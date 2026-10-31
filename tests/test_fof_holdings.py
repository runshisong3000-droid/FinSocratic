"""Deterministic tests for the FOF underlying-holdings parser (no network)."""
import json

import finsocratic.market_data as md

FIXTURE = json.dumps({
    "Datas": {"fundfofs": [
        {"TZJJDM": "012220", "TZJJMC": "南方安泰混合C", "ZJZBL": "4.34", "RZDF": "-0.02"},
        {"TZJJDM": "011034", "TZJJMC": "南方宝恒混合C", "ZJZBL": "3.67", "RZDF": "-0.04"},
    ]},
    "Expansion": "2026-09-30",
    "Success": True,
    "TotalCount": 1,
}).encode("utf-8")


def test_parse_fof_holdings(monkeypatch):
    monkeypatch.setattr(md, "_cache_get", lambda name, ttl_seconds, loader: FIXTURE)
    profile = md.fetch_fof_holdings("005215")
    assert profile["report_date"] == "2026-09-30"
    assert len(profile["holdings"]) == 2
    assert profile["holdings"][0]["target_code"] == "012220"
    assert profile["holdings"][0]["target_name"] == "南方安泰混合C"
    assert profile["holdings"][0]["weight_pct"] == 4.34
    assert abs(sum(h["weight_pct"] for h in profile["holdings"]) - 8.01) < 1e-9


def test_parse_empty_fof_holdings(monkeypatch):
    empty = json.dumps({"Datas": {"fundfofs": []}, "Expansion": "2026-09-30", "Success": True}).encode("utf-8")
    monkeypatch.setattr(md, "_cache_get", lambda name, ttl_seconds, loader: empty)
    profile = md.fetch_fof_holdings("005999")
    assert profile["holdings"] == []
    assert profile["report_date"] == "2026-09-30"
