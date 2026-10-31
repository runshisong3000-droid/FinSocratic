"""Tail-risk and drawdown analytics, borrowing empyrical/quantstats definitions.

Each function is deterministic and returns a plain number (or ``None`` when the
sample is too small). Definitions mirror empyrical (Quantopian) and quantstats
so figures are comparable with institutional tear sheets.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float | None:
    """Historical Value at Risk at ``confidence`` (a loss, expressed as a negative return)."""
    if len(returns) < 2:
        return None
    cutoff = 1.0 - confidence
    return _finite(float(np.percentile(returns, 100.0 * cutoff)))


def conditional_var(returns: pd.Series, confidence: float = 0.95) -> float | None:
    """Expected shortfall: mean of returns at or below the VaR cutoff."""
    var = historical_var(returns, confidence)
    if var is None:
        return None
    tail = returns[returns <= var]
    if tail.empty:
        return None
    return _finite(float(tail.mean()))


def tail_ratio(returns: pd.Series) -> float | None:
    """empyrical.tail_ratio: |95th percentile| / |5th percentile|."""
    if len(returns) < 2:
        return None
    upper = float(np.percentile(returns, 95))
    lower = float(np.percentile(returns, 5))
    if abs(lower) < 1e-12:
        return None
    return _finite(abs(upper) / abs(lower))


def omega_ratio(returns: pd.Series, required_return: float = 0.0) -> float | None:
    """Omega ratio above ``required_return``: sum(gains) / sum(|losses|)."""
    if len(returns) < 2:
        return None
    excess = returns - required_return
    gains = float(excess[excess > 0].sum())
    losses = float((-excess[excess < 0]).sum())
    if losses < 1e-12:
        return None
    return _finite(gains / losses)


def max_drawdown_duration(values: pd.Series) -> int | None:
    """Longest consecutive underwater period (drawdown < 0), in observations."""
    values = pd.Series(values, dtype=float)
    if len(values) < 2 or values.isna().any():
        return None
    drawdown = values / values.cummax() - 1.0
    longest = 0
    current = 0
    for underwater in (drawdown < 0):
        if underwater:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def tail_risk_summary(returns: pd.Series, values: pd.Series) -> dict[str, Any]:
    """One-shot tail-risk and drawdown deep-dive with reproduction formulas."""
    metrics = {
        "var_95": historical_var(returns, 0.95),
        "var_99": historical_var(returns, 0.99),
        "cvar_95": conditional_var(returns, 0.95),
        "tail_ratio": tail_ratio(returns),
        "omega_ratio": omega_ratio(returns),
        "max_drawdown_duration": max_drawdown_duration(values),
    }
    formulas = {
        "var_95": "历史 VaR(95%)：收益的 5% 分位数（负值表示损失）",
        "var_99": "历史 VaR(99%)：收益的 1% 分位数（负值表示损失）",
        "cvar_95": "期望短缺 ES(95%)：收益 ≤ VaR(95%) 的平均值",
        "tail_ratio": "|95% 分位收益| / |5% 分位收益|（empyrical 定义）",
        "omega_ratio": "sum(正收益) / sum(|负收益|)，阈值 0",
        "max_drawdown_duration": "净值连续低于历史高点的最长观测期数",
    }
    assumptions = [
        "VaR/CVaR 为历史模拟法，仅反映样本内经验分布，不是未来损失保证。",
        "简单收益未做对数化；日/周/月频下的绝对数值口径不同，需结合数据频率解读。",
    ]
    return {"metrics": metrics, "formulas": formulas, "assumptions": assumptions}
