"""Deterministic, source-linked FOF diligence for an offline research workflow.

This module deliberately does not call a language model or decide whether a
manager's qualitative explanation is true. It checks a small set of measurable
claims against the data supplied for this run and records the limits of each
check. All input data remains in memory.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .attribution import risk_adjusted_attribution
from .playbook import build_playbook


STATUS_LABELS = {
    "supported_within_scope": "样本范围内相符",
    "contradicted": "与已导入数据矛盾",
    "inconclusive": "证据不足以定论",
    "unverifiable": "当前无法核验",
}
_PERCENT = re.compile(r"(?<!\d)([-−+]?\d+(?:\.\d+)?)\s*[%％]")
_MATERIAL_WORDS = (
    "收益", "回报", "回撤", "波动", "风险", "基准", "超额", "跑赢", "战胜",
    "持仓", "仓位", "配置", "权益", "股票", "债券", "CTA", "市场中性",
    "策略", "流动性", "杠杆", "敞口", "开放", "赎回", "归因", "业绩",
)


def _issue(issues: list[dict[str, Any]], severity: str, code: str, message: str, count: int = 1) -> None:
    issues.append({"severity": severity, "code": code, "message": message, "count": count})


def _short_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:10].upper()}"


def _as_frame(value: pd.DataFrame | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    if not isinstance(value, pd.DataFrame):
        raise TypeError("净值、基准和持仓必须是 pandas DataFrame。")
    return value.copy()


def _column(frame: pd.DataFrame, candidates: Sequence[str]) -> str | None:
    return next((name for name in candidates if name in frame.columns), None)


def _source_name(value: object, fallback: str) -> str:
    """Use a file's basename when known; never expose a local directory path."""
    if value is None:
        return fallback
    try:
        if bool(pd.isna(value)):
            return fallback
    except (TypeError, ValueError):
        pass
    name = re.split(r"[/\\]", str(value).strip())[-1]
    name = re.sub(r"[\r\n\t]", " ", name).strip()
    return name or fallback


def _parse_date(value: object) -> object:
    """Accept ISO-like dates and YYYYMMDD integers, not ambiguous epoch numbers."""
    if isinstance(value, (int, float, np.number)) and not isinstance(value, (bool, np.bool_)):
        number = float(value)
        if math.isfinite(number) and number.is_integer() and 19000101 <= number <= 21001231:
            return pd.to_datetime(str(int(number)), format="%Y%m%d", errors="coerce")
        return pd.NaT
    return pd.to_datetime(value, errors="coerce")


