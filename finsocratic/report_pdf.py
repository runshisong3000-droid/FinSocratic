"""FOF 定期报告（季报/年报）PDF 的抓取与底层基金持仓表格解析。

东财 ``FundArchivesDatas.aspx`` 归档里没有 FOF 底层基金持仓的历史数据；跨期
底层持仓只能来自基金季度/年度报告。本模块负责：按公告接口定位定期报告 -> 解析
PDF 附件地址 -> 绕过 pdf.dfcfw.com 的反爬 -> 用 pdfplumber 抽取"基金投资明细"表。
"""
from __future__ import annotations

import io
import json
import re
from datetime import date
from typing import Any

import pdfplumber
import requests

from .market_data import _cache_get, _now

_FUND_REPORTS_URL = "https://api.fund.eastmoney.com/f10/JJGG"
_ANNOUNCE_URL = "https://np-cnotice-fund.eastmoney.com/api/content/ann"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "http://fundf10.eastmoney.com/"}

# pdf.dfcfw.com 反爬 JS 挑战固定写入的 cookie（值由混淆脚本硬编码而来，不随报告变化）。
_BOT_COOKIES = {"__tst_status": "1778596283#", "EO_Bot_Ssid": "3355574272"}

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _json_get(url: str, params: dict[str, Any]) -> bytes:
    """带 Referer 的 GET，返回 bytes；东财公告接口不带 Referer 会返回 ErrCode:-999。"""
    resp = requests.get(url, params=params, headers=_HEADERS, timeout=40)
    resp.raise_for_status()
    return resp.content


def _period_from_title(title: str) -> str | None:
    m = re.search(r"(\d{4})年第([1-4])季度报告", title or "")
    if m:
        y, q = int(m.group(1)), int(m.group(2))
        month, day = _QUARTER_END[q]
        return date(y, month, day).isoformat()
    m = re.search(r"(\d{4})年年度报告", title or "")
    if m:
        return f"{m.group(1)}-12-31"
    m = re.search(r"(\d{4})年(?:中期|半年度)报告", title or "")
    if m:
        return f"{m.group(1)}-06-30"
    return None


def fetch_report_list(code: str) -> list[dict[str, Any]]:
    """返回某只基金最近的定期报告列表（含报告期与公告 ID）。"""
    code = str(code).strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("基金代码必须是六位数字。")
    raw = _cache_get(f"reports_{code}.json", ttl_seconds=86400,
                     loader=lambda: _json_get(_FUND_REPORTS_URL,
                                              params={"fundcode": code, "pageIndex": 1, "pageSize": 20, "type": 3}))
    data = json.loads(raw.decode("utf-8-sig", errors="replace"))
    reports: list[dict[str, Any]] = []
    for item in data.get("Data") or []:
        title = item.get("TITLE") or ""
        reports.append({"art_code": item.get("ID"),
                        "title": title,
                        "short_title": item.get("ShortTitle"),
                        "publish_date": item.get("PUBLISHDATEDesc"),
                        "report_period": _period_from_title(title)})
    return reports


def fetch_report_pdf_url(art_code: str) -> str:
    """解析公告的 PDF 附件地址（attach_url）。"""
    raw = _cache_get(f"ann_{art_code}.json", ttl_seconds=86400,
                     loader=lambda: _json_get(_ANNOUNCE_URL,
                                              params={"art_code": art_code, "client_source": "web"}))
    data = (json.loads(raw.decode("utf-8-sig", errors="replace")).get("data") or {})
    url = data.get("attach_url") or data.get("attach_url_web")
    if not url:
        raise ValueError("公告未提供 PDF 附件地址。")
    return str(url)


def download_report_pdf(url: str) -> bytes:
    """下载报告 PDF；若遇反爬 JS 挑战，写入硬编码 cookie 后重试一次。"""
    session = requests.Session()
    resp = session.get(url, headers=_HEADERS, timeout=40)
    if resp.content.startswith(b"%PDF"):
        return resp.content
    for key, value in _BOT_COOKIES.items():
        session.cookies.set(key, value, domain="pdf.dfcfw.com")
    resp = session.get(url, headers=_HEADERS, timeout=40)
    if not resp.content.startswith(b"%PDF") or len(resp.content) < 10_000:
        raise ValueError("报告 PDF 下载被反爬拦截，未取得有效文件。")
    return resp.content


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _table_kind(table: list[list[str | None]]) -> str | None:
    """识别一张 pdfplumber 表格属于报告的哪一类明细表。

    返回 "fof"（基金投资明细）、"stock"（股票投资明细）、"bond"（债券投资明细）、
    "total"（合计行）、None（续页/无表头，需结合上下文状态判断）。
    """
    joined = "".join(_clean(c) for row in table for c in row)
    if "股票代码" in joined or "股票名称" in joined:
        return "stock"
    if "债券代码" in joined or "债券名称" in joined:
        return "bond"
    if "基金代码" in joined or "基金名称" in joined:
        return "fof"
    if "合计" in joined or "总计" in joined:
        return "total"
    return None


