"""Reproduce the public FOF research case and export a bounded research memo."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finsocratic.api import MarketImport, market_import, import_public_disclosure, store


def main():
    receipt = market_import(MarketImport(code="005215"))
    disclosure = import_public_disclosure(MarketImport(code="005215"))
    workspace = store.workspace()
    fund = next(item for item in workspace["funds"] if item["fund_id"] == receipt["fund_id"])
    metrics = fund["metrics"]
    def pct(key):
        value = metrics.get(key)
        return "不可计算" if value is None else f"{value:.2%}"
    lines = ["# 南方全天候策略 FOF A｜公开数据研究备忘录", "",
             "本记录由确定性研究工具生成；区分公开披露、计算结果和证据缺口，不给出投资评级。", "",
             "## 研究对象与来源", "",
             f"- 基金代码：005215；资料档案：{fund['manager']}。",
             f"- 净值研究窗口：{metrics['start']} 至 {metrics['end']}，{receipt['imported']} 个观测。",
             f"- [原始季报]({disclosure['source_url']})：2025Q2 历史披露；不代表最新合同或任职信息。",
             f"- [净值数据]({receipt['manifest']['source_url']})：来源报告的日涨跌幅连乘指数；首日归一为1。",
             f"- 抓取时间：{receipt['manifest']['retrieved_at']}。", "",
             "## 历史风险与收益", "", "| 指标 | 样本计算 |", "|---|---:|",
             f"| 区间收益 | {pct('total_return')} |", f"| 年化收益 | {pct('annual_return')} |",
             f"| 年化波动 | {pct('volatility')} |", f"| 最大回撤 | {pct('max_drawdown')} |",
             f"| 单期95%历史VaR | {pct('var_95')} |", f"| 单期95%尾部均值 | {pct('cvar_95')} |", "",
             "以上统计来自同一条来源收益曲线；来源复权与费用处理尚未独立调节。历史VaR不构成未来损失上界。", "",
             "## 回撤事件", "", "| 峰值日期 | 谷值日期 | 回撤深度 | 恢复日期 |", "|---|---|---:|---|"]
    for event in fund["analytics"]["nav_diagnostics"]["drawdown_episodes"][:5]:
        lines.append(f"| {event['peak_date']} | {event['trough_date']} | {event['depth']:.2%} | {event['recovery_date'] or '截至样本末未恢复'} |")
    lines += ["", "## 下一步尽调任务", "",
              "1. 与管理人披露的分红、拆分、净值增长率核对来源收益曲线。",
              "2. 按合同取得完整混合基准；未取得前不使用单一股票指数替代并声称超额收益。",
              "3. 将报告中的基金投资明细人工复核为两期结构化持仓，再分析同一资产的配置变化。",
              "4. 核实基金经理任期、策略决策权、费用及底层基金关联关系；名称不能替代事实档案。",
              "5. 对报告涉及的期间单独取样；PDF表格抽取结果需核对原始页后再作数值审计。", "",
              "## 数据指纹", "", f"- 净值原文 SHA-256：`{receipt['manifest']['sha256']}`",
              f"- 原始季报 SHA-256：`{disclosure['sha256']}`", "",
              "本备忘录为研究过程记录，不构成投资建议。"]
    output = ROOT / "deliverables" / "005215_公开FOF研究备忘录.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Public case ready: {receipt['imported']} observations, {disclosure['chunks_count']} PDF pages")


if __name__ == "__main__":
    main()
