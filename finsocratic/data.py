"""Data loading and finance calculations for the local FinSocratic prototype."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as _stats

from .risk_metrics import tail_risk_summary

ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT.parent / "data" / "sample"
# On Windows, keep user data and downloaded/runtime artifacts on D: by default.
# The environment variable allows a different location when D: is unavailable.
DEFAULT_HOME = Path("D:/FinSocratic-ResearchAgent") if sys.platform == "win32" else Path.home() / ".finsocratic"
DATA_HOME = Path(os.environ.get("FINSOCRATIC_HOME", str(DEFAULT_HOME))) / "data"
WORKSPACE = DATA_HOME / "workspaces" / "default"
UPLOADS = WORKSPACE / "uploads"


def load_samples() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    funds = pd.read_csv(SAMPLE_DIR / "funds.csv", dtype={"fund_id": str})
    nav = pd.read_csv(SAMPLE_DIR / "nav_monthly.csv", parse_dates=["date"], dtype={"fund_id": str})
    holdings = pd.read_csv(SAMPLE_DIR / "holdings.csv", parse_dates=["as_of"], dtype={"fund_id": str})
    return funds, nav, holdings


def load_uploaded_table(name: str, raw: bytes, sheet_name: str | None = None) -> pd.DataFrame:
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        try:
            return pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig", dtype={"fund_id": str})
        except UnicodeDecodeError:
            return pd.read_csv(io.BytesIO(raw), encoding="gb18030", encoding_errors="replace", dtype={"fund_id": str})
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(io.BytesIO(raw), sheet_name=sheet_name or 0, dtype={"fund_id": str})
    raise ValueError("目前只支持导入 CSV、XLSX 或 XLSM 表格。")


def normalize_nav(frame: pd.DataFrame, date_col: str, value_col: str, fund_id: str) -> tuple[pd.DataFrame, list[str]]:
    out = pd.DataFrame({"date": pd.to_datetime(frame[date_col], errors="coerce"), "nav": pd.to_numeric(frame[value_col], errors="coerce")})
    out["fund_id"] = str(fund_id)
    warnings: list[str] = []
    invalid = int((out[["date", "nav"]].isna().any(axis=1) | ~np.isfinite(out["nav"])).sum())
    if invalid:
        warnings.append(f"已排除 {invalid} 行日期或净值无效的数据。")
        out = out.loc[out[["date", "nav"]].notna().all(axis=1) & np.isfinite(out["nav"])]
    nonpositive = int((out["nav"] <= 0).sum())
    if nonpositive:
        warnings.append(f"已排除 {nonpositive} 行非正净值数据。")
        out = out.loc[out["nav"] > 0]
    duplicates = int(out.duplicated("date", keep="last").sum())
    if duplicates:
        warnings.append(f"检测到 {duplicates} 个重复日期，保留每个日期的最后一条记录。")
        out = out.drop_duplicates("date", keep="last")
    out = out.sort_values("date").reset_index(drop=True)
    return out[["date", "fund_id", "nav"]], warnings


def returns_for(nav: pd.DataFrame, fund_id: str) -> pd.Series:
    if nav.empty or not {"fund_id", "date", "nav"}.issubset(nav.columns):
        return pd.Series(dtype=float)
    track = nav.loc[nav["fund_id"].astype(str) == str(fund_id)].copy()
    track["date"] = pd.to_datetime(track["date"], errors="coerce")
    track["nav"] = pd.to_numeric(track["nav"], errors="coerce")
    track = track.loc[track[["date", "nav"]].notna().all(axis=1) & np.isfinite(track["nav"])]
    track = track.loc[track["nav"] > 0].sort_values("date").drop_duplicates("date", keep="last")
    return track.set_index("date")["nav"].pct_change().dropna()


def max_drawdown(nav_values: pd.Series) -> float:
    if nav_values.empty:
        return float("nan")
    return float((nav_values / nav_values.cummax() - 1).min())


def infer_nav_frequency(dates: pd.Series) -> tuple[str, int | None]:
    """Recognize common, reasonably regular NAV cadences for risk scaling."""
    gaps = pd.to_datetime(dates, errors="coerce").sort_values().diff().dt.total_seconds().dropna() / 86400
    if len(gaps) < 2:
        return "观测不足", None
    if (gaps.between(0.75, 1.25).mean() >= 0.5 and (gaps <= 4).mean() >= 0.8):
        return "日频", 252
    for label, periods, lower, upper in (
        ("周频", 52, 5, 9),
        ("月频", 12, 25, 35),
        ("季频", 4, 75, 105),
        ("年频", 1, 350, 380),
    ):
        if gaps.between(lower, upper).mean() >= 0.8:
            return label, periods
    return "不规则", None


def fund_metrics(nav: pd.DataFrame, fund_id: str) -> dict[str, float | int | str | None]:
    empty = {"total_return": np.nan, "annual_return": np.nan, "volatility": np.nan,
             "max_drawdown": np.nan, "sharpe": np.nan, "sortino": np.nan, "calmar": np.nan,
             "downside_deviation": np.nan, "skew": np.nan, "kurtosis": np.nan,
             "var_95": np.nan, "var_99": np.nan, "cvar_95": np.nan,
             "tail_ratio": np.nan, "omega_ratio": np.nan, "max_drawdown_duration": np.nan,
             "months": 0, "start": "—", "end": "—", "frequency": "观测不足", "periods_per_year": None}
    if nav.empty or not {"fund_id", "date", "nav"}.issubset(nav.columns):
        return empty
    track = nav.loc[nav["fund_id"].astype(str) == str(fund_id)].copy()
    track["date"] = pd.to_datetime(track["date"], errors="coerce")
    track["nav"] = pd.to_numeric(track["nav"], errors="coerce")
    track = track.loc[track[["date", "nav"]].notna().all(axis=1) & np.isfinite(track["nav"])]
    track = track.loc[track["nav"] > 0].sort_values("date").drop_duplicates("date", keep="last")
    if len(track) < 2:
        return {**empty, "months": len(track)}
    r = track.set_index("date")["nav"].pct_change().dropna()
    frequency, periods_per_year = infer_nav_frequency(track["date"])
    total = float(track.nav.iloc[-1] / track.nav.iloc[0] - 1)
    years = (track.date.iloc[-1] - track.date.iloc[0]).total_seconds() / (86400 * 365.2425)
    if years <= 0:
        return {**empty, "months": len(track)}
    annual = float((1 + total) ** (1 / years) - 1)
    std = r.std(ddof=1) if len(r) > 1 else np.nan
    vol = float(std * np.sqrt(periods_per_year)) if periods_per_year and np.isfinite(std) else np.nan
    sharpe = float(r.mean() / std * np.sqrt(periods_per_year)) if periods_per_year and np.isfinite(std) and std > 0 else np.nan
    downside = float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2))) if len(r) > 1 else np.nan
    sortino = float(r.mean() / downside * np.sqrt(periods_per_year)) if periods_per_year and np.isfinite(downside) and downside > 0 else np.nan
    skew = float(_stats.skew(r)) if len(r) > 2 else np.nan
    kurtosis = float(_stats.kurtosis(r)) if len(r) > 3 else np.nan
    tail = tail_risk_summary(r, track.nav)["metrics"]
    mdd = max_drawdown(track.nav)
    calmar = float(annual / abs(mdd)) if np.isfinite(annual) and np.isfinite(mdd) and mdd < 0 else np.nan
    return {"total_return": total, "annual_return": annual, "volatility": vol,
            "max_drawdown": mdd, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
            "downside_deviation": downside, "skew": skew, "kurtosis": kurtosis,
            "var_95": tail["var_95"], "var_99": tail["var_99"], "cvar_95": tail["cvar_95"],
            "tail_ratio": tail["tail_ratio"], "omega_ratio": tail["omega_ratio"],
            "max_drawdown_duration": tail["max_drawdown_duration"], "months": len(track),
            "start": track.date.iloc[0].strftime("%Y-%m-%d"), "end": track.date.iloc[-1].strftime("%Y-%m-%d"),
            "frequency": frequency, "periods_per_year": periods_per_year}


def all_metrics(funds: pd.DataFrame, nav: pd.DataFrame) -> pd.DataFrame:
    columns = ["基金", "基金编号", "管理人", "策略", "区间收益", "年化收益", "年化波动", "最大回撤", "夏普比率", "索提诺比率", "卡玛比率", "偏度", "峰度", "95%VaR", "95%CVaR", "尾部比率", "Omega比率", "最长水下期", "净值月数", "数据频率"]
    if funds.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for row in funds.itertuples(index=False):
        m = fund_metrics(nav, str(row.fund_id))
        rows.append({"基金": row.name, "基金编号": row.fund_id, "管理人": row.manager, "策略": row.strategy, "区间收益": m["total_return"], "年化收益": m["annual_return"], "年化波动": m["volatility"], "最大回撤": m["max_drawdown"], "夏普比率": m["sharpe"], "索提诺比率": m["sortino"], "卡玛比率": m["calmar"], "偏度": m["skew"], "峰度": m["kurtosis"], "95%VaR": m["var_95"], "95%CVaR": m["cvar_95"], "尾部比率": m["tail_ratio"], "Omega比率": m["omega_ratio"], "最长水下期": m["max_drawdown_duration"], "净值月数": m["months"], "数据频率": m["frequency"]})
    return pd.DataFrame(rows, columns=columns)


def monthly_returns(nav: pd.DataFrame, fund_id: str) -> pd.Series:
    """Month-end NAV returns; returns a Series indexed by monthly Period."""
    if nav.empty or not {"fund_id", "date", "nav"}.issubset(nav.columns):
        return pd.Series(dtype=float)
    track = nav.loc[nav["fund_id"].astype(str) == str(fund_id)].copy()
    track["date"] = pd.to_datetime(track["date"], errors="coerce")
    track["nav"] = pd.to_numeric(track["nav"], errors="coerce")
    track = track.loc[track[["date", "nav"]].notna().all(axis=1) & np.isfinite(track["nav"])]
    track = track.loc[track["nav"] > 0].sort_values("date").drop_duplicates("date", keep="last")
    month_end = track.set_index("date")["nav"].resample("ME").last()
    return month_end.pct_change().dropna()


def return_calendar(nav: pd.DataFrame, fund_id: str) -> dict[str, list[dict[str, float | str | int]]]:
    """Yearly returns and a year × month return calendar for return-path reviews."""
    monthly = monthly_returns(nav, fund_id)
    if monthly.empty:
        return {"yearly": [], "monthly": []}
    yearly_rows = []
    for year, group in monthly.groupby(monthly.index.year):
        yearly_rows.append({"year": int(year), "return": float((1 + group).prod() - 1), "months": int(group.count())})
    monthly_rows = []
    for year, group in monthly.groupby(monthly.index.year):
        row: dict[str, float | str | int] = {"year": int(year)}
        for month in range(1, 13):
            value = group[group.index.month == month]
            row[f"{month}月"] = float(value.iloc[0]) if len(value) else float("nan")
        row["全年"] = float((1 + group).prod() - 1)
        monthly_rows.append(row)
    return {"yearly": yearly_rows, "monthly": monthly_rows}


def read_spreadsheet_sheets(name: str, raw: bytes) -> dict[str, pd.DataFrame]:
    if Path(name).suffix.lower() not in {".xlsx", ".xlsm"}:
        return {"数据": load_uploaded_table(name, raw)}
    return pd.read_excel(io.BytesIO(raw), sheet_name=None)
