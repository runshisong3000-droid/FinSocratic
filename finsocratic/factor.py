"""Deterministic multi-factor performance attribution.

Return-based factor regression is the standard academic tool for asking "does a
manager add alpha after controlling for known risk factors?". This module
implements OLS against the Fama-French 3- and 5-factor models using only numpy
and scipy, computing exposures, t-statistics, p-values and R-squared so the
result can be reproduced and scrutinised.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

FACTOR_LABELS = {
    "mkt_rf": "市场风险溢价（Mkt-RF）",
    "smb": "规模因子（SMB，小盘-大盘）",
    "hml": "价值因子（HML，高账面-低账面）",
    "rmw": "盈利因子（RMW，稳健-疲弱）",
    "cma": "投资因子（CMA，保守-激进）",
    "rf": "无风险利率",
}


def _finite_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def _align(returns: pd.Series, factors: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Join fund returns and factors on year-month periods.

    Fund returns are labelled by calendar month-end while factor dates are the
    month-start (Ken French ``%Y%m``) or the last trading day; aligning on the
    ``M`` period tolerates these one- or two-day label shifts without losing
    valid monthly observations.
    """
    if not isinstance(returns.index, pd.DatetimeIndex):
        returns = returns.copy()
        returns.index = pd.to_datetime(returns.index)
    returns = returns.copy()
    returns.index = returns.index.to_period("M")
    factors = factors.copy()
    factors.index = pd.to_datetime(factors.index).to_period("M")
    joined = pd.DataFrame({"return": _finite_series(returns)}).join(factors, how="inner")
    return joined["return"], joined[factors.columns]


def factor_regression(
    returns: pd.Series,
    factors: pd.DataFrame,
    *,
    rf_series: pd.Series | None = None,
    periods_per_year: int | None = 12,
) -> dict[str, Any]:
    """OLS regression of excess fund returns on Fama-French factors.

    ``returns`` is a series indexed by period-end dates (monthly expected).
    ``factors`` has columns such as ``mkt_rf, smb, hml, rmw, cma, rf``.
    ``rf_series`` optionally overrides the RF column inside ``factors``.
    """
    factor_cols = [col for col in factors.columns if col != "rf"]
    y, x_frame = _align(returns, factors)
    if len(y) < len(factor_cols) + 2:
        return {"observations": len(y), "factor_names": factor_cols, "metrics": {}, "assumptions": [
            "观测期不足，无法稳定估计多因子回归。", "因子数据与基金收益已按相同期末日期对齐。",
        ]}
    rf = None
    if "rf" in x_frame.columns:
        rf = x_frame["rf"]
    if rf_series is not None:
        rf = _finite_series(rf_series).reindex(x_frame.index)
    excess = y - (rf if rf is not None else 0.0)
    x = x_frame[factor_cols].astype(float)
    x = pd.DataFrame({"const": 1.0, **{col: x[col] for col in factor_cols}}, index=x.index)
    valid = excess.notna() & x.notna().all(axis=1)
    excess, x = excess.loc[valid], x.loc[valid]
    n, k = len(x), x.shape[1]
    if n <= k:
        return {"observations": n, "factor_names": factor_cols, "metrics": {}, "assumptions": [
            "观测期不足，无法稳定估计多因子回归。", "因子数据与基金收益已按相同期末日期对齐。",
        ]}
    xtx_inv = np.linalg.inv(x.to_numpy().T @ x.to_numpy())
    beta = xtx_inv @ x.to_numpy().T @ excess.to_numpy()
    residuals = excess.to_numpy() - x.to_numpy() @ beta
    rss = float(residuals @ residuals)
    tss = float(((excess - excess.mean()) ** 2).sum())
    dof = n - k
    sigma2 = rss / dof if dof > 0 else float("nan")
    cov = xtx_inv * sigma2
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    t_stat = beta / se
    p_value = 2 * (1 - stats.t.cdf(np.abs(t_stat), df=dof))
    r_squared = 1 - rss / tss if tss > 0 else float("nan")
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / dof if dof > 0 else float("nan")
    f_stat = float((tss - rss) / (k - 1) / sigma2) if sigma2 > 0 else float("nan")
    alpha_monthly = float(beta[0])
    alpha_annualized = float((1 + alpha_monthly) ** (periods_per_year or 12) - 1)
    residual_vol_monthly = float(np.sqrt(sigma2))
    metrics: dict[str, Any] = {
        "alpha_monthly": alpha_monthly,
        "alpha_annualized": alpha_annualized,
        "r_squared": r_squared,
        "adj_r_squared": adj_r_squared,
        "f_statistic": f_stat,
        "f_pvalue": float(1 - stats.f.cdf(f_stat, k - 1, dof)) if math.isfinite(f_stat) else None,
        "residual_volatility_monthly": residual_vol_monthly,
        "residual_volatility_annualized": float(residual_vol_monthly * math.sqrt(periods_per_year or 12)),
        "observations": n,
    }
    exposures = [{
        "factor": col, "label": FACTOR_LABELS.get(col, col), "coefficient": float(beta[idx]),
        "std_error": float(se[idx]), "t_statistic": float(t_stat[idx]),
        "p_value": float(p_value[idx]), "significant": bool(p_value[idx] < 0.05),
    } for idx, col in enumerate(["const"] + factor_cols)]
    formulas = {
        "alpha_annualized": "(1 + 截距)^12 - 1（月频年化）",
        "r_squared": "1 - RSS/TSS",
        "adj_r_squared": "1 - (1-R²)(n-1)/(n-k-1)",
    }
    assumptions = [
        f"OLS 多元回归：{n} 个对齐的期末观测，{k} 个估计参数（含截距）。",
        "无风险利率来自因子表 RF 列（或调用方传入），月频小数口径。",
        "因子为 Kenneth R. French 数据库的美股学术因子；对中国资产仅作方法演示，不代表本土风险溢价。",
        "异方差与自相关未做稳健标准误校正；月频序列较短时 p 值应谨慎解读。",
        "回归描述历史样本，不证明管理人能力或未来表现。",
    ]
    return {"observations": n, "factor_names": factor_cols, "metrics": metrics,
            "exposures": exposures, "formulas": formulas, "assumptions": assumptions}


def single_factor_summary(returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int | None = 12) -> dict[str, Any]:
    """Convenience CAPM-style regression (already covered by attribution module)."""
    frame = pd.DataFrame({"r": returns, "m": benchmark_returns}).dropna()
    if len(frame) < 3:
        return {"observations": len(frame), "metrics": {}}
    slope, intercept, r, p, se = stats.linregress(frame["m"], frame["r"])
    n = len(frame)
    return {
        "observations": n,
        "metrics": {
            "beta": float(slope), "alpha_monthly": float(intercept),
            "alpha_annualized": float((1 + intercept) ** (periods_per_year or 12) - 1),
            "correlation": float(r), "r_squared": float(r * r), "beta_pvalue": float(p),
            "beta_stderr": float(se),
        },
    }
