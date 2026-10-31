"""Bridge imported PDF holdings into the research agent without assuming completeness."""
def underlying_evidence(store, fund_id):
    frame = store.fof_holdings_frame(fund_id)
    if frame.empty:
        return {'status': 'missing', 'boundary': '没有已入库的底层基金持仓，不代表没有投资。'}
    dates = sorted(frame.report_date.unique())[-2:]
    snapshots = []
    for date in dates:
        g = frame[frame.report_date == date]
        snapshots.append({'date': str(date)[:10], 'rows': len(g),
                          'disclosed_weight_pct': float(g.weight_pct.sum()),
                          'sources': sorted(set(g.source_file)),
                          'holdings': g[['target_code','target_name','weight_pct','source_row']].to_dict('records')})
    changes = []
    if len(dates) == 2:
        a = frame[frame.report_date == dates[0]].set_index('target_code')
        b = frame[frame.report_date == dates[1]].set_index('target_code')
        if a.index.is_unique and b.index.is_unique:
            for code in a.index.intersection(b.index):
                changes.append({'code': code, 'name': b.loc[code,'target_name'],
                                'weight_change_pp': float(b.loc[code,'weight_pct']-a.loc[code,'weight_pct'])})
    return {'status': 'available', 'snapshots': snapshots,
            'matched_changes': sorted(changes,key=lambda r: abs(r['weight_change_pp']),reverse=True)[:15],
            'boundary': '仅比较两期均披露的同代码持仓；未出现不视作清仓。季报与中报披露范围可能不同，合计不等于总仓位，变化不等于交易或收益贡献。'}
