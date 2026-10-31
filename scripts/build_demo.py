"""Regenerate the explicitly synthetic classroom deliverables."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finsocratic.agent import render_markdown, run_diligence
from finsocratic.data import load_samples
from finsocratic.library import extract_document


def main() -> None:
    funds, nav, holdings = load_samples()
    nav["source_file"] = "nav_monthly.csv（合成演示）"
    holdings["source_file"] = "holdings.csv（合成演示）"
    benchmark = pd.read_csv(ROOT / "data" / "sample" / "benchmark_monthly.csv", parse_dates=["date"])
    benchmark["source_file"] = "benchmark_monthly.csv（合成演示）"
    note_path = ROOT / "data" / "sample" / "manager_reports" / "FOF-001_2025Q4.txt"
    document = {"name": "FOF-001_2025Q4.txt（合成演示）",
                "chunks": extract_document(note_path.name, note_path.read_bytes())}
    fund = funds.loc[funds["fund_id"] == "FOF-001"].iloc[0]
    prior_path = note_path.parent / "FOF-001_2025Q2.txt"
    prior = {"name": prior_path.name, "chunks": extract_document(prior_path.name, prior_path.read_bytes())}
    result = run_diligence(fund, nav, holdings, [document], benchmark=benchmark, prior_documents=[prior])
    output = ROOT / "deliverables"
    output.mkdir(exist_ok=True)
    (output / "FOF-001_合成演示_尽调简报.md").write_text(render_markdown(result), encoding="utf-8")
    (output / "FOF-001_合成演示_证据台账.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Generated synthetic demo: {len(result['claims'])} claims, {len(result['evidence'])} evidence records")


if __name__ == "__main__":
    main()