def _parse_rows(rows: list[list[str | None]]) -> list[dict[str, Any]]:
    """把 pdfplumber 表格行规整为 {target_code, target_name, weight_pct}，并合并跨页续行。"""
    holdings: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        cells = [_clean(c) for c in row]
        if not cells:
            continue
        joined = "".join(cells)
        if "基金代码" in joined or "基金名称" in joined or "占基金资产净值" in joined:
            continue  # 表头行
        if "合计" in joined or "总计" in joined:
            continue  # 合计/小计行，避免污染最后一条持仓
        seq = cells[0]
        if re.fullmatch(r"\d{1,2}", seq) and len(cells) > 6:
            code = cells[1]
            if re.fullmatch(r"\d{6}", code):
                current = {"target_code": code, "target_name": cells[2], "weight_pct": cells[6]}
                holdings.append(current)
                continue
        if current is not None and seq == "":
            # 序号列因分页丢失但代码列完整：按新持仓处理，而非当作名称续行。
            if len(cells) > 6 and re.fullmatch(r"\d{6}", cells[1]):
                current = {"target_code": cells[1], "target_name": cells[2], "weight_pct": cells[6]}
                holdings.append(current)
                continue
            if len(cells) > 2 and cells[2]:
                current["target_name"] += cells[2]
            if len(cells) > 6 and cells[6]:
                current["weight_pct"] += cells[6]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in holdings:
        if h["target_code"] in seen:
            continue
        seen.add(h["target_code"])
        try:
            weight = float(h["weight_pct"])
        except (TypeError, ValueError):
            continue
        result.append({"target_code": h["target_code"], "target_name": h["target_name"],
                       "weight_pct": weight})
    return result


def parse_fund_holdings(pdf_bytes: bytes, *, report_period: str | None = None) -> dict[str, Any]:
    """解析报告 PDF 的底层基金投资明细（前十名 + 期末持有的其他基金/REIT）。

    返回 {report_period, holdings:[{target_code,target_name,weight_pct}], limitations}。
    """
    if not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("不是有效的 PDF 文件。")
    rows: list[list[str | None]] = []
    active = False  # 是否正处于"基金投资明细"表内（续页无表头，需跨页保持状态）
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                kind = _table_kind(table)
                if kind == "fof":
                    active = True
                elif kind in ("stock", "bond", "total"):
                    active = False
                if active:
                    rows.extend(table)
    holdings = _parse_rows(rows)
    return {"provider": "东方财富 定期报告 PDF",
            "retrieved_at": _now(),
            "report_period": report_period,
            "holdings": holdings,
            "limitations": ["抽取自报告 §6 基金投资明细；前十名之外的持仓披露口径因基金而异，需与报告原文核对。",
                            "跨页拆分的单元格已按名称/比例列拼接，极端格式下可能漏并，需抽样人工复核。",
                            "报告 PDF 由公告接口定位，东财反爬规则变化时需更新 cookie 策略。"]}


def fetch_report_holdings(code: str, *, max_reports: int = 4) -> list[dict[str, Any]]:
    """抓取某只基金最近若干期报告的底层基金持仓（跨期）。"""
    reports = fetch_report_list(code)[:max_reports]
    results: list[dict[str, Any]] = []
    for report in reports:
        if not report.get("report_period"):
            continue
        try:
            url = fetch_report_pdf_url(report["art_code"])
            pdf_bytes = download_report_pdf(url)
            parsed = parse_fund_holdings(pdf_bytes, report_period=report["report_period"])
        except Exception as exc:  # noqa: BLE001
            results.append({"report_period": report["report_period"], "error": str(exc)[:120],
                            "source_url": None, "holdings": []})
            continue
        parsed["source_url"] = url
        parsed["title"] = report["title"]
        parsed["sha256"] = _sha256(pdf_bytes)
        results.append(parsed)
    return results


def verify_holdings_caliber(report_holdings: list[dict[str, Any]],
                            platform_holdings: list[dict[str, Any]],
                            tolerance: float = 0.05) -> dict[str, Any]:
    """核验报告 PDF 持仓与平台持仓的口径是否一致。

    按底层基金代码对齐，比较占净值比例。返回 {matched, report_only, platform_only,
    max_abs_diff, within_tolerance}。
    """
    report = {h["target_code"]: h["weight_pct"] for h in report_holdings}
    platform = {h["target_code"]: h["weight_pct"] for h in platform_holdings}
    common = sorted(set(report) & set(platform))
    max_diff = 0.0
    for code in common:
        diff = abs(report[code] - platform[code])
        max_diff = max(max_diff, diff)
    return {"matched": len(common),
            "report_only": sorted(set(report) - set(platform)),
            "platform_only": sorted(set(platform) - set(report)),
            "max_abs_diff": round(max_diff, 4),
            "within_tolerance": max_diff <= tolerance}


def _sha256(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()
