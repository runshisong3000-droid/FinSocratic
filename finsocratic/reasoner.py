"""AI reasoning layer for the research agent.

The model never sees or recomputes numbers as a source of truth. It reads a
deterministic *fact sheet* built from ``run_diligence`` output and performs
qualitative work: interpreting a manager's strategy logic, finding
inconsistencies, generating falsifiable hypotheses and drafting a measured
conclusion. Every figure in the fact sheet is already computed and cited.

All functions degrade gracefully: when no LLM backend is configured they return
``None`` and the deterministic report remains the sole output.
"""
from __future__ import annotations

from typing import Any

from . import llm

MAX_CLAIMS_IN_SHEET = 48
MAX_CLAIM_TEXT = 220
MAX_EXPLANATION = 180


def _clean_number(value: Any) -> Any:
    if value is None or (isinstance(value, float) and value != value):
        return None
    if isinstance(value, float):
        return round(value, 6)
    return value


def _pct(value: Any) -> str:
    return "无法计算" if value is None else f"{value:.2%}"


def _claims_sheet(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the most decision-relevant claims: contradictions and unknowns first."""
    order = {"contradicted": 0, "inconclusive": 1, "unverifiable": 2, "supported_within_scope": 3}
    ranked = sorted(claims, key=lambda c: order.get(c.get("status"), 9))
    rows: list[dict[str, Any]] = []
    for claim in ranked[:MAX_CLAIMS_IN_SHEET]:
        rows.append({
            "status": claim.get("status_label") or claim.get("status"),
            "text": (claim.get("text") or "")[:MAX_CLAIM_TEXT],
            "核对结果": (claim.get("explanation") or "")[:MAX_EXPLANATION],
            "边界": (claim.get("limitation") or "")[:MAX_EXPLANATION],
        })
    return rows


def build_fact_sheet(result: dict[str, Any]) -> dict[str, Any]:
    """Distil a full audit result into a compact, model-readable fact sheet."""
    fund = result.get("fund", {})
    metrics = result.get("metrics", {})
    comp = result.get("benchmark_comparison", {})
    attribution = comp.get("attribution") or {}
    factor = result.get("factor_attribution", {})
    calendar = result.get("return_calendar", {})

    return {
        "基金": {
            "名称": fund.get("name"), "管理人": fund.get("manager"),
            "策略": fund.get("strategy"), "编号": fund.get("fund_id"),
        },
        "净值": {
            "区间": f"{metrics.get('start')} 至 {metrics.get('end')}",
            "观测点": metrics.get("observations"),
            "频率": metrics.get("frequency"),
            "区间收益": _pct(metrics.get("total_return")),
            "年化收益": _pct(metrics.get("annual_return")),
            "年化波动": _pct(metrics.get("volatility")),
            "最大回撤": _pct(metrics.get("max_drawdown")),
        },
        "相对基准": {
            "匹配观测": comp.get("matched_observations"),
            "相对收益(百分点)": _clean_number(comp.get("relative_return_pp")),
            "Beta": _clean_number(attribution.get("beta")),
            "Jensen Alpha(年化)": _pct(attribution.get("alpha_annualized")),
            "跟踪误差": _pct(attribution.get("tracking_error")),
            "信息比率": _clean_number(attribution.get("information_ratio")),
            "上行捕获率": _clean_number(attribution.get("up_capture_ratio")),
            "下行捕获率": _clean_number(attribution.get("down_capture_ratio")),
        },
        "多因子(Fama-French5,月频)": {
            "可用": factor.get("available"),
            "观测": factor.get("observations"),
            "年化Alpha": _pct((factor.get("metrics") or {}).get("alpha_annualized")),
            "R方": _clean_number((factor.get("metrics") or {}).get("r_squared")),
            "暴露": [{"因子": e.get("label") or e.get("factor"),
                      "系数": _clean_number(e.get("coefficient")),
                      "t值": _clean_number(e.get("t_statistic")),
                      "p值": _clean_number(e.get("p_value"))}
                     for e in factor.get("exposures", [])],
        },
        "年度收益": calendar.get("yearly", [])[:12],
        "陈述审计": _claims_sheet(result.get("claims", [])),
        "证据缺口": (result.get("insights") or {}).get("evidence_gaps", []),
        "复核优先级": (result.get("insights") or {}).get("review_priority"),
        "矛盾数": sum(1 for c in result.get("claims", []) if c.get("status") == "contradicted"),
        "待核验数": sum(1 for c in result.get("claims", []) if c.get("status") in {"inconclusive", "unverifiable"}),
    }


_SYSTEM = (
    "你是一名严格、审慎、证伪优先的公募FOF尽调研究员。"
    "你会收到一份由确定性计算生成的「事实快照」，其中的数字都已算好并溯源。"
    "你的任务是对该管理人做定性推理与批判性分析，绝不重新计算或编造任何数字，"
    "也绝不给出买卖或投资评级。你只使用快照里已提供的事实；缺失即缺失。"
)

_DILIGENCE_PROMPT = """基于下面的「事实快照」，产出一个 JSON 对象，字段如下（都用中文）：

{{
  "verdict": "一段不超过120字的审慎结论：这位管理人策略逻辑与已核实事实之间的一致程度，以及最关键的存疑点。不要给投资评级。",
  "thesis": "一段话，评估其策略逻辑、风险收益特征与行为一致性；明确区分‘已被数据支持’与‘仅来自其自述’的部分。",
  "strengths": ["2-4条，仅限能被快照数字或证据支持的可信优势"],
  "red_flags": ["2-5条，红队质疑：快照中最值得警惕的矛盾、口径疑点或证据缺失"],
  "critical_questions": ["3-5条，下一轮尽调最该追问管理人、且能拿到可验证证据的问题"],
  "hypotheses": ["2-4条，可被后续数据证伪的研究假设，每条尽量可观察、可量化"],
  "evidence_boundary": "一段话，说明现有证据能证明什么、不能证明什么。"
}}

要求：
1. 只输出一个 JSON 对象，不要 Markdown 代码块或额外文字。
2. 任何数字若未在快照中出现，一律不要自行填写；用文字描述其缺失即可。
3. 保持克制与专业，避免套话与过度肯定。

事实快照：
{sheet}
"""

_RED_TEAM_PROMPT = """请以最严厉的怀疑者视角，对下面这份「事实快照」做红队挑战，产出一个 JSON 对象（中文）：

{{
  "attacks": ["4-6条，每条用一句话指出：这份材料/数据最可能被‘看起来不错’所掩盖的风险或误导点"],
  "falsifiable_checks": ["3-5条，每条给出一个能直接证伪或证实该问题的具体检验动作（要能落地，比如索要某期持仓/交易流水/费用归因）"],
  "worst_case_reading": "一段话：在最不利但仍在事实范围内的解读下，这位管理人可能被如何评价？",
  "missing_evidence_that_matters": ["列出最影响判断却仍然缺失的证据，按重要性排序"]
}}

要求：只输出 JSON 对象，不要额外文字；不要编造快照里没有的数据；保持专业克制。

事实快照：
{sheet}
"""


def _analyze(result: dict[str, Any], prompt_template: str, *, reasoner: bool = False) -> dict[str, Any] | None:
    if not llm.is_available():
        return None
    sheet = build_fact_sheet(result)
    import json as _json
    prompt = prompt_template.format(sheet=_json.dumps(sheet, ensure_ascii=False, indent=1))
    model = llm.config()["reasoner_model"] if reasoner else None
    # ``deepseek-reasoner`` consumes output tokens for its hidden chain-of-thought
    # before emitting the answer, so a JSON-mode budget (3000) is not enough and
    # the reply comes back empty with ``finish_reason=length``.
    max_tokens = 16000 if reasoner else 3000
    return llm.json_object(prompt, model=model, temperature=0.2, max_tokens=max_tokens)


def deep_analysis(result: dict[str, Any]) -> dict[str, Any] | None:
    """Qualitative diligence synthesis; returns ``None`` without a backend."""
    return _analyze(result, _DILIGENCE_PROMPT, reasoner=False)


def red_team(result: dict[str, Any]) -> dict[str, Any] | None:
    """Adversarial challenge of the same facts; returns ``None`` without a backend."""
    return _analyze(result, _RED_TEAM_PROMPT, reasoner=True)
