"""Backfill cross-period underlying-fund holdings from FOF quarterly/annual report PDFs.

For each imported FOF, locates the latest N periodic reports (eastmoney announcement
API), downloads the PDF (with the pdf.dfcfw.com anti-bot cookie), extracts the
"基金投资明细" table, and stores the rows in ``fof_holdings`` keyed by report period.
This fills the cross-period gap that the platform's latest-only mobile API cannot.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from finsocratic.report_pdf import fetch_report_holdings
from finsocratic.storage import WorkspaceStore


def _code(fund_id: str) -> str:
    return fund_id.split("-")[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--periods", type=int, default=2, help="每只基金回溯的定期报告期数")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", type=str, default="", help="逗号分隔的基金代码")
    args = parser.parse_args()

    store = WorkspaceStore()
    funds = [f for f in store.list_funds()
             if not f.get("is_sample") and str(f["fund_id"]).startswith("CN-")
             and "FOF" in str(f["strategy"]).upper()]
    if args.only:
        codes = {c.strip() for c in args.only.split(",") if c.strip()}
        funds = [f for f in funds if _code(f["fund_id"]) in codes]
    if args.limit:
        funds = funds[: args.limit]

    updated = skipped = failed = 0

    def worker(fund):
        fid = fund["fund_id"]
        code = _code(fid)
        try:
            results = fetch_report_holdings(code, max_reports=args.periods)
        except Exception as exc:  # noqa: BLE001
            return fid, "failed", str(exc)[:120]
        stored = 0
        for r in results:
            if r.get("error") or not r.get("holdings"):
                continue
            period = r["report_period"]
            store.upsert_fof_holdings(
                [{"fund_id": fid, "target_code": h["target_code"], "target_name": h["target_name"],
                  "weight_pct": h["weight_pct"], "report_date": period} for h in r["holdings"]],
                source_file=f"eastmoney_report_{code}_{period}.pdf")
            stored += 1
        if not stored:
            return fid, "skipped", "报告无可抽取持仓"
        frame = store.fof_holdings_frame(fid)
        periods = sorted(set(frame["report_date"].dt.strftime("%Y-%m-%d"))) if not frame.empty else []
        store.update_fund_details(fid, {"fof_holdings_period_count": len(periods),
                                        "fof_holdings_report_periods": periods})
        return fid, "updated", f"{stored} 期报告（累计 {len(periods)} 期）"

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, f) for f in funds]
        for future in as_completed(futures):
            fid, status, detail = future.result()
            if status == "updated":
                updated += 1
            elif status == "failed":
                failed += 1
            else:
                skipped += 1
            print(f"{status:8s} {fid}  {detail}")

    print(f"\n完成：更新 {updated}，跳过 {skipped}，失败 {failed}，共 {len(funds)} 只 FOF。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
