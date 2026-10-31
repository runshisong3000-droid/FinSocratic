"""Bulk-import the full public FOF universe into the local workbench.

Unlike ``collect_public_data.py`` (a small curated case), this pulls every
public FOF (or a filtered subset) with enough NAV history and imports it into
SQLite. Run from the project root with ``py -3.11``.

Examples:
    py -3.11 scripts/bootstrap_all_fof.py --type FOF-进取型 --limit 60
    py -3.11 scripts/bootstrap_all_fof.py --min-obs 120 --limit 200
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finsocratic.market_data import fetch_fund_list, fetch_fund_nav, fund_source_manifest  # noqa: E402
from finsocratic.storage import WorkspaceStore  # noqa: E402
from finsocratic.data import DATA_HOME


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-import public FOF funds.")
    parser.add_argument("--type", default="FOF", help="基金类型筛选（如 FOF-进取型 / FOF-均衡型 / FOF-稳健型 / FOF）")
    parser.add_argument("--limit", type=int, default=0, help="最多导入数量（0 表示不限制）")
    parser.add_argument("--min-obs", type=int, default=60, help="最少有效净值观测，用于过滤新基金")
    parser.add_argument("--workers", type=int, default=4, help="并发下载线程数")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="跳过工作区已存在且有足够净值的基金")
    args = parser.parse_args()

    store = WorkspaceStore()
    frame = fetch_fund_list()
    mask = frame["type"].str.contains(args.type, na=False)
    candidates = frame.loc[mask].reset_index(drop=True)
    print(f"目录中匹配「{args.type}」的基金：{len(candidates)} 只")

    if args.limit:
        candidates = candidates.head(args.limit)
        print(f"本次最多导入前 {len(candidates)} 只")

    downloaded = 0
    skipped = 0
    failed = 0

    def import_one(code: str) -> str:
        nonlocal downloaded, skipped, failed
        profile_id = f"CN-{code}"
        existing = store.get_fund(profile_id)
        if args.skip_existing and existing:
            nav_frame = store.nav_frame(profile_id)
            if len(nav_frame) >= args.min_obs:
                skipped += 1
                return "skip"
        item = candidates.loc[candidates["code"] == code].iloc[0]
        nav = fetch_fund_nav(code)
        if len(nav) < args.min_obs:
            failed += 1
            return f"skip-short({len(nav)})"
        manifest = fund_source_manifest(code)
        profile = {
            "fund_id": profile_id, "name": item["name"],
            "manager": f"待核对管理人 · {code}", "strategy": item["type"],
            "description": manifest["return_basis"], "source_manifest": manifest,
            "data_origin": "public_market", "inception": None,
        }
        if existing and existing.get("profile_disclosure"):
            profile.update({k: existing[k] for k in ("manager", "inception", "profile_disclosure")})
        store.save_market_fund(profile, nav)
        downloaded += 1
        return "ok"

    codes = candidates["code"].tolist()
    ledger = {'started_at': datetime.now(timezone.utc).isoformat(), 'total': len(codes), 'items': [], 'state': 'running'}
    ledger_path = DATA_HOME / 'public_research' / 'universe_acquisition.json'
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    def save_ledger():
        temp = ledger_path.with_suffix('.tmp')
        temp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(ledger_path)
    save_ledger()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(import_one, code): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                outcome = future.result()
            except Exception as error:  # noqa: BLE001
                outcome = f"error:{str(error)[:120]}"
                failed += 1
            if outcome not in ("skip", "ok"):
                print(f"  {code}: {outcome}")
            ledger['items'].append({'code': code, 'outcome': outcome})
            if len(ledger['items']) % 25 == 0:
                save_ledger()
                print(f"progress {len(ledger['items'])}/{len(codes)}", flush=True)

    ledger.update(state='complete', finished_at=datetime.now(timezone.utc).isoformat())
    save_ledger()

    print(f"\n完成：新导入 {downloaded} 只，跳过（已存在/观测不足） {skipped} 只，失败 {failed} 只")
    print(f"工作区基金总数：{len(store.list_funds())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
