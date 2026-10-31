"""Transparent, deterministic checks for portfolio claims and fund data."""
from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from .data import all_metrics, fund_metrics


def portfolio_metrics(holdings: pd.DataFrame, fund_id: str) -> dict[str, Any]:
    required = {"fund_id", "asset", "weight_pct", "as_of"}
    if holdings.empty or not required.issubset(holdings.columns):
        return {"available": False, "reason": "没有可用的持仓快照。"}
    rows = holdings.loc[holdings["fund_id"].astype(str) == str(fund_id)].copy()
    if rows.empty:
        return {"available": False, "reason": "没有该基金的持仓快照。"}
    dates = pd.to_datetime(rows["as_of"], errors="coerce")
    as_of = dates.max()
    if pd.notna(as_of):
        rows = rows.loc[dates == as_of].copy()
    weights = pd.to_numeric(rows["weight_pct"], errors="coerce")
    invalid = weights.isna() | ~np.isfinite(weights) | (weights < 0) | (weights > 100)
    if invalid.any():
        return {"available": False, "reason": f"最新持仓快照有 {int(invalid.sum())} 条无效权重；权重须为0%至100%的数字。"}
    total = float(weights.sum())
    if total <= 0:
        return {"available": False, "reason": "最新持仓快照的有效权重合计为0%。"}
    rows["weight_pct"] = weights
    shares = weights / total
    return {
        "available": True,
        "as_of": as_of.strftime("%Y-%m-%d") if pd.notna(as_of) else "未知",
        "reported_weight_sum": total,
        "hhi": float((shares**2).sum()),
        "top_weight": float(weights.max()),
        "asset_count": int(len(weights)),
        "rows": rows,
    }


def _as_percent(value: float) -> str:
    return f"{value:.2f}%"


def assess_claims(text: str, fund: pd.Series, nav: pd.DataFrame, holdings: pd.DataFrame) -> list[dict[str, str]]:
    """Check only claims that map to available fields; otherwise say what is missing."""
    fund_id = str(fund["fund_id"])
    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;])\s*|\n+", text) if s.strip()]
    results: list[dict[str, str]] = []
    metrics = fund_metrics(nav, fund_id)
    alloc = portfolio_metrics(holdings, fund_id)
    frequency = str(metrics.get("frequency", "观测不足"))
    for sentence in sentences:
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", sentence)
        expected = float(percent_match.group(1)) if percent_match else None
        if any(k in sentence for k in ("最大回撤", "回撤控制", "drawdown")):
            if np.isfinite(metrics.get("max_drawdown", np.nan)):
                observed = abs(float(metrics["max_drawdown"])) * 100
                stated = f"不超过{expected:g}%" if expected is not None else "未给出量化阈值"
                status = "与样本相符" if expected is not None and observed <= expected else "样本不支持" if expected is not None else "部分可核验"
                explanation = (f"陈述为最大回撤{stated}；由当前净值序列估算的最大回撤为{_as_percent(observed)}。"
                               f"数据为{frequency}，观测间的回撤无法还原；这里只能做频率受限的交叉检查。")
                evidence = f"{frequency}净值序列：{metrics.get('start', '—')} 至 {metrics.get('end', '—')}，{metrics['months']} 个净值点"
            else:
                status, explanation, evidence = "无法核验", "缺少足够的净值观测。", "请导入该基金的日期和净值列"
        elif any(k in sentence for k in ("权益", "股票", "债券", "CTA", "市场中性", "仓位", "配置")) and percent_match:
            target_asset = next((a for a in alloc.get("rows", pd.DataFrame()).get("asset", pd.Series(dtype=str)).dropna().astype(str).unique() if a in sentence), None)
            if alloc["available"] and target_asset:
                found = alloc["rows"].loc[alloc["rows"]["asset"].astype(str) == target_asset, "weight_pct"]
                observed = float(pd.to_numeric(found, errors="coerce").sum()) if not found.empty else np.nan
                if np.isfinite(observed):
                    status = "与快照相符" if abs(observed - expected) <= 0.5 else "与快照不符"
                    explanation = f"陈述约为{expected:g}%；持仓快照记录为{_as_percent(observed)}。"
                    evidence = f"持仓快照日期：{alloc['as_of']}；该结论只比较已导入快照"
                else:
                    status, explanation, evidence = "无法核验", "持仓表中没有找到对应资产类别。", "请核对资产名称映射"
            else:
                status, explanation, evidence = "部分可核验", "识别到配置比例陈述，但无法可靠映射到持仓资产字段。", "需要规范化的资产类别与持仓快照"
        elif any(k in sentence for k in ("年化收益", "年化回报", "annual return")):
            observed = metrics.get("annual_return", np.nan)
            if np.isfinite(observed) and expected is not None:
                status = "与样本相符" if abs(observed * 100 - expected) <= 1 else "与样本不符"
                explanation = f"净值序列估算年化收益{_as_percent(observed * 100)}，陈述约为{expected:g}%。"
                evidence = f"区间：{metrics.get('start', '—')} 至 {metrics.get('end', '—')}；按净值端点复合年化"
            else:
                status, explanation, evidence = "无法核验", "缺少完整净值序列或可比较的百分比。", "请导入日期和净值"
        else:
            status = "当前数据无法检验"
            explanation = "这项陈述没有映射到当前结构化数据字段；系统不会仅凭文本判断其真假。"
            evidence = "可补充对应期间的持仓、净值、基准或第三方原始来源"
        results.append({"陈述": sentence, "判断": status, "对照说明": explanation, "证据与限制": evidence})
    return results


