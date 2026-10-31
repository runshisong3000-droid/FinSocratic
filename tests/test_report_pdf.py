"""Deterministic tests for report-PDF parsing helpers (no network / no PDF)."""
import finsocratic.report_pdf as rp

ROWS = [
    # 表头
    ["序号", "基金代 码", "基金名 称", "运作方 式", "持有份 额 （份）",
     "公允价 值 （元）", "占基金 资产净 值比例 （%）", "是否属 于基金 管理人 及管理 人关联 方所管 理的基 金"],
    # 数据行
    ["1", "012220", "南方安 泰混合 C", "契约型 开放式", "101,424, 406.22", "119,214, 247.07", "4.34", "是"],
    ["2", "011034", "南方宝 恒混合 C", "契约型 开放式", "83,073,5 53.04", "100,618, 687.44", "3.67", "是"],
    # 跨页续行
    ["6", "007415", "南方致", "契约型", "40,669,0", "63,581,9", "2.32", "是"],
    ["", "", "远混合 A", "开放式", "52.45", "96.60", "", ""],
    # 合计 / 费用表（不应被误并入）
    ["2", "3,931,421.00", "24,088,222.41", "0.88"],
    ["项目", "本期费用", "其中：交易及持有基金管理人产生费用"],
]


def test_parse_rows_basic_and_continuation():
    result = rp._parse_rows(ROWS)
    assert len(result) == 3
    by_code = {h["target_code"]: h for h in result}
    assert by_code["012220"]["target_name"] == "南方安泰混合C"
    assert by_code["012220"]["weight_pct"] == 4.34
    assert by_code["007415"]["target_name"] == "南方致远混合A"
    assert by_code["007415"]["weight_pct"] == 2.32


def test_parse_rows_ignores_total_and_fee():
    result = rp._parse_rows(ROWS)
    names = "".join(h["target_name"] for h in result)
    assert "24,088,222.41" not in names
    assert "本期费用" not in names


def test_period_from_title():
    assert rp._period_from_title("南方全天候策略混合型基金中基金(FOF)2026年第3季度报告") == "2026-09-30"
    assert rp._period_from_title("xx2025年第1季度报告") == "2025-03-31"
    assert rp._period_from_title("xx2025年年度报告") == "2025-12-31"
    assert rp._period_from_title("xx2026年中期报告") == "2026-06-30"
    assert rp._period_from_title("无定期报告") is None
