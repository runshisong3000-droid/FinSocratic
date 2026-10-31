"""FOF manager diligence coverage map.

Categories adapt public CFA Institute manager-selection guidance and AIMA's
public due-diligence overview; questions below are written for FinSocratic.
Coverage measures supplied evidence, never investment quality.
"""
from __future__ import annotations

from typing import Any, Mapping


def build_playbook(
    profile: Mapping[str, Any], metrics: Mapping[str, Any], allocation: Mapping[str, Any],
    benchmark: Mapping[str, Any], claims: list[dict[str, Any]], comparisons: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    doc_ids = [item["id"] for item in evidence if item["kind"] == "source_text" and not item["id"].startswith("PRIOR-")]
    nav_ids = list(metrics["calculation_evidence_ids"].values())
    holding_ids = [item_id for ids in allocation["evidence_ids"].values() for item_id in ids]
    rows = [
        ("strategy", "策略与经理团队", "partial" if profile.get("manager") and doc_ids else "missing",
         "已有经理名称和报告文字；决策权限、关键人履历及团队稳定性仍需原始材料。",
         doc_ids[:2], "索取团队组织图、关键人履历、决策权限与人员变动记录。"),
        ("performance", "业绩与可比基准", "complete" if metrics["observations"] >= 12 and benchmark["matched_observations"] >= 12 else "partial" if metrics["observations"] >= 2 else "missing",
         f"有效净值 {metrics['observations']} 点，同日基准 {benchmark['matched_observations']} 点；基准适配性仍需人工判断。",
         nav_ids + ([benchmark["evidence_id"]] if benchmark["evidence_id"] else []),
         "确认净值的分红、费用和现金流处理，以及基准选择依据。"),
        ("portfolio", "组合结构与底层穿透", "partial" if allocation["available"] else "missing",
         f"最新快照 {allocation['as_of'] or '日期未知'}，已报权重 {allocation['weight_sum']:.1f}%；尚未自动穿透底层基金。" if allocation["available"] else "缺少可核验的最新持仓快照。",
         holding_ids, "索取底层基金明细、重叠持仓、实际敞口和集中度口径。"),
        ("risk", "风险控制与回撤路径", "partial" if metrics["max_drawdown"] is not None else "missing",
         f"基于{metrics['frequency']}净值可计算观测点回撤；止损执行、压力测试与尾部暴露未获独立验证。",
         [metrics["calculation_evidence_ids"]["max_drawdown"]] if "max_drawdown" in metrics["calculation_evidence_ids"] else [],
         "索取日频净值、压力测试、风险限额与超限处置记录。"),
        ("liquidity", "流动性、条款与费用", "partial" if profile.get("liquidity") or profile.get("fee_pct") is not None else "missing",
         f"档案记载开放安排 {profile.get('liquidity') or '未知'}、费率 {profile.get('fee_pct') if profile.get('fee_pct') is not None else '未知'}%；尚未核对合同条款。",
         [], "核对基金合同、赎回通知期、底层流动性、估值规则与完整费用。"),
        ("operations", "运营、估值与合规", "missing",
         "当前资料没有独立的托管、估值、审计与合规控制证据。", [],
         "索取托管与估值制度、外部审计意见、重大事件和合规记录。"),
        ("narrative", "叙事一致性与可证伪性", "partial" if claims else "missing",
         f"现期拆解 {len(claims)} 项陈述，跨期同主题对照 {len(comparisons)} 项；差异需结合真实报告期间解释。",
         [item["source_evidence_id"] for item in claims[:5]],
         "请经理逐项解释跨期表述变化，并提供能独立复核的原始记录。"),
    ]
    return [
        {"id": key, "title": title, "coverage": coverage, "detail": detail,
         "evidence_ids": ids, "next_request": request}
        for key, title, coverage, detail, ids, request in rows
    ]
