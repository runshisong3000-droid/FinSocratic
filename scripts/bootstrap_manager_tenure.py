"""Backfill manager tenure (任职区间) for already-imported workspace funds.

Fetches each fund's eastmoney F10 manager history and merges ``manager``,
``inception``, ``manager_start_date``, ``manager_history`` and
``current_managers`` into the stored profile. Best-effort: a failed fetch leaves
the fund untouched and is counted, never wiping existing data.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from finsocratic.market_data import fetch_manager_profile
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
    funds = [f for f in store.list_funds() if not f.get("is_sample") and str(f["fund_id"]).startswith("CN-")]
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
            mp = fetch_manager_profile(code)
        except Exception as exc:  # noqa: BLE001
            return fid, "failed", str(exc)[:120]
        if not mp.get("current_managers"):
            return fid, "skipped", "无现任经理数据"
        store.update_fund_details(fid, {
            "manager": " ".join(mp["current_managers"]),
            "inception": mp.get("inception"),
            "manager_start_date": mp.get("manager_start_date"),
            "manager_history": mp.get("manager_history"),
            "current_managers": mp.get("current_managers"),
            "manager_source_manifest": {"source_url": mp["source_url"],
                                        "sha256": mp["sha256"],
                                        "retrieved_at": mp["retrieved_at"]},
        })
        return fid, "updated", f"{', '.join(mp['current_managers'])} @ {mp['manager_start_date']}"

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

    print(f"\n完成：更新 {updated}，跳过 {skipped}，失败 {failed}，共 {len(funds)} 只。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
