"""Deterministic tests for the F10 manager-tenure parser (no network)."""
import finsocratic.market_data as md

FIXTURE = """<html><body><table>
<tr><th>起始期</th><th>截止期</th><th>基金经理</th><th>任职期间</th><th>任职回报</th></tr>
<tr><td>2018-03-08</td><td>至今</td><td>夏莹莹 李文良</td><td>8年又237天</td><td>56.16%</td></tr>
<tr><td>2017-11-10</td><td>2018-03-07</td><td>柯晓 夏莹莹</td><td>117天</td><td>0.52%</td></tr>
<tr><td>2017-10-19</td><td>2017-11-09</td><td>柯晓</td><td>21天</td><td>0.20%</td></tr>
<tr><td>基金代码</td><td>基金名称</td><td>基金类型</td><td>起始时间</td></tr>
</table></body></html>"""


def test_parse_manager_history(monkeypatch):
    monkeypatch.setattr(md, "_cache_get", lambda name, ttl_seconds, loader: FIXTURE.encode("utf-8"))
    profile = md.fetch_manager_profile("005215")
    assert profile["current_managers"] == ["夏莹莹", "李文良"]
    assert profile["manager_start_date"] == "2018-03-08"
    assert profile["inception"] == "2017-10-19"
    assert len(profile["manager_history"]) == 3
    assert profile["manager_history"][0]["end_date"] is None  # 现任
    assert profile["manager_history"][-1]["managers"] == ["柯晓"]


def test_parse_empty_manager_history(monkeypatch):
    empty = "<html><body><table></table></body></html>"
    monkeypatch.setattr(md, "_cache_get", lambda name, ttl_seconds, loader: empty.encode("utf-8"))
    profile = md.fetch_manager_profile("005999")
    assert profile["current_managers"] == []
    assert profile["manager_start_date"] is None
    assert profile["inception"] is None
    assert profile["manager_history"] == []
