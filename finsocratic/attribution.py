"""Benchmark-relative, risk-adjusted attribution computed deterministically.

Number crunching delegates to SciPy (the battle-tested regression engine also
used under the hood by pyfolio/quantstats) wherever a canonical, maintained
implementation exists. Formulas are returned alongside values so a reviewer can
reproduce each figure independently.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as _stats


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _regression(fund: pd.Series, benchmark: pd.Series):
    if len(fund) < 2 or len(benchmark) != len(fund):
        return None
    try:
        result = _stats.linregress(benchmark.to_numpy(dtype=float), fund.to_numpy(dtype=float))
    except (ValueError, TypeError):
        return None
    if not np.isfinite(result.slope):
        return None
    return result


def tracking_error(fund: pd.Series, benchmark: pd.Series, periods: int) -> float | None:
    excess = fund - benchmark
    if len(excess) < 2:
        return None
    return _finite(float(excess.std(ddof=1) * math.sqrt(periods)))


def information_ratio(fund: pd.Series, benchmark: pd.Series, periods: int) -> float | None:
    excess = fund - benchmark
    if len(excess) < 2:
        return None
    std = excess.std(ddof=1)
    if not np.isfinite(std) or std <= 1e-12:
        return None
    return _finite(float(excess.mean() / std * math.sqrt(periods)))


def active_return(fund: pd.Series, benchmark: pd.Series, periods: int) -> float | None:
    excess = fund - benchmark
    if excess.empty:
        return None
    return _finite(float(excess.mean() * periods))


def up_capture_ratio(fund: pd.Series, benchmark: pd.Series) -> float | None:
    up = benchmark > 0
    if not up.any():
        return None
    denominator = float(benchmark[up].sum())
    if abs(denominator) < 1e-12:
        return None
    return _finite(float(fund[up].sum() / denominator))


def down_capture_ratio(fund: pd.Series, benchmark: pd.Series) -> float | None:
    down = benchmark < 0
    if not down.any():
        return None
    denominator = float(benchmark[down].sum())
    if abs(denominator) < 1e-12:
        return None
    return _finite(float(fund[down].sum() / denominator))


def rolling_beta(fund: pd.Series, benchmark: pd.Series, dates: pd.Series, window: int) -> list[dict[str, Any]]:
    """Trailing-window OLS beta at each end date, without forward-looking data."""
    rows: list[dict[str, Any]] = []
    if window < 2 or len(fund) < window:
        return rows
    for end in range(window - 1, len(fund)):
        f = fund.iloc[end - window + 1 : end + 1]
        b = benchmark.iloc[end - window + 1 : end + 1]
        reg = _regression(f, b)
        if reg is None:
            continue
        rows.append({"end_date": pd.Timestamp(dates.iloc[end]).strftime("%Y-%m-%d"),
                     "beta": _finite(reg.slope), "observations": int(len(f))})
    return rows


def risk_adjusted_attribution(
    fund_returns: pd.Series,
    benchmark_returns: pd.Series,
    *,
    periods_per_year: int | None = None,
    dates: pd.Series | None = None,
) -> dict[str, Any]:
    """Compute benchmark-relative attribution for aligned, NaN-free returns.

    ``fund_returns`` and ``benchmark_returns`` must be same-length pandas Series
    of simple periodic returns already aligned to identical dates. ``periods`` is
    the annualization factor; ``None`` suppresses annualized metrics. ``dates``
    optionally supplies observation dates for the rolling beta series.
    """
    fund = pd.Series(fund_returns, dtype=float).reset_index(drop=True)
    benchmark = pd.Series(benchmark_returns, dtype=float).reset_index(drop=True)
    if len(fund) != len(benchmark):
        raise ValueError("基金与基准收益序列长度不一致，无法做风险调整归因。")
    if dates is not None:
        dates = pd.Series(dates).reset_index(drop=True)
        if len(dates) != len(fund):
            raise ValueError("归因日期序列长度与收益序列不一致。")

    formulas = {
        "beta": "OLS 回归斜率 cov(fund, benchmark) / var(benchmark)（scipy.linregress）",
        "alpha_annualized": "OLS 截距 × 每年期数（无风险利率设为0）",
        "correlation": "OLS 相关系数 r",
        "r_squared": "r²（基准收益可解释的基金收益比例）",
        "beta_pvalue": "回归斜率显著性的 p 值",
        "beta_stderr": "回归斜率的标准误",
        "tracking_error": "std(fund - benchmark, ddof=1) × sqrt(每年期数)",
        "information_ratio": "mean(fund - benchmark) / std(fund - benchmark, ddof=1) × sqrt(每年期数)",
        "active_return_annualized": "mean(fund - benchmark) × 每年期数",
        "up_capture_ratio": "sum(fund | benchmark>0) / sum(benchmark | benchmark>0)",
        "down_capture_ratio": "sum(fund | benchmark<0) / sum(benchmark | benchmark<0)",
    }
    assumptions = [
        "无风险利率设为0；alpha、信息比率与主动收益仅衡量相对基准的风险调整表现。",
        "收益率使用相邻净值的简单百分比；未独立验证分红、费用与复权口径。",
        "beta、相关性与捕获率由历史样本估计，不是稳定参数，也不构成未来预测。",
    ]
    metrics: dict[str, float | None] = {key: None for key in formulas}

    if len(fund) < 2 or periods_per_year is None:
        return {
            "metrics": metrics, "formulas": formulas, "observations": int(len(fund)),
            "periods_per_year": periods_per_year, "rolling_beta": [], "assumptions": assumptions,
        }

    reg = _regression(fund, benchmark)
    if reg is not None:
        metrics.update({
            "beta": _finite(reg.slope),
            "alpha_annualized": _finite(reg.intercept * int(periods_per_year)),
            "correlation": _finite(reg.rvalue),
            "r_squared": _finite(reg.rvalue ** 2),
            "beta_pvalue": _finite(reg.pvalue),
            "beta_stderr": _finite(reg.stderr),
        })
    metrics.update({
        "tracking_error": tracking_error(fund, benchmark, int(periods_per_year)),
        "information_ratio": information_ratio(fund, benchmark, int(periods_per_year)),
        "active_return_annualized": active_return(fund, benchmark, int(periods_per_year)),
        "up_capture_ratio": up_capture_ratio(fund, benchmark),
        "down_capture_ratio": down_capture_ratio(fund, benchmark),
    })
    rb = rolling_beta(fund, benchmark, dates, int(periods_per_year)) if dates is not None else []
    return {
        "metrics": metrics, "formulas": formulas, "observations": int(len(fund)),
        "periods_per_year": periods_per_year, "rolling_beta": rb, "assumptions": assumptions,
    }
