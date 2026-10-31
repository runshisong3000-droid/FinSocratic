"""Open-source market data acquisition with a transparent local cache.

Data sources are public and free of authentication:

- Fund NAV history: 东方财富 pingzhongdata (unit NAV, accumulated NAV, daily return).
- Index/benchmark daily bars: 东方财富 push2his kline API.
- Factor data: Kenneth R. French data library (monthly 3/5-factor, US; academic
  risk factors for return-based attribution).

Every fetch writes a small cached file under ``DATA_HOME/market`` so the offline
research workflow stays reproducible. All values are returned as plain pandas
DataFrames; nothing here calls a language model or fabricates observations.
"""
from __future__ import annotations

import io
import json
import hashlib
import re
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

from .data import DATA_HOME

CACHE_DIR = DATA_HOME / "market"
_TIMEOUT = 20
_HEADERS = {"User-Agent": "Mozilla/5.0 (FinSocratic local research; offline-capable)"}

# Common Chinese benchmarks (Tencent quote symbols; eastmoney push2his is blocked on this network).
INDEX_SYMBOL = {
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证800": "sh000906",
    "中证1000": "sh000852",
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
}

_TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

FAMA_FRENCH_5F_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip"
FAMA_FRENCH_3F_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cache_get(name: str, ttl_seconds: int, loader: Callable[[], bytes]) -> bytes:
    """Return cached bytes or fetch and store them; a failed fetch falls back to a stale cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / name
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl_seconds:
            return path.read_bytes()
    try:
        raw = loader()
    except Exception:
        if path.exists():
            return path.read_bytes()
        raise
    path.write_bytes(raw)
    return raw


def _get(url: str, params: dict[str, Any] | None = None) -> bytes:
    response = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    response.raise_for_status()
    return response.content


def _ms_to_date(millis: float) -> str:
    return datetime.fromtimestamp(int(millis) / 1000, tz=timezone(timedelta(hours=8))).date().isoformat()


def fetch_fund_list() -> pd.DataFrame:
    """All public funds from eastmoney's fundcode_search endpoint."""
    raw = _cache_get("fund_list.json", ttl_seconds=86400, loader=lambda: _get("https://fund.eastmoney.com/js/fundcode_search.js"))
    text = raw.decode("utf-8-sig", errors="replace")
    start, end = text.index("["), text.rindex("]") + 1
    rows = json.loads(text[start:end])
    return pd.DataFrame(rows, columns=["code", "pinyin", "name", "type", "pinyin_full"])


def search_funds(keyword: str, *, kind: str | None = None) -> pd.DataFrame:
    frame = fetch_fund_list()
    keyword = str(keyword).strip()
    mask = frame["name"].str.contains(keyword, na=False, regex=False) | frame["code"].str.contains(keyword, na=False, regex=False)
    if kind:
        mask &= frame["type"].str.contains(kind, na=False)
    return frame.loc[mask].reset_index(drop=True)


def fetch_fund_nav(code: str, *, use_accumulated: bool = True) -> pd.DataFrame:
    """Daily NAV for one fund, sourced from eastmoney pingzhongdata.

    Returns columns: date, nav, accumulated_nav, daily_return_pct, source_file.
    ``nav`` compounds the vendor's reported daily percentage returns by default.
    Accumulated NAV is retained for reference; it is NOT a reinvestment index.
    The vendor's return adjustments have not been independently reconciled.
    """
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("基金代码必须是六位数字。")
    raw = _cache_get(f"fund_{code}.js", ttl_seconds=86400,
                     loader=lambda: _get(f"https://fund.eastmoney.com/pingzhongdata/{code}.js"))
    text = raw.decode("utf-8-sig", errors="replace")

    def series(var: str) -> list[dict[str, Any]]:
        import re
        match = re.search(rf"var\s+{var}\s*=\s*(\[.*?\]);", text, re.S)
        return json.loads(match.group(1)) if match else []

    unit = series("Data_netWorthTrend")
    accum = series("Data_ACWorthTrend")
    rows: dict[str, list[Any]] = {"date": [], "unit_nav": [], "accumulated_nav": [], "daily_return_pct": []}
    for item in unit:
        rows["date"].append(_ms_to_date(item["x"]))
        rows["unit_nav"].append(pd.to_numeric(item["y"], errors="coerce"))
        rows["daily_return_pct"].append(pd.to_numeric(item.get("equityReturn"), errors="coerce"))
    accum_map: dict[str, float] = {}
    for item in accum:
        # Data_ACWorthTrend is [[timestamp, value], ...] while Data_netWorthTrend is [{"x": ..., "y": ...}].
        if isinstance(item, dict):
            accum_map[_ms_to_date(item["x"])] = pd.to_numeric(item["y"], errors="coerce")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            accum_map[_ms_to_date(item[0])] = pd.to_numeric(item[1], errors="coerce")
    rows["accumulated_nav"] = [accum_map.get(d) for d in rows["date"]]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["date", "nav", "accumulated_nav", "daily_return_pct", "source_file"])
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    if use_accumulated:
        growth = frame["daily_return_pct"].copy()
        growth.iloc[0] = 0.0
        if growth.isna().any() or (growth <= -100).any():
            raise ValueError("来源日涨跌幅缺失或无效，停止构造收益指数；请导入经核对的复权净值。")
        frame["nav"] = (1 + growth / 100).cumprod()
    else:
        frame["nav"] = pd.to_numeric(frame["unit_nav"], errors="coerce")
    frame["source_file"] = f"eastmoney_{code}_reported_return_index.csv" if use_accumulated else f"eastmoney_{code}_unit_nav.csv"
    frame = frame.loc[frame["nav"] > 0]
    return frame.reset_index(drop=True)


