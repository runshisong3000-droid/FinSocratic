"""Offline end-to-end acceptance checks for the teaching workflow."""
from pathlib import Path
import os
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finsocratic.analysis import fund_research_report, portfolio_metrics
from finsocratic.data import fund_metrics, load_samples, normalize_nav
from finsocratic.library import extract_document, retrieve


def main() -> None:
    funds, nav, holdings = load_samples()
    assert len(funds) == 3 and len(nav) > 0 and len(holdings) > 0
    report = fund_research_report(funds.iloc[0], nav, holdings)
    for required in ("区间收益", "最大回撤", "组合快照", "权益策略"):
        assert required in report, required
    metrics = portfolio_metrics(holdings, "FOF-001")
    assert abs(metrics["reported_weight_sum"] - 100) < 1e-9
    previous = holdings.loc[holdings["fund_id"] == "FOF-001"].copy()
    previous["as_of"] = pd.Timestamp("2024-12-31")
    previous["weight_pct"] = previous["weight_pct"] / 2
    latest = portfolio_metrics(pd.concat([previous, holdings], ignore_index=True), "FOF-001")
    assert latest["as_of"] == "2025-12-31" and latest["asset_count"] == metrics["asset_count"]
    invalid = holdings.copy()
    invalid.loc[invalid["fund_id"] == "FOF-001", "weight_pct"] = -1
    assert not portfolio_metrics(invalid, "FOF-001")["available"]
    annual = fund_metrics(pd.DataFrame({"fund_id": [1, 1], "date": pd.to_datetime(["2024-01-01", "2025-01-01"]), "nav": [1.0, 1.1]}), "1")
    assert abs(annual["annual_return"] - 0.1) < 0.001
    frame = nav.rename(columns={"date": "日期", "nav": "净值"})[["日期", "净值"]]
    frame.loc[len(frame)] = [frame.iloc[0, 0], -1]
    normalized, warnings = normalize_nav(frame, "日期", "净值", "FOF-001")
    assert (normalized["nav"] > 0).all() and warnings
    chunks = extract_document("note.txt", "最大回撤需要结合净值频率复核。\n组合权重合计为100%。".encode("utf-8"))
    hits = retrieve("最大回撤", [{"name": "note.txt", "chunks": chunks}], limit=2)
    assert hits and hits[0]["location"] == "第 1 行"
    print("acceptance ok: report, latest portfolio, invalid weights, annualization, normalization, library retrieval")


if __name__ == "__main__":
    main()
