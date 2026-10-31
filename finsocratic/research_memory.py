"""Version evidence independently of model wording or retrieval order."""
import hashlib
import json
from .storage import json_safe


def digest(value):
    return hashlib.sha256(json.dumps(json_safe(value),ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def snapshot(store, fund_id):
    from .learning import status
    nav=store.nav_frame(fund_id)
    holdings=store.fof_holdings_frame(fund_id)
    docs=store.list_documents(fund_id)
    report=status().get('report',{})
    profile=store.get_fund(fund_id) or {}
    return {'净值': {'hash':digest(nav.to_dict('records')), 'rows':len(nav),
                     'end':str(nav.date.max())[:10] if len(nav) else None},
            '底层持仓': {'hash':digest(holdings.to_dict('records')),'rows':len(holdings)},
            '原始材料': {'hash':digest(sorted((d['id'],d.get('sha256','')) for d in docs)),
                         'rows':len(docs),'documents':[{'id':d['id'],'name':d['name']} for d in docs]},
            '基金档案': {'hash':digest(profile),'name':profile.get('name')},
            '学习模型': {'hash':digest(report),'run_id':report.get('run_id')}}


def compare(previous, current):
    if not previous:
        return {'status':'baseline','summary':'建立首次证据基线；历史回答不作为新增证据。','changes':[]}
    changes=[{'category':key,'before':previous.get(key),'after':value}
             for key,value in current.items() if previous.get(key,{}).get('hash')!=value.get('hash')]
    return {'status':'changed' if changes else 'unchanged',
            'summary':f'{len(changes)} 类输入发生变化；需区分数据更新与模型版本变化。' if changes else '输入证据未变化；本轮仅是重新解释，不得声称获得新证据。',
            'changes':changes}