def fund_source_manifest(code: str) -> dict[str, Any]:
    path = CACHE_DIR / f"fund_{code}.js"
    raw = path.read_bytes()
    return {"provider": "东方财富 / 天天基金", "source_url": f"https://fund.eastmoney.com/pingzhongdata/{code}.js",
            "disclosure_url": f"https://fund.eastmoney.com/{code}.html",
            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": hashlib.sha256(raw).hexdigest(), "cache_stale": time.time() - path.stat().st_mtime > 86400,
            "return_basis": "来源日涨跌幅逐期连乘，首日归一为1；非累计净值；来源复权处理尚未独立核对",
            "limitations": ["销售平台数据，需与管理人原始披露交叉核对", "不包含底层持仓、经理任职、交易和费用归因", "基金名称和类别不证明实际投资策略"]}


def fetch_manager_profile(code: str) -> dict[str, Any]:
    """Dated manager tenure history for one fund from eastmoney F10.

    Returns a plain dict; no language model is involved. ``end_date`` is ``None``
    for the current appointment. Dates come from a vendor sales page and should be
    cross-checked against the fund manager's own disclosure; they are not verified
    regulatory records.
    """
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("基金代码必须是六位数字。")
    raw = _cache_get(f"manager_{code}.html", ttl_seconds=86400,
                     loader=lambda: _get(f"https://fundf10.eastmoney.com/jjjl_{code}.html"))
    text = raw.decode("utf-8-sig", errors="replace")
    rows: list[list[str]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [re.sub(r"<[^>]+>", "", cell).replace("&nbsp;", " ").strip()
                 for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        rows.append(cells)
    history: list[dict[str, Any]] = []
    in_history = False
    for cells in rows:
        if not cells:
            continue
        if cells[0] == "起始期":
            in_history = True
            continue
        if in_history and cells[0] == "基金代码":
            break  # following table lists the manager's other funds, not this fund's history
        if in_history and len(cells) >= 4:
            start = cells[0].strip() or None
            end = cells[1].strip() or None
            if end == "至今":
                end = None
            managers = [m for m in cells[2].split() if m]
            if not managers or not start:
                continue
            history.append({"start_date": start, "end_date": end, "managers": managers,
                            "tenure_label": cells[3] if len(cells) > 3 else None,
                            "return_pct": cells[4] if len(cells) > 4 else None})
    current = [h for h in history if h["end_date"] is None]
    current_names: list[str] = []
    for h in current:
        for m in h["managers"]:
            if m not in current_names:
                current_names.append(m)
    start_dates = sorted(h["start_date"] for h in current)
    return {
        "provider": "东方财富 / 天天基金 F10",
        "source_url": f"https://fundf10.eastmoney.com/jjjl_{code}.html",
        "retrieved_at": _now(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "current_managers": current_names,
        "manager_start_date": start_dates[0] if start_dates else None,
        "inception": min((h["start_date"] for h in history), default=None),
        "manager_history": history,
        "limitations": ["销售平台披露的任职变动，需与管理人原始披露交叉核对。",
                        "任职起始日期不等同于成立日期；成立日期以基金合同为准。",
                        "换任历史按页面表格解析，可能存在合并或缺失。"],
    }


def fetch_fof_holdings(code: str) -> dict[str, Any]:
    """Latest disclosed underlying-fund holdings for one FOF (基金中基金).

    Uses eastmoney's mobile position API which, unlike the web F10 archive, exposes
    the ``fundfofs`` list (投资的其他基金) together with the report date. Only the
    latest reporting period is returned here; historical periods live in the fund's
    quarterly/annual report PDFs, not in this endpoint.
    """
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("基金代码必须是六位数字。")
    url = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition"
    params = {"FCODE": code, "pageIndex": 1, "pageSize": 100, "deviceid": "finsocratic-local-0001",
              "plat": "Android", "product": "EFund", "version": "6.4.0"}
    raw = _cache_get(f"fof_holdings_{code}.json", ttl_seconds=86400,
                     loader=lambda: _get(url, params=params))
    payload = json.loads(raw.decode("utf-8-sig", errors="replace"))
    datas = payload.get("Datas") or {}
    holdings: list[dict[str, Any]] = []
    for item in datas.get("fundfofs") or []:
        target_code = str(item.get("TZJJDM") or "").strip()
        if not target_code:
            continue
        try:
            weight = float(item.get("ZJZBL") or 0)
        except (TypeError, ValueError):
            weight = float("nan")
        holdings.append({"target_code": target_code,
                         "target_name": str(item.get("TZJJMC") or "").strip(),
                         "weight_pct": weight})
    return {"provider": "东方财富 / 天天基金 移动端",
            "source_url": url,
            "retrieved_at": _now(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "report_date": payload.get("Expansion") or None,
            "holdings": holdings,
            "limitations": ["销售平台披露的底层基金持仓，仅最新一期；跨期历史需核对季度/年度报告原文。",
                            "占净值比例之和可能不等于100%（含直接股票、债券与其他资产）。",
                            "底层基金代码与名称来自销售平台，需与管理人定期报告交叉核对。"]}


def _parse_ymd(value: str) -> date:
    text = str(value).strip().replace("-", "")
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return date.today() - timedelta(days=365 * 8)


def fetch_index_daily(name: str = "沪深300", *, start: str = "20180101") -> pd.DataFrame:
    """Daily close for a benchmark index via Tencent quote (push2his is blocked on this network).

    Tencent's ``fqkline`` endpoint returns ``[date, open, close, high, low, volume]``
    rows; ``close`` (index 2) is used as the NAV. Pagination walks backward in
    2000-bar pages until the requested ``start`` is covered.
    """
    symbol = INDEX_SYMBOL.get(name, name)
    start_date = _parse_ymd(start)
    pages: list[pd.DataFrame] = []
    cursor = date.today()
    while True:
        cache_key = f"index_tencent_{symbol}_{cursor.isoformat()}.json"
        raw = _cache_get(cache_key, ttl_seconds=86400, loader=lambda c=cursor: _get(_TENCENT_KLINE_URL, params={
            "param": f"{symbol},day,1990-01-01,{c.isoformat()},2000,qfq"}))
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        data = payload.get("data")
        days = ((data or {}).get(symbol) or {}).get("day") or []
        if not days:
            break
        rows = [{"date": item[0], "nav": pd.to_numeric(item[2], errors="coerce")} for item in days if len(item) >= 3]
        page = pd.DataFrame(rows).dropna(subset=["nav"]) if rows else pd.DataFrame(columns=["date", "nav"])
        pages.append(page)
        earliest = min(item[0] for item in days)
        if earliest <= start_date.isoformat() or len(days) < 2000:
            break
        cursor = datetime.strptime(earliest, "%Y-%m-%d").date() - timedelta(days=1)
    if not pages:
        return pd.DataFrame(columns=["date", "nav", "source_file"])
    frame = pd.concat(pages, ignore_index=True).drop_duplicates("date", keep="last")
    frame = frame.loc[frame["date"] >= start_date.isoformat()].sort_values("date").reset_index(drop=True)
    frame["source_file"] = f"腾讯行情指数({name})"
    return frame.loc[:, ["date", "nav", "source_file"]]


def _parse_fama_french(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = archive.namelist()[0]
        text = archive.read(name).decode("utf-8", errors="replace")
    data_start = 0
    for index, line in enumerate(text.splitlines()):
        if line.lstrip().startswith(",") and "Mkt" in line:
            data_start = index
            break
    frame = pd.read_csv(io.StringIO(text), skiprows=data_start)
    frame.columns = [col.strip() for col in frame.columns]
    date_col = frame.columns[0]
    frame["date"] = pd.to_datetime(frame[date_col].astype(str).str.strip(), format="%Y%m", errors="coerce")
    for col in frame.columns:
        if col != "date" and col != date_col:
            frame[col] = pd.to_numeric(frame[col], errors="coerce") / 100.0
    return frame.drop(columns=[date_col]).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_fama_french_5f() -> pd.DataFrame:
    raw = _cache_get("fama_french_5f.zip", ttl_seconds=30 * 86400, loader=lambda: _get(FAMA_FRENCH_5F_URL))
    frame = _parse_fama_french(raw)
    return frame.rename(columns={"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RMW": "rmw", "CMA": "cma", "RF": "rf"})


def fetch_fama_french_3f() -> pd.DataFrame:
    raw = _cache_get("fama_french_3f.zip", ttl_seconds=30 * 86400, loader=lambda: _get(FAMA_FRENCH_3F_URL))
    frame = _parse_fama_french(raw)
    return frame.rename(columns={"Mkt-RF": "mkt_rf", "SMB": "smb", "HML": "hml", "RF": "rf"})


def fund_universe(kind: str = "FOF", *, limit: int = 40) -> pd.DataFrame:
    """A manageable universe of real funds (default: FOF) for research imports."""
    frame = search_funds("", kind=kind)
    if frame.empty:
        return frame
    return frame.head(limit).reset_index(drop=True)
