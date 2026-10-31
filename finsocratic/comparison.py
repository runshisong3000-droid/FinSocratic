"""Comparable fund research using identical observed dates, without interpolation."""
from __future__ import annotations

from typing import Any
import pandas as pd
from .data import fund_metrics


def compare_funds(funds: list[dict[str, Any]], start: str | None = None, end: str | None = None) -> dict[str, Any]:
    if len(funds) < 2:
        raise ValueError("请选择至少两只基金进行同区间比较。")
    if len(funds) > 8:
        raise ValueError("单次最多比较八只基金。")
    if len({bool(f.get('is_sample')) for f in funds}) > 1:
        raise ValueError("合成演示与非演示基金不能放在同一次比较中。")
    lower = pd.Timestamp(start) if start else None
    upper = pd.Timestamp(end) if end else None
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("开始日期不能晚于结束日期。")
    tracks = {}
    common = None
    for fund in funds:
        frame = pd.DataFrame(fund.get('nav', []))
        if frame.empty:
            raise ValueError(f"{fund['name']}没有净值数据。")
        frame['date'] = pd.to_datetime(frame['date'], errors='coerce')
        frame['nav'] = pd.to_numeric(frame['nav'], errors='coerce')
        frame = frame.dropna(subset=['date', 'nav']).loc[lambda x: x.nav > 0]
        if lower is not None:
            frame = frame.loc[frame.date >= lower]
        if upper is not None:
            frame = frame.loc[frame.date <= upper]
        frame = frame.sort_values('date').drop_duplicates('date', keep='last')
        tracks[fund['fund_id']] = frame
        dates = set(frame.date)
        common = dates if common is None else common & dates
    dates = sorted(common or [])
    if len(dates) < 3:
        raise ValueError("共同观测日期少于三个，无法可靠比较；请调整基金或日期范围。不会插值补齐。")
    rows, chart = [], {date: {'date':date.date().isoformat()} for date in dates}
    for fund in funds:
        frame = tracks[fund['fund_id']].loc[lambda x: x.date.isin(dates)].copy()
        frame['fund_id'] = fund['fund_id']
        metrics = fund_metrics(frame, fund['fund_id'])
        rows.append({'fund_id':fund['fund_id'], 'name':fund['name'], 'manager':fund['manager'],
                     'metrics':metrics, 'sources':sorted(set(frame.get('source_file', pd.Series(['导入净值'])).astype(str))),
                     'excluded_observations':len(tracks[fund['fund_id']])-len(frame)})
        first = float(frame.nav.iloc[0])
        for point in frame.itertuples():
            chart[point.date][fund['fund_id']] = float(point.nav) / first * 100
    return {'start':dates[0].date().isoformat(), 'end':dates[-1].date().isoformat(),
            'requested_start':start, 'requested_end':end, 'observations':len(dates), 'funds':rows,
            'chart':list(chart.values()), 'is_sample':bool(funds[0].get('is_sample')),
            'method':'仅使用所有基金共同存在的观测日期，首点归一为100；不前向填充、不插值。',
            'limits':['统一采样可能遗漏更高频率下的回撤；风险统计仅描述共同观测样本。',
                      '费率、估值时点和复权口径仍需核对。比较结果不是投资推荐。']}


def fund_brief(fund: dict[str, Any], tasks: list[dict], runs: list[dict]) -> str:
    m = fund.get('metrics', {})
    def pct(key):
        v = m.get(key)
        return '—' if v is None else f'{v:.2%}'
    lines = [f"# {fund['name']}｜研究档案", '',
             f"基金编号：{fund['fund_id']} · 管理人档案：{fund['manager']}",
             f"数据属性：{'合成演示' if fund.get('is_sample') else '公开或用户导入数据'}", '',
             '## 研究范围', '', f"{m.get('start','—')} 至 {m.get('end','—')} · {m.get('months',0)} 个观测 · {m.get('frequency','—')}", '',
             '| 指标 | 计算结果 |', '|---|---:|']
    for label,key in [('区间收益','total_return'),('年化收益','annual_return'),('年化波动','volatility'),('最大回撤','max_drawdown'),('单期95%历史VaR','var_95'),('单期95%尾部均值','cvar_95')]:
        lines.append(f'| {label} | {pct(key)} |')
    source = fund.get('source_manifest') or {}
    lines += ['', '## 来源与口径', '', source.get('return_basis','由导入净值计算，复权与费用口径需核对。')]
    if source:
        lines += [f"- [来源原文]({source['source_url']})", f"- 抓取时间：{source.get('retrieved_at')}", f"- SHA-256：`{source.get('sha256')}`"]
    lines += ['', '## 已收集材料', '']
    for doc in fund.get('reports',[]):
        lines.append(f"- {doc['name']} · {doc.get('period','reference')} · 编号 {doc['id']}")
    if not fund.get('reports'):
        lines.append('尚未取得管理人材料，不能由净值推断经理行为。')
    lines += ['', '## 跟进事项', '']
    relevant = [t for t in tasks if t.get('fund_id') == fund['fund_id']]
    for task in relevant:
        lines.append(f"- [{task['status']}] {task['question']}" + (f"；处理记录：{task['resolution_note']}" if task.get('resolution_note') else ''))
    if not relevant:
        lines.append('尚未运行材料审计；需核对经理任期、合同基准、底层持仓与完整费用。')
    lines += ['', '## 已保存审计', '']
    for run in runs:
        if run.get('fund_id') == fund['fund_id']:
            lines.append(f"- {run['id']} · {run.get('created_at','')} · {run.get('claim_count',0)} 项陈述")
    lines += ['', '历史统计不代表未来表现；本档案是研究过程记录，不构成投资建议。']
    return '\n'.join(lines)+'\n'