def _prepare_series(
    frame: pd.DataFrame | None,
    *,
    kind: str,
    fund_id: str,
    source_label: str,
    evidence: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> pd.DataFrame:
    """Validate a time series without silently resolving conflicting dates."""
    source = _as_frame(frame)
    empty = pd.DataFrame(columns=["date", "value", "source_row", "evidence_id"])
    if source.empty:
        _issue(issues, "warning", f"{kind}_missing", f"没有可用的{'基金' if kind == 'nav' else '基准'}净值。")
        return empty
    source = source.reset_index(drop=True)
    default_rows = pd.Series(np.arange(2, len(source) + 2), index=source.index)
    source["source_row"] = (pd.to_numeric(source["source_row"], errors="coerce").fillna(default_rows).astype(int)
                            if "source_row" in source else default_rows)
    source["source_file"] = (source["source_file"].map(lambda value: _source_name(value, source_label))
                             if "source_file" in source else source_label)
    if kind == "nav" and "fund_id" in source:
        source = source.loc[source["fund_id"].astype(str) == fund_id].copy()
        if source.empty:
            _issue(issues, "error", "fund_nav_missing", f"净值表中没有基金 {fund_id} 的记录。")
            return empty
    if kind == "benchmark" and "fund_id" in source and source["fund_id"].nunique(dropna=True) > 1:
        _issue(issues, "error", "benchmark_ambiguous", "基准表包含多条序列；请只提供一条明确的基准序列。")
        return empty
    date_col = _column(source, ("date", "日期", "as_of"))
    value_col = _column(source, ("nav", "benchmark_nav", "value", "close", "净值", "累计净值"))
    if date_col is None or value_col is None:
        _issue(issues, "error", f"{kind}_columns", f"{kind} 需要日期列和净值列。")
        return empty
    source["date"] = source[date_col].map(_parse_date)
    source["value"] = pd.to_numeric(source[value_col], errors="coerce")
    valid = source["date"].notna() & np.isfinite(source["value"].astype(float)) & (source["value"] > 0)
    invalid_count = int((~valid).sum())
    if invalid_count:
        _issue(issues, "warning", f"{kind}_invalid_rows", f"{kind} 有 {invalid_count} 行日期或净值无效，已排除。", invalid_count)
    source = source.loc[valid, ["date", "value", "source_row", "source_file"]].copy()
    if source.empty:
        return empty
    duplicate = source.duplicated("date", keep=False)
    if duplicate.any():
        conflict_dates = source.loc[duplicate].groupby("date")["value"].nunique()
        conflict_dates = conflict_dates.index[conflict_dates > 1]
        if len(conflict_dates):
            _issue(issues, "error", f"{kind}_conflicting_dates", f"{kind} 有 {len(conflict_dates)} 个日期包含互相冲突的净值，相关日期已全部排除。", len(conflict_dates))
            source = source.loc[~source["date"].isin(conflict_dates)].copy()
        exact_count = int(source.duplicated("date", keep="first").sum())
        if exact_count:
            _issue(issues, "warning", f"{kind}_duplicate_dates", f"{kind} 有 {exact_count} 条同日同值的重复记录，已去重。", exact_count)
            source = source.drop_duplicates("date", keep="first")
    source = source.sort_values("date").reset_index(drop=True)
    if len(source) < 2:
        _issue(issues, "warning", f"{kind}_short_history", f"{kind} 少于两个有效日期，无法计算区间收益。")
    source["evidence_id"] = [
        _short_id(kind.upper(), fund_id if kind == "nav" else "benchmark", date.date(), float(value))
        for date, value in zip(source["date"], source["value"])
    ]
    for row in source.itertuples(index=False):
        evidence.append({
            "id": row.evidence_id,
            "kind": "observation",
            "role": kind,
            "source": row.source_file,
            "location": f"第 {row.source_row} 行 · {row.date:%Y-%m-%d}",
            "text": f"净值 {row.value:.8g}",
        })
    return source


def _frequency(dates: pd.Series) -> tuple[str, int | None]:
    if len(dates) < 3:
        return "样本不足", None
    gaps = dates.diff().dropna().dt.days
    median = float(gaps.median())
    # Rely on the median gap, which is robust to occasional holiday gaps in an
    # otherwise daily series or a single missing month in a monthly series.
    if 1 <= median <= 4:
        return "近似日频", 252
    if 5 <= median <= 10:
        return "近似周频", 52
    if 20 <= median <= 45:
        return "近似月频", 12
    if 70 <= median <= 110:
        return "近似季频", 4
    return "不规则频率", None


def _calculate_metrics(
    track: pd.DataFrame,
    evidence: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "observations": len(track), "start": None, "end": None,
        "frequency": "样本不足", "total_return": None, "annual_return": None,
        "volatility": None, "max_drawdown": None, "drawdown_peak": None,
        "drawdown_trough": None, "calculation_evidence_ids": {},
        "assumptions": ["输入净值视为同一口径的可比净值；未独立验证分红、费用或复权处理。"],
    }
    if track.empty:
        return metrics
    metrics["start"] = track.iloc[0]["date"].strftime("%Y-%m-%d")
    metrics["end"] = track.iloc[-1]["date"].strftime("%Y-%m-%d")
    frequency, periods = _frequency(track["date"])
    metrics["frequency"] = frequency
    if len(track) < 2:
        return metrics
    values = track["value"].astype(float).reset_index(drop=True)
    total = float(values.iloc[-1] / values.iloc[0] - 1)
    elapsed_days = int((track.iloc[-1]["date"] - track.iloc[0]["date"]).days)
    annual = float((values.iloc[-1] / values.iloc[0]) ** (365.25 / elapsed_days) - 1) if elapsed_days > 0 else None
    drawdowns = values / values.cummax() - 1
    trough_idx = int(drawdowns.idxmin())
    peak_idx = int(values.iloc[:trough_idx + 1].idxmax())
    metrics.update({
        "total_return": total,
        "annual_return": annual,
        "max_drawdown": float(drawdowns.iloc[trough_idx]),
        "drawdown_peak": track.iloc[peak_idx]["date"].strftime("%Y-%m-%d"),
        "drawdown_trough": track.iloc[trough_idx]["date"].strftime("%Y-%m-%d"),
    })
    if elapsed_days < 365:
        _issue(issues, "warning", "short_annualization", "样本不足一年；年化收益仅是区间端点推算，不应视作稳健长期预期。")
    if periods is not None and len(values) >= 4:
        returns = values.pct_change().dropna()
        metrics["volatility"] = float(returns.std(ddof=1) * math.sqrt(periods))
        metrics["assumptions"].append(f"波动率使用相邻净值简单收益率的样本标准差，按每年 {periods} 期年化。")
    elif periods is None:
        _issue(issues, "warning", "irregular_frequency", "净值日期频率不规则，未计算年化波动率。")
    input_ids = track["evidence_id"].tolist()
    definitions = {
        "total_return": "期末净值 / 期初净值 - 1",
        "annual_return": "(期末净值 / 期初净值)^(365.25 / 区间天数) - 1",
        "max_drawdown": "min(净值 / 截至该日的最高净值 - 1)",
        "volatility": f"std(相邻净值收益率, ddof=1) × sqrt({periods})" if periods else "",
    }
    for metric, formula in definitions.items():
        value = metrics[metric]
        if value is None:
            continue
        calc_id = f"CALC-{metric.upper()}"
        metrics["calculation_evidence_ids"][metric] = calc_id
        evidence.append({
            "id": calc_id, "kind": "calculation", "source": "确定性计算",
            "location": f"{metrics['start']} 至 {metrics['end']}；{len(track)} 个净值点",
            "text": f"{formula} = {value:.8f}", "input_evidence_ids": input_ids,
        })
    return metrics


def _prepare_holdings(
    holdings: pd.DataFrame | None,
    fund_id: str,
    source_label: str,
    evidence: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    frame = _as_frame(holdings)
    result: dict[str, Any] = {"available": False, "as_of": None, "weight_sum": None, "assets": {}, "evidence_ids": {}}
    if frame.empty:
        _issue(issues, "warning", "holdings_missing", "没有该基金的持仓快照；配置陈述无法量化核验。")
        return result
    required = {"fund_id", "asset", "weight_pct"}
    if not required.issubset(frame.columns):
        _issue(issues, "error", "holdings_columns", "持仓表需要 fund_id、asset、weight_pct 列。")
        return result
    frame = frame.reset_index(drop=True)
    default_rows = pd.Series(np.arange(2, len(frame) + 2), index=frame.index)
    frame["source_row"] = (pd.to_numeric(frame["source_row"], errors="coerce").fillna(default_rows).astype(int)
                           if "source_row" in frame else default_rows)
    frame["source_file"] = (frame["source_file"].map(lambda value: _source_name(value, source_label))
                            if "source_file" in frame else source_label)
    frame = frame.loc[frame["fund_id"].astype(str) == fund_id].copy()
    if frame.empty:
        _issue(issues, "warning", "fund_holdings_missing", f"持仓表中没有基金 {fund_id} 的记录。")
        return result
    if "as_of" in frame:
        frame["as_of"] = frame["as_of"].map(_parse_date)
        undated_count = int(frame["as_of"].isna().sum())
        if undated_count:
            _issue(issues, "warning", "holdings_invalid_dates", f"持仓有 {undated_count} 行日期无效；有有效日期时仅采用最新有效快照。", undated_count)
        latest = frame["as_of"].max()
        if pd.notna(latest):
            frame = frame.loc[frame["as_of"] == latest].copy()
            result["as_of"] = latest.strftime("%Y-%m-%d")
    if result["as_of"] is None:
        _issue(issues, "warning", "holdings_undated", "持仓快照没有有效日期，无法确认与报告期间一致。")
    frame["weight_pct"] = pd.to_numeric(frame["weight_pct"], errors="coerce")
    valid = frame["asset"].notna() & frame["asset"].astype(str).str.strip().ne("") & frame["weight_pct"].between(0, 100)
    invalid_count = int((~valid).sum())
    if invalid_count:
        _issue(issues, "warning", "holdings_invalid_rows", f"持仓快照有 {invalid_count} 行资产名称或权重无效，已排除。", invalid_count)
    frame = frame.loc[valid].copy()
    if frame.empty:
        return result
    result["available"] = True
    result["weight_sum"] = float(frame["weight_pct"].sum())
    if abs(result["weight_sum"] - 100) > 1:
        _issue(issues, "warning", "holdings_incomplete", f"最新持仓快照权重合计 {result['weight_sum']:.2f}%，不是完整的 100%。")
    for row in frame.itertuples(index=False):
        asset = str(row.asset).strip()
        item_id = _short_id("HOLD", fund_id, result["as_of"], row.source_row, asset, row.weight_pct)
        result["assets"][asset] = result["assets"].get(asset, 0.0) + float(row.weight_pct)
        result["evidence_ids"].setdefault(asset, []).append(item_id)
        evidence.append({
            "id": item_id, "kind": "observation", "role": "holdings", "source": row.source_file,
            "location": f"第 {row.source_row} 行 · {result['as_of'] or '日期未知'}",
            "text": f"{asset}：{row.weight_pct:.2f}%",
        })
    return result


def _normalize_documents(
    documents: Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | None,
    *,
    prefix: str,
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if documents is None:
        return []
    if isinstance(documents, str):
        documents = [{"name": "输入报告", "chunks": [
            {"location": f"第 {number} 行", "text": line}
            for number, line in enumerate(documents.splitlines(), 1) if line.strip()
        ]}]
    elif isinstance(documents, Mapping):
        documents = [documents]
    out: list[dict[str, str]] = []
    for doc_index, doc in enumerate(documents, 1):
        name = str(doc.get("name") or doc.get("file") or f"报告 {doc_index}")
        chunks = doc.get("chunks")
        if chunks is None:
            chunks = [{"location": doc.get("location", "全文"), "text": doc.get("text", "")}]
        full_text = "\n".join(str(c.get("text", "")) for c in chunks)
        report_match = re.search(r"报告日期[：:]\s*(\d{4}-\d{2}-\d{2})", full_text)
        report_date = report_match.group(1) if report_match else ""
        skip_section = False
        for chunk_index, chunk in enumerate(chunks, 1):
            body = str(chunk.get("text") or "").strip()
            if not body:
                continue
            location = str(chunk.get("location") or f"片段 {chunk_index}")
            item_id = _short_id(prefix, name, location, body)
            evidence.append({"id": item_id, "kind": "source_text", "source": name, "location": location, "text": body})
            if body in ("证据边界", "资料请求", "免责声明"):
                skip_section = True
            out.append({"id": item_id, "source": name, "location": location, "text": body,
                        "report_date": report_date, "skip_claims": skip_section})
    return out


def _split_claims(chunks: list[dict[str, str]]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        if chunk.get("skip_claims") or chunk["text"].startswith(("资料核验提示", "本演示纪要", "免责声明", "合成演示资料")):
            continue
        for clause in re.split(r"[。！？!?；;，,\n]+", chunk["text"]):
            clause = clause.strip(" \t：:。")
            if len(clause) < 5 or not any(word in clause for word in _MATERIAL_WORDS):
                continue
            if clause.startswith(("演示资料", "资料核验提示", "本演示", "免责声明")):
                continue
            if clause.endswith(("沟通纪要", "研究报告", "月度报告", "季度报告")):
                continue
            key = (chunk["id"], clause)
            if key in seen:
                continue
            seen.add(key)
            claims.append({
                "id": _short_id("CLAIM", chunk["id"], clause),
                "text": clause, "source": chunk["source"],
                "location": chunk["location"], "source_evidence_id": chunk["id"],
                "report_date": chunk.get("report_date", ""), "context": chunk["text"],
            })
    return claims


def _metric_check(
    claim: str, value: float | None, metric: str, calc_id: str | None, *, frequency: str | None = None
) -> tuple[str, str, str, list[str]]:
    match = _PERCENT.search(claim)
    if match is None:
        return "unverifiable", "陈述未给出可比较的百分比。", "需要明确期间、口径和数值。", []
    if value is None:
        return "unverifiable", "没有足够的有效净值计算该指标。", "需要相同口径的完整净值序列。", []
    stated = float(match.group(1).replace("−", "-"))
    if metric == "max_drawdown":
        stated = abs(stated)
    observed = abs(value) * 100 if metric == "max_drawdown" else value * 100
    upper_bound = any(word in claim for word in ("不超过", "以内", "以下", "低于", "小于", "控制在"))
    lower_bound = any(word in claim for word in ("不低于", "至少", "以上", "超过", "高于"))
    tolerance = 0.5
    agrees = (observed <= stated + tolerance if upper_bound else
              observed >= stated - tolerance if lower_bound else
              abs(observed - stated) <= tolerance)
    status = "supported_within_scope" if agrees else "contradicted"
    relation = "上限" if upper_bound else "下限" if lower_bound else "报告值"
    explanation = f"管理人{relation} {stated:g}%；已导入净值计算值 {observed:.2f}%。"
    limitation = "仅覆盖已导入净值日期；历史净值的分红、费用及复权口径尚待核对。"
    if metric == "max_drawdown":
        limitation += " 离散净值不能排除观测日之间更深的回撤。"
        if upper_bound and agrees and frequency != "近似日频":
            status = "inconclusive"
            explanation += " 当前采样频率不足以证明整个期间的回撤上限。"
    return status, explanation, limitation, [calc_id] if calc_id else []


def _evaluate_claim(
    claim: dict[str, str],
    metrics: dict[str, Any],
    allocation: dict[str, Any],
    benchmark_result: dict[str, Any],
) -> dict[str, Any]:
    text = claim["text"]
    check_ids: list[str] = []
    if "最大回撤" in text or "回撤控制" in text or "drawdown" in text.lower():
        topic = "最大回撤"
        status, explanation, limitation, check_ids = _metric_check(
            text, metrics["max_drawdown"], "max_drawdown", metrics["calculation_evidence_ids"].get("max_drawdown"),
            frequency=metrics["frequency"],
        )
        follow_up = "请提供对应期间的日频或更高频率净值，并确认回撤与复权口径。"
    elif any(word in text for word in ("年化收益", "年化回报", "annual return")):
        topic = "年化收益"
        status, explanation, limitation, check_ids = _metric_check(
            text, metrics["annual_return"], "annual_return", metrics["calculation_evidence_ids"].get("annual_return")
        )
        follow_up = "请确认年化计算起止日期、分红再投资和费用口径。"
    elif any(word in text for word in ("累计收益", "区间收益", "总收益")):
        topic = "区间收益"
        status, explanation, limitation, check_ids = _metric_check(
            text, metrics["total_return"], "total_return", metrics["calculation_evidence_ids"].get("total_return")
        )
        follow_up = "请提供收益对应的起止日期与净值口径。"
    elif any(word in text for word in ("归因", "来自", "源于", "贡献")) and any(word in text for word in ("收益", "回报", "超额")):
        topic = "收益归因"
        status = "unverifiable"
        explanation = "净值和基准端点只能描述结果，不能证明收益由某项策略贡献。"
        limitation = "缺少策略级净值、逐期权重、交易流水及风险归因数据。"
        follow_up = "请提供策略级收益贡献、逐期持仓、费用和交易记录，说明归因方法。"
    elif (("基准" in text and any(word in text for word in ("跑赢", "战胜", "优于", "领先")))
          or "超额收益" in text):
        topic = "基准比较"
        excess = benchmark_result.get("relative_return_pp")
        check_ids = [benchmark_result["evidence_id"]] if benchmark_result.get("evidence_id") else []
        if excess is None:
            status, explanation = "unverifiable", "基金和基准缺少至少两个完全匹配的日期。"
        elif excess < 0:
            status, explanation = "contradicted", f"匹配日期端点计算的基金收益低于基准 {abs(excess):.2f} 个百分点。"
        elif "持续" in text or "始终" in text:
            status, explanation = "inconclusive", f"匹配日期端点收益高于基准 {excess:.2f} 个百分点，但不能证明每个子期间持续领先。"
        else:
            status, explanation = "supported_within_scope", f"匹配日期端点收益高于基准 {excess:.2f} 个百分点。"
        limitation = "仅使用基金和基准完全相同日期的净值端点；未验证基准选择、风险调整或因果归因。"
        follow_up = "请说明基准选择依据，并提供逐期超额收益与风险调整结果。"
    elif _PERCENT.search(text) and any(word in text for word in ("仓位", "配置", "权益", "股票", "债券", "CTA", "市场中性")):
        topic = "组合配置"
        match = _PERCENT.search(text)
        stated = float(match.group(1).replace("−", "-")) if match else None
        asset = next((name for name in sorted(allocation["assets"], key=len, reverse=True) if name in text), None)
        if asset is None:
            status, explanation, limitation = "unverifiable", "无法将陈述可靠映射到持仓快照中的资产类别。", "需要同口径的类别定义及对应日期的持仓快照。"
        else:
            topic = f"组合配置：{asset}"
            observed = allocation["assets"][asset]
            check_ids = allocation["evidence_ids"].get(asset, [])
            status = "supported_within_scope" if abs(observed - stated) <= 0.5 else "contradicted"
            explanation = f"管理人陈述 {stated:g}%；{asset} 最新快照合计 {observed:.2f}%。"
            limitation = f"持仓快照日期为 {allocation['as_of'] or '未知'}；无法由单一快照证明整个报告期间的平均仓位。"
            if allocation["as_of"] is None and status == "supported_within_scope":
                status = "inconclusive"
            if allocation["weight_sum"] is not None and abs(allocation["weight_sum"] - 100) > 1:
                status = "inconclusive" if status == "supported_within_scope" else status
                limitation += " 快照权重未合计至 100%。"
        follow_up = "请提供报告期末完整持仓、资产类别映射与权重口径。"
    else:
        topic = "定性或不可映射陈述"
        status = "unverifiable"
        explanation = "当前材料不足以把这项陈述转化为可靠的独立检验；文本相似度不构成真实性证据。"
        limitation = "需要可定位的外部记录、相关持仓、交易或风险归因资料，并由研究员判断。"
        follow_up = "请说明该陈述的具体期间、可观察指标，并提供能排除其他解释的原始证据。"
    return {
        **claim, "topic": topic, "status": status, "status_label": STATUS_LABELS[status],
        "explanation": explanation, "limitation": limitation,
        "check_evidence_ids": check_ids, "follow_up": follow_up,
    }


def _benchmark_comparison(
    nav: pd.DataFrame, benchmark: pd.DataFrame, evidence: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {"matched_observations": 0, "start": None, "end": None, "fund_return": None,
                              "benchmark_return": None, "relative_return_pp": None, "evidence_id": None,
                              "attribution": None, "attribution_observations": None,
                              "attribution_periods_per_year": None, "rolling_beta": [],
                              "attribution_assumptions": []}
    if nav.empty or benchmark.empty:
        return result
    matched = nav.merge(benchmark, on="date", suffixes=("_fund", "_benchmark")).sort_values("date").reset_index(drop=True)
    result["matched_observations"] = len(matched)
    if len(matched) < 2:
        _issue(issues, "warning", "benchmark_alignment", "基金与基准没有至少两个相同日期的观测，未作收益比较。")
        return result
    first, last = matched.iloc[0], matched.iloc[-1]
    fund_return = float(last["value_fund"] / first["value_fund"] - 1)
    benchmark_return = float(last["value_benchmark"] / first["value_benchmark"] - 1)
    result.update({
        "start": first["date"].strftime("%Y-%m-%d"), "end": last["date"].strftime("%Y-%m-%d"),
        "fund_return": fund_return, "benchmark_return": benchmark_return,
        "relative_return_pp": (fund_return - benchmark_return) * 100,
        "evidence_id": "CALC-BENCHMARK",
    })
    input_ids = matched["evidence_id_fund"].tolist() + matched["evidence_id_benchmark"].tolist()
    evidence.append({
        "id": "CALC-BENCHMARK", "kind": "calculation", "source": "确定性计算",
        "location": f"{result['start']} 至 {result['end']}；{len(matched)} 个匹配日期",
        "text": f"(基金期末/期初-1) - (基准期末/期初-1) = {result['relative_return_pp']:.4f} 个百分点",
        "input_evidence_ids": input_ids,
    })
    if len(matched) >= 3:
        fund_returns = matched["value_fund"].astype(float).pct_change()
        benchmark_returns = matched["value_benchmark"].astype(float).pct_change()
        valid = fund_returns.notna() & benchmark_returns.notna()
        fund_returns = fund_returns.loc[valid].reset_index(drop=True)
        benchmark_returns = benchmark_returns.loc[valid].reset_index(drop=True)
        return_dates = pd.to_datetime(matched.loc[valid, "date"]).reset_index(drop=True)
        periods = _frequency(pd.to_datetime(matched["date"]))[1]
        attribution = risk_adjusted_attribution(
            fund_returns, benchmark_returns, periods_per_year=periods, dates=return_dates,
        )
        result["attribution"] = attribution["metrics"]
        result["attribution_observations"] = attribution["observations"]
        result["attribution_periods_per_year"] = attribution["periods_per_year"]
        result["rolling_beta"] = attribution["rolling_beta"]
        result["attribution_assumptions"] = attribution["assumptions"]
        for key, value in attribution["metrics"].items():
            if value is None:
                continue
            calc_id = f"CALC-ATTR-{key.upper()}"
            evidence.append({
                "id": calc_id, "kind": "calculation", "source": "确定性计算",
                "location": f"{result['start']} 至 {result['end']}；{attribution['observations']} 个收益期",
                "text": f"{attribution['formulas'][key]} = {value:.6f}",
                "input_evidence_ids": input_ids,
            })
    return result


def _return_calendar(track: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Yearly returns and a year × month return calendar from a cleaned NAV track."""
    if track.empty or len(track) < 2:
        return {"yearly": [], "monthly": []}
    monthly = track.set_index("date")["value"].resample("ME").last().pct_change().dropna()
    if monthly.empty:
        return {"yearly": [], "monthly": []}
    yearly_rows = [{"year": int(year), "return": float((1 + group).prod() - 1), "months": int(group.count())}
                   for year, group in monthly.groupby(monthly.index.year)]
    monthly_rows: list[dict[str, Any]] = []
    for year, group in monthly.groupby(monthly.index.year):
        row: dict[str, Any] = {"year": int(year)}
        for month in range(1, 13):
            value = group[group.index.month == month]
            row[f"{month}月"] = float(value.iloc[0]) if len(value) else None
        row["全年"] = float((1 + group).prod() - 1)
        monthly_rows.append(row)
    return {"yearly": yearly_rows, "monthly": monthly_rows}


def _factor_attribution(
    nav: pd.DataFrame,
    factors: pd.DataFrame | None,
    evidence: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Multi-factor (Fama-French) return attribution, aligned on monthly periods."""
    result: dict[str, Any] = {"available": False, "observations": 0, "metrics": {}, "exposures": [],
                              "factor_names": [], "assumptions": []}
    if nav.empty or factors is None or factors.empty:
        return result
    if len(nav) < 3:
        return result
    from .factor import factor_regression
    monthly = nav.set_index("date")["value"].resample("ME").last().pct_change().dropna()
    if monthly.empty:
        return result
    factor_frame = factors.set_index("date") if "date" in factors.columns else factors
    regression = factor_regression(monthly, factor_frame, periods_per_year=12)
    result["available"] = regression["observations"] > 0
    result["observations"] = regression["observations"]
    result["metrics"] = regression.get("metrics", {})
    result["exposures"] = regression.get("exposures", [])
    result["factor_names"] = regression.get("factor_names", [])
    result["assumptions"] = regression.get("assumptions", [])
    if result["available"]:
        nav_ids = nav["evidence_id"].tolist() if "evidence_id" in nav.columns else []
        metrics = result["metrics"]
        formulas = regression.get("formulas", {})
        for key, label, formula in (
            ("alpha_annualized", "年化Alpha（截距）", formulas.get("alpha_annualized", "(1+截距)^12-1")),
            ("r_squared", "R²", formulas.get("r_squared", "1-RSS/TSS")),
            ("adj_r_squared", "调整R²", formulas.get("adj_r_squared", "1-(1-R²)(n-1)/(n-k-1)")),
        ):
            value = metrics.get(key)
            if value is None:
                continue
            calc_id = f"CALC-FF-{key.upper()}"
            evidence.append({
                "id": calc_id, "kind": "calculation", "source": "确定性计算",
                "location": f"多因子回归；{result['observations']} 个对齐月度观测",
                "text": f"{formula} = {value:.6f}", "input_evidence_ids": nav_ids,
            })
    return result


def _compare_periods(current: list[dict[str, Any]], previous: list[dict[str, str]]) -> list[dict[str, str]]:
    old_by_topic: dict[str, list[dict[str, str]]] = {}
    for claim in previous:
        text = claim["text"]
        if "最大回撤" in text or "回撤控制" in text:
            topic = "最大回撤"
        elif "年化收益" in text or "年化回报" in text:
            topic = "年化收益"
        elif any(word in text for word in ("归因", "来自", "源于", "贡献")) and any(word in text for word in ("收益", "回报")):
            topic = "收益归因"
        elif ("基准" in text and any(word in text for word in ("跑赢", "战胜", "优于", "领先"))) or "超额收益" in text:
            topic = "基准比较"
        elif any(word in text for word in ("仓位", "配置", "权益", "股票", "债券", "CTA")):
            topic = "组合配置"
        else:
            topic = "定性或不可映射陈述"
        old_by_topic.setdefault(topic, []).append(claim)
    comparisons = []
    for claim in current:
        topic = "组合配置" if claim["topic"].startswith("组合配置") else claim["topic"]
        candidates = old_by_topic.get(topic, [])
        if claim["topic"].startswith("组合配置："):
            asset = claim["topic"].split("：", 1)[1]
            candidates = [prior for prior in candidates if asset in prior["text"]]
        for prior in candidates[:1]:
            current_pct = _PERCENT.search(claim["text"])
            prior_pct = _PERCENT.search(prior["text"])
            numeric_shift = bool(current_pct and prior_pct)
            current_value = float(current_pct.group(1).replace("−", "-")) if current_pct else None
            prior_value = float(prior_pct.group(1).replace("−", "-")) if prior_pct else None
            delta_pp = (current_value - prior_value) if numeric_shift else None
            if numeric_shift:
                assessment = (
                    f"披露比例由 {prior_value:g}% 变为 {current_value:g}%"
                    f"（{delta_pp:+.1f} 个百分点）；需核对两个报告期与资产分类口径。"
                )
            elif claim["text"] == prior["text"]:
                assessment = "表述相同；仍需确认两个报告期的可观察数据与口径。"
            else:
                assessment = "表述有变化；不同期间的差异本身不证明矛盾，需追问变化原因与证据。"
            comparisons.append({
                "topic": topic, "current_claim_id": claim["id"], "prior_claim_id": prior["id"],
                "prior_source_evidence_id": prior["source_evidence_id"],
                "assessment": assessment,
                "change_type": "numeric_shift" if numeric_shift else "same" if claim["text"] == prior["text"] else "narrative_shift",
                "delta_pp": delta_pp,
                "current_text": claim["text"], "prior_text": prior["text"],
            })
    return comparisons


def _build_insights(
    fund: Mapping[str, Any], metrics: Mapping[str, Any], allocation: Mapping[str, Any],
    benchmark: Mapping[str, Any], claims: list[dict[str, Any]], comparisons: list[dict[str, Any]],
    issues: list[dict[str, Any]], evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create factual highlights for the workbench without adding model-made facts."""
    contradicted = [item for item in claims if item["status"] == "contradicted"]
    uncertain = [item for item in claims if item["status"] in {"inconclusive", "unverifiable"}]
    checked = [item for item in claims if item["check_evidence_ids"]]
    gaps = [item["message"] for item in issues if item["severity"] == "error"]
    if metrics["observations"] < 2:
        gaps.append("缺少两期可比净值，收益与风险结论无法建立。")
    if not allocation["available"]:
        gaps.append("缺少可用的最新持仓快照，组合配置尚无法核对。")
    if not claims:
        gaps.append("尚无可识别的现期管理人陈述。")
    if benchmark["matched_observations"] < 2:
        gaps.append("缺少同日可比基准，不能检查超额收益说法。")
    priority = "高" if contradicted or any(i["severity"] == "error" for i in issues) else "中" if uncertain or gaps else "常规"
    top_assets = sorted(allocation["assets"].items(), key=lambda item: item[1], reverse=True)[:3]
    return {
        "review_priority": priority,
        "claim_coverage_pct": round(len(checked) / len(claims) * 100, 1) if claims else 0.0,
        "source_count": len({item["source"] for item in evidence if item["kind"] != "calculation"}),
        "contradicted_claim_ids": [item["id"] for item in contradicted],
        "uncertain_claim_ids": [item["id"] for item in uncertain],
        "top_exposures": [{"asset": asset, "weight_pct": weight} for asset, weight in top_assets],
        "narrative_changes": len([item for item in comparisons if item["change_type"] != "same"]),
        "evidence_gaps": gaps,
        "headline": (
            f"{fund.get('manager') or '该管理人'}：{len(claims)} 项陈述中 "
            f"{len(contradicted)} 项与已导入数据矛盾、{len(uncertain)} 项仍待核验；"
            f"复核优先级为{priority}。"
        ),
    }


def run_diligence(
    fund: pd.Series | Mapping[str, Any],
    nav: pd.DataFrame,
    holdings: pd.DataFrame | None,
    documents: Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | None,
    *,
    benchmark: pd.DataFrame | None = None,
    prior_documents: Sequence[Mapping[str, Any]] | Mapping[str, Any] | str | None = None,
    source_labels: Mapping[str, str] | None = None,
    factors: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run one FOF evidence audit entirely offline, returning JSON-ready records.

    Documents use the format returned by ``library.extract_document``:
    ``[{"name": "report.pdf", "chunks": [{"location": "第 2 页", "text": "..."}]}]``.
    A single document dictionary or plain text is accepted for convenience.
    ``benchmark`` is a separate date/NAV DataFrame. ``factors`` is an optional
    monthly factor DataFrame (e.g. Fama-French columns ``mkt_rf, smb, hml, rmw,
    cma, rf`` plus a ``date`` column) used for supplementary multi-factor
    attribution. No retrieval result alone ever changes a claim's status. An
    optional ``source_file`` column on each numeric table names each row's
    original file; ``source_labels`` provides a fallback filename by table role.
    """
    if not isinstance(fund, (pd.Series, Mapping)):
        raise TypeError("fund 必须是基金记录字典或 pandas Series。")
    fund_info = dict(fund)
    fund_id = str(fund_info.get("fund_id") or "")
    if not fund_id:
        raise ValueError("fund 需要 fund_id。")
    if source_labels is not None and not isinstance(source_labels, Mapping):
        raise TypeError("source_labels 必须是 nav、holdings、benchmark 文件名映射。")
    supplied_labels = source_labels or {}
    labels = {
        "nav": _source_name(supplied_labels.get("nav"), "基金净值"),
        "holdings": _source_name(supplied_labels.get("holdings"), "持仓快照"),
        "benchmark": _source_name(supplied_labels.get("benchmark"), "业绩基准净值"),
    }
    evidence: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    clean_nav = _prepare_series(nav, kind="nav", fund_id=fund_id, source_label=labels["nav"], evidence=evidence, issues=issues)
    clean_benchmark = (_prepare_series(benchmark, kind="benchmark", fund_id=fund_id, source_label=labels["benchmark"],
                                       evidence=evidence, issues=issues) if benchmark is not None else pd.DataFrame())
    metrics = _calculate_metrics(clean_nav, evidence, issues)
    allocation = _prepare_holdings(holdings, fund_id, labels["holdings"], evidence, issues)
    benchmark_result = _benchmark_comparison(clean_nav, clean_benchmark, evidence, issues)
    factor_attribution = _factor_attribution(clean_nav, factors, evidence, issues)
    return_calendar = _return_calendar(clean_nav)
    current_chunks = _normalize_documents(documents, prefix="DOC", evidence=evidence)
    prior_chunks = _normalize_documents(prior_documents, prefix="PRIOR", evidence=evidence)
    if not current_chunks:
        _issue(issues, "warning", "report_missing", "没有可提取的现期报告正文，无法抽取管理人陈述。")
    claims = []
    scoped_cache = {}
    for item in _split_claims(current_chunks):
        claim_metrics = metrics
        window = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:至|到)\s*(\d{4}-\d{2}-\d{2})", item["context"])
        year = re.search(r"(20\d{2})\s*年", item["text"])
        metric_text = any(word in item["text"] for word in ("最大回撤", "回撤控制", "年化收益", "年化回报", "累计收益", "区间收益", "总收益"))
        incomplete = False
        if metric_text and (window or year):
            start = window.group(1) if window else f"{int(year.group(1))-1}-12-31"
            end = window.group(2) if window else f"{year.group(1)}-12-31"
            key = (start, end)
            if key not in scoped_cache:
                selected = clean_nav.loc[clean_nav["date"].between(pd.Timestamp(start), pd.Timestamp(end))]
                local_evidence = []
                scoped = _calculate_metrics(selected, local_evidence, [])
                suffix = f"-{start}-{end}"
                for entry in local_evidence:
                    entry["id"] += suffix
                scoped["calculation_evidence_ids"] = {k:v+suffix for k,v in scoped["calculation_evidence_ids"].items()}
                evidence.extend(local_evidence)
                scoped_cache[key] = scoped
            claim_metrics = scoped_cache[key]
            incomplete = claim_metrics.get("start") != start or claim_metrics.get("end") != end
        evaluated = _evaluate_claim(item, claim_metrics, allocation, benchmark_result)
        if metric_text and (window or year):
            evaluated["analysis_window"] = {"requested_start": start, "requested_end": end, "observed_start": claim_metrics.get("start"), "observed_end": claim_metrics.get("end")}
            evaluated["limitation"] += f" 本项按 {start} 至 {end} 单独取样。"
            if incomplete and evaluated["status"] in ("supported_within_scope", "contradicted"):
                evaluated.update(status="inconclusive", status_label=STATUS_LABELS["inconclusive"], explanation="请求期间的起止观测不完整，不能使用其他期间的结果替代。" )
        if evaluated["topic"].startswith("组合配置") and item.get("report_date") and allocation.get("as_of") != item["report_date"]:
            evaluated.update(status="inconclusive", status_label=STATUS_LABELS["inconclusive"], explanation="持仓快照日期与报告日期不同，需要同日期资料才能核验。", check_evidence_ids=[])
        if item["source"].lower().endswith(".pdf") and evaluated["status"] in ("supported_within_scope", "contradicted"):
            evaluated.update(status="inconclusive", status_label=STATUS_LABELS["inconclusive"], explanation="PDF 自动抽取可能丢失表格行列与期间对应关系，请在原始页核对后录入明确陈述。")
        claims.append(evaluated)
    previous_claims = _split_claims(prior_chunks)
    comparisons = _compare_periods(claims, previous_claims) if previous_claims else []
    questions: list[dict[str, Any]] = []
    seen_questions: set[str] = set()
    for claim in claims:
        if claim["status"] == "supported_within_scope" and "离散净值" not in claim["limitation"]:
            continue
        question = claim["follow_up"]
        if question not in seen_questions:
            seen_questions.add(question)
            questions.append({
                "id": _short_id("Q", question), "question": question,
                "related_claim_ids": [claim["id"]],
                "priority": "高" if claim["status"] == "contradicted" else "中",
            })
        else:
            existing = next(item for item in questions if item["question"] == question)
            existing["related_claim_ids"].append(claim["id"])
            if claim["status"] == "contradicted":
                existing["priority"] = "高"
    for issue in issues:
        if issue["severity"] != "error":
            continue
        question = f"请修复输入数据：{issue['message']}"
        questions.append({"id": _short_id("Q", question), "question": question, "related_claim_ids": [], "priority": "高"})
    status_counts = {key: sum(claim["status"] == key for claim in claims) for key in STATUS_LABELS}
    summary = (
        f"{fund_info.get('name') or fund_id}：离线审计了 {len(claims)} 项可识别的管理人陈述；"
        f"样本范围内相符 {status_counts['supported_within_scope']} 项，"
        f"与数据矛盾 {status_counts['contradicted']} 项，"
        f"证据不足或无法核验 {status_counts['inconclusive'] + status_counts['unverifiable']} 项。"
        " 结论仅适用于已导入的资料和数据，需由研究员复核后用于投资判断。"
    )
    input_sources = {
        role: sorted({item["source"] for item in evidence if item.get("role") == role})
        for role in ("nav", "holdings", "benchmark")
    }
    profile = {
        "fund_id": fund_id,
        "name": str(fund_info.get("name") or fund_id),
        "manager": str(fund_info.get("manager") or "未知"),
        "strategy": str(fund_info.get("strategy") or "未知"),
    }
    for field in ("asset_class", "region", "inception", "liquidity", "description"):
        value = fund_info.get(field)
        profile[field] = str(value) if value is not None and not pd.isna(value) else None
    fee = pd.to_numeric(fund_info.get("fee_pct"), errors="coerce")
    profile["fee_pct"] = float(fee) if pd.notna(fee) else None
    insights = _build_insights(profile, metrics, allocation, benchmark_result, claims, comparisons, issues, evidence)
    playbook = build_playbook(profile, metrics, allocation, benchmark_result, claims, comparisons, evidence)
    workflow = [
        {"id": "ingest", "name": "材料解析", "detail": f"现期 {len(current_chunks)} 段、前期 {len(prior_chunks)} 段文本", "status": "complete"},
        {"id": "validate", "name": "数据质检", "detail": f"{len(clean_nav)} 个净值点、{len(issues)} 条口径提示", "status": "complete"},
        {"id": "calculate", "name": "独立计算", "detail": f"{len([e for e in evidence if e['kind'] == 'calculation'])} 项可追溯计算", "status": "complete"},
        {"id": "audit", "name": "陈述审计", "detail": f"{len(claims)} 项陈述、{status_counts['contradicted']} 项矛盾", "status": "complete"},
        {"id": "compare", "name": "跨期对照", "detail": f"{len(comparisons)} 项同主题比较", "status": "complete" if prior_chunks else "skipped"},
        {"id": "brief", "name": "研究简报", "detail": f"{len(questions)} 条追问、{len(evidence)} 条证据", "status": "complete"},
    ]
    return {
        "execution_mode": "deterministic_offline", "fund": profile,
        "input_sources": input_sources,
        "data_quality": {"issues": issues, "nav_observations": len(clean_nav),
                         "benchmark_observations": len(clean_benchmark),
                         "holdings_rows": sum(len(ids) for ids in allocation["evidence_ids"].values()),
                         "frequency": metrics["frequency"],
                         "sufficient_for_basic_metrics": len(clean_nav) >= 2},
        "metrics": metrics, "benchmark_comparison": benchmark_result,
        "factor_attribution": factor_attribution, "return_calendar": return_calendar,
        "allocation": allocation, "evidence": evidence, "claims": claims,
        "period_comparison": comparisons, "follow_up_questions": questions,
        "manager_summary": summary, "insights": insights, "workflow": workflow, "playbook": playbook,
    }


def augment_with_ai(result: Mapping[str, Any], *, include_red_team: bool = True) -> dict[str, Any]:
    """Attach qualitative AI reasoning to an existing deterministic audit.

    ``run_diligence`` stays a pure, offline, testable function. This separate
    step reads its *fact sheet* and asks the model only to interpret, challenge
    and draft — never to compute. It returns ``None``-valued AI fields when no
    backend is configured, so the deterministic report remains self-sufficient.
    """
    from . import llm as _llm
    from . import reasoner

    augmented = dict(result)
    ai: dict[str, Any] = {"status": _llm.status()}
    if _llm.is_available():
        ai["deep_analysis"] = reasoner.deep_analysis(augmented)
        if include_red_team:
            ai["red_team"] = reasoner.red_team(augmented)
    augmented["ai"] = ai
    if ai.get("deep_analysis") or ai.get("red_team"):
        augmented["execution_mode"] = "ai_augmented"
        workflow = list(augmented.get("workflow", []))
        workflow.append({
            "id": "ai_reasoning", "name": "AI 推理",
            "detail": f"深度尽调分析{' + 红队质疑' if ai.get('red_team') else ''}",
            "status": "complete",
        })
        augmented["workflow"] = workflow
    return augmented


def render_markdown(result: Mapping[str, Any]) -> str:
    """Export a readable research brief with claim and calculation source IDs."""
    fund = result["fund"]
    metrics = result["metrics"]
    evidence_by_id = {item["id"]: item for item in result["evidence"]}

    def pct(value: float | None) -> str:
        return "无法计算" if value is None else f"{value:.2%}"

    ai = result.get("ai") or {}
    ai_analysis = ai.get("deep_analysis") or {}
    ai_red_team = ai.get("red_team") or {}
    ai_used = bool(ai_analysis or ai_red_team)
    run_mode = "AI 增强：确定性计算 + 模型推理（模型不生成数字）。" if ai_used else "确定性离线检查；未调用语言模型或外部金融数据。"
    lines = [
        f"# FOF 基金经理证据审计简报：{fund['name']}", "",
        f"基金编号：{fund['fund_id']} · 管理人：{fund['manager']} · 策略：{fund['strategy']}", "",
        f"**运行方式：** {run_mode}", "",
        "## 管理人摘要", "", result["manager_summary"], "",
        "- 研究复核优先级：" + result.get("insights", {}).get("review_priority", "未评估"),
        "- 可连接独立证据的陈述占比：" + f"{result.get('insights', {}).get('claim_coverage_pct', 0):.1f}%", "",
    ]
    if ai_analysis:
        lines += ["## AI 深度研判", "", f"**结论：** {ai_analysis.get('verdict', '')}", "",
                  f"**策略与行为一致性：** {ai_analysis.get('thesis', '')}", ""]
        if ai_analysis.get("strengths"):
            lines.append("**可信优势：**")
            lines += [f"- {item}" for item in ai_analysis["strengths"]]
            lines.append("")
        if ai_analysis.get("red_flags"):
            lines.append("**风险信号：**")
            lines += [f"- {item}" for item in ai_analysis["red_flags"]]
            lines.append("")
        if ai_analysis.get("critical_questions"):
            lines.append("**下一轮尽调最该追问：**")
            lines += [f"{i}. {item}" for i, item in enumerate(ai_analysis["critical_questions"], 1)]
            lines.append("")
        if ai_analysis.get("hypotheses"):
            lines.append("**可证伪的研究假设：**")
            lines += [f"- {item}" for item in ai_analysis["hypotheses"]]
            lines.append("")
        if ai_analysis.get("evidence_boundary"):
            lines += [f"**证据边界：** {ai_analysis['evidence_boundary']}", ""]
    if ai_red_team:
        lines += ["## 红队质疑", ""]
        if ai_red_team.get("attacks"):
            lines += [f"- {item}" for item in ai_red_team["attacks"]]
            lines.append("")
        if ai_red_team.get("falsifiable_checks"):
            lines.append("**可落地检验动作：**")
            lines += [f"{i}. {item}" for i, item in enumerate(ai_red_team["falsifiable_checks"], 1)]
            lines.append("")
        if ai_red_team.get("worst_case_reading"):
            lines += [f"**最不利但仍在事实范围内的解读：** {ai_red_team['worst_case_reading']}", ""]
        if ai_red_team.get("missing_evidence_that_matters"):
            lines.append("**最影响判断却仍缺失的证据（按重要性）：**")
            lines += [f"- {item}" for item in ai_red_team["missing_evidence_that_matters"]]
            lines.append("")
    lines += ["## 数据与计算", "",
        f"- 净值区间：{metrics['start'] or '未知'} 至 {metrics['end'] or '未知'}；{metrics['observations']} 个有效点；{metrics['frequency']}。",
        f"- 区间收益：{pct(metrics['total_return'])}；年化收益：{pct(metrics['annual_return'])}。",
        f"- 年化波动：{pct(metrics['volatility'])}；最大回撤：{pct(metrics['max_drawdown'])}。",
    ]
    source_names = {"nav": "基金净值", "holdings": "持仓快照", "benchmark": "业绩基准"}
    for role, title in source_names.items():
        filenames = result.get("input_sources", {}).get(role, [])
        if filenames:
            lines.append(f"- {title}输入文件：{'、'.join(filenames)}。")
    comp = result["benchmark_comparison"]
    if comp["relative_return_pp"] is not None:
        lines.append(f"- 同日基准比较：基金 {pct(comp['fund_return'])}，基准 {pct(comp['benchmark_return'])}，差值 {comp['relative_return_pp']:.2f} 个百分点（{comp['start']} 至 {comp['end']}）。")
    else:
        lines.append("- 同日基准比较：资料不足，未计算。")
    attribution = comp.get("attribution")
    if attribution:
        def ratio(value: float | None) -> str:
            return "无法计算" if value is None else f"{value:.2f}"
        def pctv(value: float | None) -> str:
            return "无法计算" if value is None else f"{value:.2%}"
        def pval(value: float | None) -> str:
            return "无法计算" if value is None else f"{value:.3g}"
        attribution_rows = [
            ("Beta（相对基准）", ratio(attribution.get("beta"))),
            ("Jensen Alpha（年化，无风险利率=0）", pctv(attribution.get("alpha_annualized"))),
            ("与基准相关性", ratio(attribution.get("correlation"))),
            ("R²（基准解释比例）", ratio(attribution.get("r_squared"))),
            ("Beta 显著性 p 值", pval(attribution.get("beta_pvalue"))),
            ("Beta 标准误", ratio(attribution.get("beta_stderr"))),
            ("跟踪误差（年化）", pctv(attribution.get("tracking_error"))),
            ("信息比率", ratio(attribution.get("information_ratio"))),
            ("主动收益（年化）", pctv(attribution.get("active_return_annualized"))),
            ("上行捕获率", ratio(attribution.get("up_capture_ratio"))),
            ("下行捕获率", ratio(attribution.get("down_capture_ratio"))),
        ]
        lines += ["", "## 风险调整归因（相对基准）", "",
                  f"以下指标由 {comp.get('attribution_observations')} 个同日收益期按确定性公式计算，仅描述历史样本与所选基准的关系。",
                  "", "| 指标 | 值 |", "|---|---:|"]
        lines += [f"| {label} | {value} |" for label, value in attribution_rows]
        for assumption in comp.get("attribution_assumptions", []):
            lines.append(f"- {assumption}")
    calendar = result.get("return_calendar") or {}
    if calendar.get("yearly"):
        lines += ["", "## 年度与月度收益（%）", "",
                  "年度收益由月度收益连乘得到；月度收益为相邻月末净值的简单百分比，未扣费、未验证分红复权口径。",
                  "", "| 年度 | 区间收益 | 有效月数 |", "|---|---:|---:|"]
        for row in calendar["yearly"]:
            lines.append(f"| {row['year']} | {row['return']:.2%} | {row['months']} |")
    if calendar.get("monthly"):
        month_headers = " | ".join(f"{month}月" for month in range(1, 13))
        lines += ["", f"| 年度 | {month_headers} | 全年 |",
                  "|---:" + "|---:" * 13 + "|"]
        for row in calendar["monthly"]:
            cells = [str(row["year"])]
            cells += ["—" if row.get(f"{month}月") is None else f"{row[f'{month}月']:.2%}" for month in range(1, 13)]
            cells.append(f"{row['全年']:.2%}")
            lines.append("| " + " | ".join(cells) + " |")
    factor_result = result.get("factor_attribution") or {}
    if factor_result.get("available"):
        fm = factor_result.get("metrics", {})
        def fv(value: float | None) -> str:
            return "无法计算" if value is None else f"{value:.2%}"
        def fr(value: float | None) -> str:
            return "无法计算" if value is None else f"{value:.2f}"
        lines += ["", "## 多因子归因（Fama-French 5 因子，月频）", "",
                  f"对基金月末收益与 Kenneth R. French 因子做 OLS 回归（{factor_result.get('observations')} 个对齐月度观测）。因子为美股学术因子，对中国资产仅作方法演示，不代表本土风险溢价。",
                  "", "| 指标 | 值 |", "|---|---:|",
                  f"| 年化 Alpha（截距） | {fv(fm.get('alpha_annualized'))} |",
                  f"| R² | {fr(fm.get('r_squared'))} |",
                  f"| 调整 R² | {fr(fm.get('adj_r_squared'))} |",
                  f"| F 统计量 | {fr(fm.get('f_statistic'))} |",
                  f"| 残差波动（年化） | {fv(fm.get('residual_volatility_annualized'))} |",
                  "", "| 因子 | 系数 | t 值 | p 值 | 显著(5%) |", "|---|---:|---:|---:|---:|"]
        for exposure in factor_result.get("exposures", []):
            label = exposure.get("label") or exposure.get("factor")
            lines.append(f"| {label} | {exposure['coefficient']:.4f} | {exposure['t_statistic']:.2f} | "
                         f"{exposure['p_value']:.4f} | {'是' if exposure.get('significant') else '否'} |")
        for assumption in factor_result.get("assumptions", []):
            lines.append(f"- {assumption}")
    if result.get("playbook"):
        lines += ["", "## 机构尽调覆盖图", "", "覆盖状态描述本次输入材料，不是基金或经理评分。", "", "| 维度 | 覆盖 | 下一步资料请求 |", "|---|---|---|"]
        for item in result["playbook"]:
            lines.append(f"| {item['title']} | {item['coverage']} | {item['next_request']} |")
    lines += ["", "## 关键陈述与证据", ""]
    if not result["claims"]:
        lines += ["当前没有从现期报告中识别出可审计的管理人陈述。", ""]
    for number, claim in enumerate(result["claims"], 1):
        checks = "、".join(claim["check_evidence_ids"]) or "无独立计算或观察证据"
        lines += [
            f"### {number}. {claim['status_label']} · {claim['id']}", "",
            f"> {claim['text']}", "",
            f"- 原文：{claim['source']}，{claim['location']}（{claim['source_evidence_id']}）。",
            f"- 检查：{claim['explanation']}",
            f"- 对照证据：{checks}。",
            f"- 边界：{claim['limitation']}", "",
        ]
    if result["period_comparison"]:
        lines += ["## 跨期表述", ""]
        for item in result["period_comparison"]:
            lines.append(f"- {item['topic']}：现期 {item['current_claim_id']}，前期 {item['prior_claim_id']}；{item['assessment']}")
        lines.append("")
    lines += ["## 需向管理人追问", ""]
    if result["follow_up_questions"]:
        lines += [f"{number}. [{item['priority']}] {item['question']}" for number, item in enumerate(result["follow_up_questions"], 1)]
    else:
        lines.append("当前没有自动生成的追问；研究员仍应审查数据口径与原始材料。")
    lines += ["", "## 数据质量与方法边界", ""]
    for item in result["data_quality"]["issues"]:
        lines.append(f"- {item['severity']} · {item['code']}：{item['message']}")
    for assumption in metrics["assumptions"]:
        lines.append(f"- {assumption}")
    lines += ["", "## 引用证据索引", ""]
    referenced = {item["source_evidence_id"] for item in result["claims"]}
    referenced.update(id_ for item in result["claims"] for id_ in item["check_evidence_ids"])
    referenced.update(item["prior_source_evidence_id"] for item in result["period_comparison"])
    if comp["evidence_id"]:
        referenced.add(comp["evidence_id"])
    for item_id in sorted(referenced):
        item = evidence_by_id[item_id]
        excerpt = item["text"].replace("\n", " ")
        if len(excerpt) > 240:
            excerpt = excerpt[:237] + "…"
        input_files = sorted({evidence_by_id[source_id]["source"] for source_id in item.get("input_evidence_ids", [])
                              if source_id in evidence_by_id})
        if input_files:
            excerpt += f"；输入文件：{'、'.join(input_files)}"
        lines.append(f"- **{item_id}** · {item['source']}，{item['location']}：{excerpt}")
    lines += ["", "本简报仅供研究，不构成投资建议；未验证的叙事和历史业绩不能作为未来表现预测。"]
    return "\n".join(lines) + "\n"