def markdown_report(fund_name: str, results: list[dict[str, str]]) -> str:
    lines = [f"# 管理人陈述核对记录：{fund_name}", "", "本报告是对已导入资料的有限交叉检查，不构成投资建议或对管理人诚信的判断。", ""]
    for i, item in enumerate(results, 1):
        lines += [f"## {i}. {item['判断']}", "", f"**陈述：** {item['陈述']}", "", f"**对照：** {item['对照说明']}", "", f"**证据与限制：** {item['证据与限制']}", ""]
    return "\n".join(lines)


def fund_research_report(fund: pd.Series, nav: pd.DataFrame, holdings: pd.DataFrame) -> str:
    """Create a deterministic, source-labeled teaching report for one fund."""
    fund_id = str(fund["fund_id"])
    metrics = fund_metrics(nav, fund_id)
    allocation = portfolio_metrics(holdings, fund_id)
    def pct(v: object) -> str:
        return "—" if not np.isfinite(v) else f"{float(v):.2%}"
    lines = [f"# 基金研究速报：{fund.get('name', fund_id)}", "", "## 研究对象", "", f"- 基金编号：{fund_id}", f"- 管理人：{fund.get('manager', '—')}", f"- 策略：{fund.get('strategy', '—')}", f"- 数据标记：当前工作区导入数据", "", "## 业绩与风险", "", f"- 区间收益：{pct(metrics.get('total_return'))}", f"- 年化收益：{pct(metrics.get('annual_return'))}", f"- 年化波动：{pct(metrics.get('volatility'))}", f"- 最大回撤：{pct(metrics.get('max_drawdown'))}", f"- 夏普比率：{metrics.get('sharpe', float('nan')):.2f}" if np.isfinite(metrics.get('sharpe', np.nan)) else "- 夏普比率：—", f"- 净值观测：{metrics.get('months', 0)} 个点（{metrics.get('start', '—')} 至 {metrics.get('end', '—')}）", f"- 数据频率：{metrics.get('frequency', '观测不足')}", "", "## 组合快照", ""]
    if allocation.get("available"):
        lines += [f"- 快照日期：{allocation['as_of']}", f"- 权重合计：{allocation['reported_weight_sum']:.2f}%", f"- 最大单项权重：{allocation['top_weight']:.2f}%", f"- HHI：{allocation['hhi']:.3f}", "", "| 资产类别 | 权重 |"]
        lines += ["|---|---:|"] + [f"| {r.asset} | {float(r.weight_pct):.2f}% |" for r in allocation["rows"].itertuples()]
    else:
        lines.append("- 当前没有可用持仓快照。")
    lines += ["", "## 研究边界", "", "本报告由当前工作区的结构化数据按固定公式生成，不构成投资建议。净值观测间的回撤无法还原；不规则频率时不报告年化波动和夏普比率；持仓快照不自动穿透底层资产；资料和数据口径应由研究人员继续复核。"]
    return "\n".join(lines)


