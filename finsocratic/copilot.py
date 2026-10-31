"""Evidence-grounded research assistant powered by explicit finance tools.

No external model or network is called. Intent routing selects bounded tools;
every numerical response is computed from the selected workspace and cited.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .agent import run_diligence
from .library import retrieve


def _pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2%}"


def _frame(fund: dict[str, Any], kind: str) -> pd.DataFrame:
    rows = fund.get("nav" if kind == "nav" else "holdings_history", [])
    if not rows and kind != "nav":
        rows = fund.get("holdings", [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        columns = ["fund_id", "date", "nav"] if kind == "nav" else ["fund_id", "asset", "weight_pct", "as_of"]
        return pd.DataFrame(columns=columns)
    frame["fund_id"] = fund["fund_id"]
    date_col = "date" if kind == "nav" else "as_of"
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    return frame


def answer_research(
    question: str, fund_id: str | None, workspace: dict[str, Any],
    documents: list[dict[str, Any]], runs: list[dict[str, Any]],
) -> dict[str, Any]:
    question = question.strip()
    if not question:
        raise ValueError("请输入研究问题。")
    if len(question) > 8000:
        raise ValueError("单次问题请控制在 8000 字以内。")
    funds = workspace.get("funds", [])
    named = [f for f in funds if any(str(f.get(key, "")) in question for key in ("fund_id", "name", "manager") if f.get(key))]
    compare = any(word in question for word in ("比较", "对比", "筛选", "横向", "哪只", "哪个经理", "候选", "排名"))
    chosen = named or ([f for f in funds if f["fund_id"] == fund_id] if fund_id else [])
    if compare and len(chosen) < 2:
        sample_scope = chosen[0].get("is_sample", False) if chosen else all(f.get("is_sample", False) for f in funds)
        chosen = [f for f in funds if bool(f.get("is_sample", False)) == bool(sample_scope)]
    if not chosen:
        chosen = funds[:1]
    if not chosen:
        return {"answer": "工作区还没有基金。请先导入基金档案和净值，再运行研究。", "citations": [], "steps": [], "suggestions": ["导入基金档案"]}
    selected_ids = {f["fund_id"] for f in chosen}
    selected_docs = [d for d in documents if d.get("fund_id") in selected_ids]
    selected_runs = [r for r in runs if r.get("fund", {}).get("fund_id") in selected_ids]
    citations: list[dict[str, Any]] = []
    steps: list[dict[str, str]] = []
    sections: list[str] = []

    def cite(source: str, location: str, text: str, ref_id: str | None = None) -> str:
        existing = next((c for c in citations if c["source"] == source and c["location"] == location and c["text"] == text), None)
        if existing:
            return f"[{existing['id']}]"
        identifier = f"R{len(citations) + 1}"
        citations.append({"id": identifier, "source": source, "location": location, "text": text, "ref_id": ref_id})
        return f"[{identifier}]"

    def metric_citation(fund: dict[str, Any]) -> str:
        m = fund.get("metrics", {})
        sources = sorted({str(row.get("source_file") or "工作区净值") for row in fund.get("nav", [])})
        return cite("、".join(sources) or "工作区净值", f"{fund['name']} · {m.get('start', '未知')} 至 {m.get('end', '未知')}",
                    f"区间收益 {_pct(m.get('total_return'))}；年化收益 {_pct(m.get('annual_return'))}；年化波动 {_pct(m.get('volatility'))}；最大回撤 {_pct(m.get('max_drawdown'))}。由导入净值按确定公式计算。")

    steps.append({"tool": "resolve_research_scope", "label": "确定研究范围", "detail": "、".join(f["name"] for f in chosen)})
    if compare:
        from .comparison import compare_funds
        try:
            aligned = compare_funds(chosen)
            table = ["### 同区间候选基金对照", "", f"共同区间：{aligned['start']} 至 {aligned['end']}，{aligned['observations']} 个共同观测。", "", "| 基金 | 年化收益 | 年化波动 | 最大回撤 | 来源 |", "|---|---:|---:|---:|---|"]
            for row in aligned['funds']:
                m = row['metrics']
                ref = cite('、'.join(row['sources']), f"{aligned['start']} 至 {aligned['end']}", f"共同观测重算；{aligned['observations']} 个点；最大回撤 {_pct(m.get('max_drawdown'))}")
                table.append(f"| {row['name']} | {_pct(m.get('annual_return'))} | {_pct(m.get('volatility'))} | {_pct(m.get('max_drawdown'))} | {ref} |")
            table += ["", aligned['method'], *aligned['limits']]
            sections.append("\n".join(table))
            steps.append({'tool':'compare_common_observations','label':'统一区间复算','detail':f"{len(chosen)} 只基金，{aligned['observations']} 个共同观测，不插值"})
        except ValueError as error:
            sections.append(f"### 比较范围需要调整\n\n{error}")
            steps.append({'tool':'compare_common_observations','label':'检查可比性','detail':str(error)})

    audit_intent = bool(re.search(r"[-+]?\d+(?:\.\d+)?\s*[%％]", question)) and any(word in question for word in ("核验", "核对", "是否", "回撤", "收益", "仓位", "权益", "债券", "CTA"))
    if audit_intent:
        fund = chosen[0]
        result = run_diligence(fund, _frame(fund, "nav"), _frame(fund, "holdings"),
                               [{"name": "本次研究问题", "chunks": [{"location": "问题原文", "text": question}]}])
        evidence = {e["id"]: e for e in result["evidence"]}
        lines = ["### 量化陈述核验", ""]
        for claim in result["claims"]:
            refs = []
            for identifier in claim["check_evidence_ids"]:
                e = evidence[identifier]
                refs.append(cite(e["source"], e["location"], e["text"], identifier))
            lines += [f"**{claim['status_label']}**：{claim['text']}", f"{claim['explanation']} {' '.join(refs)}", f"核验边界：{claim['limitation']}", ""]
        sections.append("\n".join(lines))
        steps.append({"tool": "audit_quantified_claim", "label": "独立复算陈述", "detail": f"使用当前净值和持仓核对 {len(result['claims'])} 项陈述"})

    drift_intent = any(word in question for word in ("配置", "仓位", "持仓", "漂移", "变化", "调仓", "风格")) and not audit_intent
    if drift_intent:
        lines = ["### 配置变化", ""]
        for fund in chosen:
            holdings = _frame(fund, "holdings")
            dates = sorted(holdings["as_of"].dropna().unique()) if not holdings.empty else []
            if len(dates) < 2:
                lines.append(f"{fund['name']}只有 {len(dates)} 期有效快照，尚不能计算跨期配置变化。")
                continue
            old = holdings.loc[holdings.as_of == dates[-2]].groupby("asset")["weight_pct"].sum()
            new = holdings.loc[holdings.as_of == dates[-1]].groupby("asset")["weight_pct"].sum()
            delta = new.subtract(old, fill_value=0)
            ordered = sorted(delta.items(), key=lambda item: abs(item[1]), reverse=True)
            start, end = pd.Timestamp(dates[-2]).date(), pd.Timestamp(dates[-1]).date()
            change = "；".join(f"{asset} {float(old.get(asset, 0)):.1f}% → {float(new.get(asset, 0)):.1f}%（{value:+.1f} 个百分点）" for asset, value in ordered[:4])
            source = "、".join(sorted(set(holdings.source_file.dropna().astype(str)))) if "source_file" in holdings else "持仓快照"
            ref = cite(source, f"{fund['name']} · {start} → {end}", change)
            lines.append(f"**{fund['name']}**：{change}。{ref}")
            if abs(float(old.sum()) - 100) <= 1 and abs(float(new.sum()) - 100) <= 1:
                lines.append(f"两期配置差异度为 **{float(delta.abs().sum()) / 2:.1f} 个百分点**（权重差绝对值之和的一半）。这是快照变化代理，未剔除市场涨跌，也不等于实际交易换手率。")
        sections.append("\n\n".join(lines))
        steps.append({"tool": "calculate_allocation_drift", "label": "比较跨期配置", "detail": "对齐最近两期资产分类，计算权重差与快照配置差异度"})

    risk_intent = any(word in question for word in ("风险", "回撤", "波动", "亏损", "收益", "业绩")) and not audit_intent and not compare
    if risk_intent:
        lines = ["### 收益与风险诊断", ""]
        for fund in chosen:
            m = fund.get("metrics", {})
            lines.append(f"**{fund['name']}**：区间收益 {_pct(m.get('total_return'))}，年化收益 {_pct(m.get('annual_return'))}，年化波动 {_pct(m.get('volatility'))}，最大回撤 {_pct(m.get('max_drawdown'))}。{metric_citation(fund)}")
            nav = _frame(fund, "nav").sort_values("date")
            if len(nav) > 1:
                returns = nav.nav.pct_change().dropna()
                worst_index = returns.idxmin()
                lines.append(f"最弱相邻观测期截至 {nav.loc[worst_index, 'date']:%Y-%m-%d}，单期收益 {float(returns.min()):.2%}；净值频率为 {m.get('frequency', '未识别')}。")
        lines.append("回撤仅来自可见净值点，不能排除两次观测之间的更深跌幅。策略收益归因还需要逐期权重、策略级净值及费用记录。")
        sections.append("\n\n".join(lines))
        steps.append({"tool": "diagnose_nav_path", "label": "诊断净值路径", "detail": "复核收益、频率、最大回撤和最弱相邻观测期"})

    diligence_intent = any(word in question for word in ("尽调", "追问", "缺口", "证据不足", "还缺", "下一步", "问题", "材料", "归因", "流动性", "赎回", "费用", "合规"))
    if diligence_intent or not sections:
        if selected_runs:
            latest = selected_runs[0]
            related = [p for p in latest.get("playbook", []) if p["coverage"] != "complete"]
            topic_keys = {"liquidity": ("流动性", "赎回", "费用"), "risk": ("回撤", "风险"), "operations": ("合规", "审计", "估值"), "portfolio": ("穿透", "集中", "底层"), "narrative": ("叙事", "归因", "变化")}
            explicit = [p for p in related if any(k in question for k in topic_keys.get(p["id"], ()))]
            focus = explicit or related[:5]
            lines = ["### 下一轮尽调重点", ""]
            for p in focus:
                ref = cite("尽调覆盖图", f"{latest.get('fund', {}).get('name', '')} · {p['title']}", p["detail"])
                lines += [f"**{p['title']}**：{p['detail']} {ref}", f"资料请求：{p['next_request']}", ""]
            for c in [c for c in latest.get("claims", []) if c.get("status") == "contradicted"][:3]:
                lines.append(f"优先复核矛盾：{c['text']}。{c['explanation']}")
            sections.append("\n".join(lines))
            steps.append({"tool": "review_diligence_gaps", "label": "梳理证据缺口", "detail": f"读取最近尽调的 {len(focus)} 个重点维度及矛盾陈述"})

    hits = retrieve(question, selected_docs, limit=4) if selected_docs else []
    if hits:
        lines = ["### 相关原文", ""]
        for hit in hits:
            excerpt = hit["text"][:600]
            ref = cite(hit["file"], hit["location"], excerpt)
            lines.append(f"{ref} {excerpt}")
        lines.append("上述内容是材料中的陈述；是否被独立数据支持，以陈述核验结果为准。")
        sections.append("\n\n".join(lines))
        steps.append({"tool": "retrieve_source_passages", "label": "定位原文", "detail": f"在选定经理的材料中找到 {len(hits)} 个相关片段"})

    if not sections:
        sections.append("当前资料没有足够证据回答这个问题。可先上传相关报告，或明确要比较的基金、日期和指标。")
    return {
        "answer": "\n\n".join(sections), "citations": citations, "steps": steps,
        "suggestions": ["比较三只基金的收益、回撤和样本长度", "这位经理最近两期配置发生了什么变化？", "下一轮尽调最应该追问哪些证据？", "核验：权益策略占35%，最大回撤在1%以内"],
        "scope": {"fund_ids": sorted(selected_ids), "execution_mode": "local_research_tools", "external_model_used": False},
    }
