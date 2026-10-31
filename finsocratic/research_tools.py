"""Deterministic FOF research diagnostics with explicit evidence limitations.

All returns use imported NAV observations. Allocation changes are snapshot
comparisons, not transaction turnover or performance attribution. Correlations
match both start and end dates of each return interval.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .data import fund_metrics, infer_nav_frequency


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> pd.Timestamp:
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        number = _number(value)
        if number is None or not number.is_integer() or not 19000101 <= number <= 21001231:
            return pd.NaT
        return pd.to_datetime(str(int(number)), format="%Y%m%d", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def _iso(value: Any) -> str | None:
    return value.strftime("%Y-%m-%d") if pd.notna(value) else None


def _nav(nav: pd.DataFrame, fund_id: str) -> tuple[pd.DataFrame, list[str]]:
    empty = pd.DataFrame(columns=["fund_id", "date", "nav", "source_file"])
    if nav.empty or not {"fund_id", "date", "nav"}.issubset(nav.columns):
        return empty, ["没有可用净值序列。"]
    frame = nav.loc[nav["fund_id"].astype(str) == str(fund_id)].copy()
    if frame.empty:
        return empty, ["没有该基金的净值序列。"]
    frame["date"] = frame["date"].map(_date)
    frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
    valid = frame["date"].notna() & np.isfinite(frame["nav"]) & (frame["nav"] > 0)
    issues = [f"排除 {int((~valid).sum())} 条日期或净值无效的记录。"] if (~valid).any() else []
    frame = frame.loc[valid].copy()
    conflicts = frame.groupby("date")["nav"].nunique()
    conflicts = conflicts.index[conflicts > 1]
    if len(conflicts):
        issues.append(f"排除 {len(conflicts)} 个存在冲突净值的日期。")
        frame = frame.loc[~frame["date"].isin(conflicts)]
    frame = frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)
    frame["fund_id"] = str(fund_id)
    if "source_file" not in frame:
        frame["source_file"] = "导入净值"
    return frame, issues


def holdings_drift(holdings: pd.DataFrame, fund_id: str) -> dict[str, Any]:
    """Compare complete allocation snapshots without inferring transactions."""
    limits = [
        "配置变动幅度 = 0.5 × 各类别权重变动绝对值之和；它是快照变动代理，不是真实交易换手率。",
        "权重变化可能来自价格变动、申赎、分类调整或主动交易；缺少交易流水时不能拆解原因。",
        "缺失类别在完整快照之间按零权重处理；资产分类口径须保持一致，未自动穿透底层基金。",
    ]
    result: dict[str, Any] = {"fund_id": str(fund_id), "snapshots": [], "transitions": [], "latest": None,
                              "issues": [], "limits": limits}
    required = {"fund_id", "asset", "weight_pct", "as_of"}
    if holdings.empty or not required.issubset(holdings.columns):
        result["issues"].append("没有可比较的持仓历史。")
        return result
    frame = holdings.loc[holdings["fund_id"].astype(str) == str(fund_id)].copy()
    frame["as_of"] = frame["as_of"].map(_date)
    frame["weight_pct"] = pd.to_numeric(frame["weight_pct"], errors="coerce")
    if frame["as_of"].isna().any():
        result["issues"].append("日期无效的持仓行未纳入跨期比较。")
    for date, group in frame.dropna(subset=["as_of"]).groupby("as_of", sort=True):
        valid = group["asset"].notna() & group["asset"].astype(str).str.strip().ne("") & group["weight_pct"].between(0, 100)
        if not valid.all():
            result["issues"].append(f"{_iso(date)} 快照存在无效类别或权重，整期未纳入比较。")
            continue
        weights = group.groupby("asset")["weight_pct"].sum().sort_values(ascending=False)
        total = float(weights.sum())
        if total <= 0:
            result["issues"].append(f"{_iso(date)} 快照权重合计为零，整期未纳入比较。")
            continue
        hhi = float(((weights / total) ** 2).sum())
        complete = abs(total - 100) <= 1
        result["snapshots"].append({
            "as_of": _iso(date), "total_weight_pct": total, "complete": complete,
            "hhi": hhi, "effective_categories": 1 / hhi if hhi else None,
            "top_asset": str(weights.index[0]), "top_weight_pct": float(weights.iloc[0]),
            "assets": [{"asset": str(asset), "weight_pct": float(weight)} for asset, weight in weights.items()],
            "sources": sorted(set(group.get("source_file", pd.Series(["导入持仓"])).dropna().astype(str))),
        })
    for previous, current in zip(result["snapshots"], result["snapshots"][1:]):
        old = {item["asset"]: item["weight_pct"] for item in previous["assets"]}
        new = {item["asset"]: item["weight_pct"] for item in current["assets"]}
        changes = [{"asset": asset, "from_weight_pct": old.get(asset, 0.0), "to_weight_pct": new.get(asset, 0.0),
                    "delta_pp": new.get(asset, 0.0) - old.get(asset, 0.0)} for asset in sorted(set(old) | set(new))]
        changes.sort(key=lambda item: abs(item["delta_pp"]), reverse=True)
        comparable = previous["complete"] and current["complete"]
        result["transitions"].append({
            "from_date": previous["as_of"], "to_date": current["as_of"], "comparable": comparable,
            "turnover_proxy_pct": sum(abs(item["delta_pp"]) for item in changes) / 2 if comparable else None,
            "largest_change_pp": max((abs(item["delta_pp"]) for item in changes), default=0.0),
            "changes": changes,
            "note": "两个快照权重完整；请核对分类口径。" if comparable else "至少一个快照权重不完整，未计算配置变动幅度。",
        })
    result["latest"] = result["transitions"][-1] if result["transitions"] else None
    if len(result["snapshots"]) < 2:
        result["issues"].append("少于两期有效持仓，无法计算配置变化。")
    return result


def _periods(track: pd.DataFrame) -> list[dict[str, Any]]:
    records = list(track.itertuples(index=False))
    return [{"start":_iso(a.date),"end":_iso(b.date),"return":float(b.nav/a.nav-1),
             "days":int((b.date-a.date).days),"start_nav":float(a.nav),"end_nav":float(b.nav),
             "source_start":str(a.source_file),"source_end":str(b.source_file)} for a,b in zip(records,records[1:])]



def _episodes(track: pd.DataFrame) -> list[dict[str, Any]]:
    if track.empty:
        return []
    episodes = []
    peak = trough = 0
    active = False
    nav_values = track["nav"].to_numpy(dtype=float)
    for i in range(1, len(track)):
        value, peak_value = nav_values[i], nav_values[peak]
        if value >= peak_value * (1 - 1e-12):
            if active:
                episodes.append(_episode_record(track, peak, trough, i))
                active = False
            peak = trough = i
        else:
            if not active:
                active = True
                trough = i
            elif value < nav_values[trough]:
                trough = i
    if active:
        episodes.append(_episode_record(track, peak, trough, None))
    return sorted(episodes, key=lambda item: item["depth"])


def _episode_record(track: pd.DataFrame, peak: int, trough: int, recovery: int | None) -> dict[str, Any]:
    end = recovery if recovery is not None else len(track) - 1
    return {"peak_date": _iso(track.iloc[peak]["date"]), "trough_date": _iso(track.iloc[trough]["date"]),
            "recovery_date": _iso(track.iloc[recovery]["date"]) if recovery is not None else None,
            "depth": float(track.iloc[trough]["nav"] / track.iloc[peak]["nav"] - 1),
            "underwater_days": int((track.iloc[end]["date"] - track.iloc[peak]["date"]).days),
            "observations_underwater": end - peak, "recovered": recovery is not None,
            "as_of": _iso(track.iloc[end]["date"])}


def nav_diagnostics(nav: pd.DataFrame, fund_id: str) -> dict[str, Any]:
    """Return-path diagnostics that expose period sensitivity and recovery time."""
    track, issues = _nav(nav, fund_id)
    frequency, annual_periods = infer_nav_frequency(track["date"])
    metrics = {key: (_number(value) if isinstance(value, (float, np.floating)) else value)
               for key, value in fund_metrics(track, str(fund_id)).items()}
    periods = _periods(track)
    result: dict[str, Any] = {
        "fund_id": str(fund_id), "metrics": metrics, "frequency": frequency,
        "period_returns": periods, "worst_periods": sorted(periods, key=lambda item: item["return"])[:5],
        "rolling_returns": [], "horizon_summary": [], "drawdown_episodes": _episodes(track),
        "drawdown_path": [], "issues": issues,
        "limits": ["全部路径统计来自已导入观测点，月频数据无法还原月内更深回撤。",
                   "滚动窗口按识别频率近似季度、半年和一年；日频采用 63/126/252 期，未强行填补缺失净值。",
                   "收益贡献和风险贡献需要底层策略收益、同期权重和协方差；当前未据持仓比例推断贡献。"],
    }
    if track.empty:
        return result
    values = track["nav"].astype(float)
    dd = values / values.cummax() - 1
    result["drawdown_path"] = [{"date": _iso(date), "nav": float(value), "drawdown": float(drawdown)}
                               for date, value, drawdown in zip(track["date"], values, dd)]
    # A rolling window is only emitted when both the cadence and actual span fit.
    horizons = {"日频": (63, 126, 252), "周频": (13, 26, 52), "月频": (3, 6, 12), "季频": (1, 2, 4)}
    if frequency not in horizons:
        result["issues"].append("频率不规则或样本不足，未输出标准滚动窗口。")
        return result
    result["rolling_returns"] = [{"date": _iso(date), "return_3m": None, "return_6m": None, "return_12m": None}
                                 for date in track["date"]]
    track_dates = track["date"].tolist()
    track_values = values.to_numpy()
    for months, width in zip((3, 6, 12), horizons[frequency]):
        key = f"return_{months}m"
        points = []
        for end in range(width, len(track)):
            start = end - width
            days = int((track_dates[end] - track_dates[start]).days)
            if not months * 30.4375 * 0.7 <= days <= months * 30.4375 * 1.3:
                continue
            value = float(track_values[end] / track_values[start] - 1)
            result["rolling_returns"][end][key] = value
            points.append({"start": _iso(track_dates[start]), "end": _iso(track_dates[end]), "return": value})
        result["horizon_summary"].append({
            "key": key, "label": f"滚动{months}个月", "periods": width, "observations": len(points),
            "latest": points[-1]["return"] if points else None,
            "worst": min(points, key=lambda item: item["return"]) if points else None,
            "best": max(points, key=lambda item: item["return"]) if points else None,
            "positive_rate": sum(point["return"] > 0 for point in points) / len(points) if points else None,
        })
    return result


def fund_correlations(nav: pd.DataFrame, funds: pd.DataFrame | None = None, min_observations: int = 6) -> dict[str, Any]:
    """Pairwise return correlation on identical start AND end observation dates."""
    ids = sorted(nav["fund_id"].dropna().astype(str).unique()) if "fund_id" in nav else []
    names = dict(zip(funds["fund_id"].astype(str), funds["name"].astype(str))) if funds is not None and {"fund_id", "name"}.issubset(funds.columns) else {}
    series = {}
    for fund_id in ids:
        track, _ = _nav(nav, fund_id)
        series[fund_id] = pd.DataFrame(_periods(track), columns=["start", "end", "return"])
    size = len(ids)
    matrix: list[list[float | None]] = [[None] * size for _ in ids]
    samples = [[0] * size for _ in ids]
    pairs = []
    for i, first in enumerate(ids):
        for j in range(i, size):
            second = ids[j]
            matched = series[first].merge(series[second], on=["start", "end"], suffixes=("_a", "_b"))
            count = len(matched)
            coefficient = None
            status = "样本不足"
            if count >= min_observations:
                if matched["return_a"].std(ddof=1) > 1e-12 and matched["return_b"].std(ddof=1) > 1e-12:
                    coefficient = float(matched["return_a"].corr(matched["return_b"]))
                    status = "可计算"
                else:
                    status = "收益序列缺少变化"
            matrix[i][j] = matrix[j][i] = coefficient
            samples[i][j] = samples[j][i] = count
            if i != j:
                pairs.append({"fund_a": first, "fund_b": second, "name_a": names.get(first, first), "name_b": names.get(second, second),
                              "correlation": coefficient, "observations": count, "status": status,
                              "start": str(matched["start"].min()) if count else None,
                              "end": str(matched["end"].max()) if count else None})
    return {"funds": [{"fund_id": fund_id, "name": names.get(fund_id, fund_id)} for fund_id in ids],
            "matrix": matrix, "sample_counts": samples, "pairs": pairs, "minimum_observations": min_observations,
            "method": "Pearson 相关系数；仅匹配起止日期均一致的相邻净值收益区间。",
            "limits": ["样本相关性描述历史共同变化，不证明未来分散效果或因果关系。",
                       "非同步或平滑估值可能低估真实相关性；少量月度观测尤其不稳定。",
                       "相关系数不等于风险贡献，未提供底层收益、组合权重和协方差估计时不计算风险预算。"]}


def research_analytics(nav: pd.DataFrame, holdings: pd.DataFrame, fund_id: str) -> dict[str, Any]:
    return {"holdings_drift": holdings_drift(holdings, fund_id), "nav_diagnostics": nav_diagnostics(nav, fund_id)}