def screen_funds(
    funds: pd.DataFrame,
    nav: pd.DataFrame,
    holdings: pd.DataFrame,
    *,
    min_observations: int = 24,
    max_drawdown_limit: float = 0.35,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Rank eligible funds using transparent historical metrics, not forecasts.

    The score is a weighted average of cross-sectional percentile ranks for
    annual return, Sharpe, and drawdown (smaller absolute loss is better).
    Funds missing adequate return history or violating the drawdown limit are
    excluded. A sample with no excess of observations cannot support a Sharpe.
    """
    if min_observations < 3:
        raise ValueError("最少净值观测数必须不少于3。")
    if not 0 < max_drawdown_limit <= 1:
        raise ValueError("最大回撤门槛应在0到100%之间。")
    if weights is None:
        weights = {"annual_return": 0.50, "sharpe": 0.30, "max_drawdown": 0.20}
    allowed = {"annual_return", "sharpe", "max_drawdown"}
    if not weights or set(weights) - allowed or any(not np.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("评分权重只能包含年化收益、夏普比率、最大回撤，且必须为非负数并有正总和。")
    normalized_weights = {k: v / sum(weights.values()) for k, v in weights.items() if v > 0}
    result = all_metrics(funds, nav)
    portfolio_rows = []
    for fid in funds["fund_id"].astype(str) if "fund_id" in funds.columns else []:
        p = portfolio_metrics(holdings, fid)
        portfolio_rows.append(p.get("reported_weight_sum", np.nan) if p.get("available") else np.nan)
    result["持仓权重合计"] = portfolio_rows
    result["数据充分"] = result["净值月数"] >= min_observations
    result["通过回撤门槛"] = result["最大回撤"].notna() & (result["最大回撤"].abs() <= max_drawdown_limit)
    result["可排名"] = result["数据充分"] & result["通过回撤门槛"]
    result["未入选原因"] = ""
    result.loc[~result["数据充分"], "未入选原因"] = f"净值观测不足（少于{min_observations}个点）"
    result.loc[result["数据充分"] & ~result["通过回撤门槛"], "未入选原因"] = f"最大回撤超过{max_drawdown_limit:.0%}门槛"
    metric_columns = {"annual_return": "年化收益", "sharpe": "夏普比率", "max_drawdown": "最大回撤"}
    required_columns = [metric_columns[metric] for metric in normalized_weights]
    missing_metric = result["可排名"] & result[required_columns].isna().any(axis=1)
    result.loc[missing_metric, "可排名"] = False
    result.loc[missing_metric, "未入选原因"] = "评分所需指标缺失"
    eligible = result.loc[result["可排名"]]
    score = pd.Series(0.0, index=eligible.index)
    if len(eligible) < 2:
        result.loc[eligible.index, "可排名"] = False
        result.loc[eligible.index, "未入选原因"] = "可比基金不足2只"
    else:
        for metric, weight in normalized_weights.items():
            values = eligible[metric_columns[metric]]
            percentile = (-values.abs()).rank(pct=True, method="average") if metric == "max_drawdown" else values.rank(pct=True, method="average")
            score += percentile * weight
    result["筛选分数"] = np.nan
    if len(eligible) >= 2:
        result.loc[score.index, "筛选分数"] = score
    result["名次"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    ranked = result.loc[result["可排名"] & result["筛选分数"].notna()].sort_values("筛选分数", ascending=False)
    result.loc[ranked.index, "名次"] = range(1, len(ranked) + 1)
    return result.sort_values(["可排名", "筛选分数"], ascending=[False, False], na_position="last").reset_index(drop=True)
