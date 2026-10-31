"""Backfill latest disclosed underlying-fund holdings for already-imported FOF funds.

Fetches each FOF's eastmoney mobile position list (``fundfofs``) and stores the
rows in ``fof_holdings`` plus a summary in the fund profile. Best-effort: a failed
fetch leaves the fund untouched and is counted, never wiping existing data. Only
the latest reporting period is available from this endpoint; historical periods
require the fund's quarterly/annual report PDFs.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from finsocratic.market_data import fetch_fof_holdings
from finsocratic.storage import WorkspaceStore


def _code(fund_id: str) -> str:
    return fund_id.split("-")[-1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 只，0 表示全部")
    parser.add_argument("--only", type=str, default="", help="逗号分隔的基金代码，仅处理这些")
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
            mp = fetch_fof_holdings(code)
        except Exception as exc:  # noqa: BLE001
            return fid, "failed", str(exc)[:120]
        holdings = mp.get("holdings") or []
        if not holdings:
            return fid, "skipped", "无底层基金持仓披露"
        store.upsert_fof_holdings(
            [{"fund_id": fid, "target_code": h["target_code"], "target_name": h["target_name"],
              "weight_pct": h["weight_pct"], "report_date": mp["report_date"]} for h in holdings],
            source_file=f"eastmoney_fof_{code}.json")
        store.update_fund_details(fid, {
            "fof_holdings_count": len(holdings),
            "fof_holdings_report_date": mp.get("report_date"),
            "fof_holdings_weight_sum": round(sum(h["weight_pct"] for h in holdings), 2),
            "fof_holdings_source_manifest": {"source_url": mp["source_url"],
                                             "sha256": mp["sha256"],
                                             "retrieved_at": mp["retrieved_at"]},
        })
        return fid, "updated", f"{len(holdings)} 只 @ {mp['report_date']}"

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
