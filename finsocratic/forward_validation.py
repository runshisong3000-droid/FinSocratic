"""Pre-outcome frozen forecast cohorts. No backdating, no retrospective enrollment."""
import hashlib
import json
import sqlite3
import io
from contextlib import contextmanager
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import joblib
import numpy as np
import pandas as pd
from .data import DATA_HOME
from .learning import HOME, status, features, FEATURES

ROOT=DATA_HOME/'forward_validation'
LOCK=threading.Lock()

@contextmanager
def connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(ROOT/'ledger.sqlite3',timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS cohorts (month TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def freeze(store):
    with LOCK, connect() as c:
        c.execute("BEGIN IMMEDIATE")
        return _freeze(store, c)

def _freeze(store, c):
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    month=pd.Period(now.strftime('%Y-%m'),freq='M')+1
    # One cohort per target month. Retraining cannot overwrite the registered challenger.
    if c.execute('SELECT 1 FROM cohorts WHERE month=?',(str(month),)).fetchone():
        return {'status':'already_frozen','month':str(month)}
    report=status().get('report')
    if not report:raise ValueError('请先完成模型训练。')
    source=HOME/report['run_id']
    raw=(source/'model.joblib').read_bytes()
    sha=hashlib.sha256(raw).hexdigest()
    model=joblib.load(io.BytesIO(raw))
    cards=json.loads((source/'cards.json').read_text(encoding='utf-8'))['cards']
    nav=store.nav_frame(); nav=nav[nav.date<=pd.Timestamp(now.date())]
    rows=[]; skipped=len(set(cards)-set(nav.fund_id))
    for fid,g in nav[nav.fund_id.isin(cards)].groupby('fund_id'):
        f=features(g)
        if f.empty: skipped+=1;continue
        latest=f.sort_values('date').tail(1)
        date=latest.iloc[0].date
        if date.to_period('M')!=month-1 or (pd.Timestamp(now.date())-date).days>7:
            skipped+=1;continue
        x=model['scaler'].transform(latest[FEATURES])
        rows.append({'fund_id':fid,'as_of':date.date().isoformat(),
                     'features':latest[FEATURES].iloc[0].to_dict(),
                     'neural':float(max(model['model'].predict(x)[0],0)),
                     'ridge':float(max(model['ridge'].predict(x)[0],0)),
                     'persistence':float(latest.iloc[0].vol21)})
    if not rows:raise ValueError('没有本月足够新鲜的特征，不能冻结下一月预测。请先更新净值。')
    folder=ROOT/str(month);folder.mkdir(exist_ok=True)
    (folder/'model.joblib').write_bytes(raw)
    payload={'month':str(month),'registered_at':now.isoformat(),'run_id':report['run_id'],
             'model_sha256':sha,'predictions':rows,'skipped':skipped,
             'protocol':'目标月开始前冻结；每月只注册一个版本；全部合格样本纳入，不按误差筛选。目标为自然月日收益标准差×sqrt(252)。至少15个收益、月末端点不超过7天；缺数据单列，不填造。至少3个成熟月份后观察稳定性，不作统计显著性声明。'}
    c.execute('INSERT INTO cohorts VALUES (?,?)',(str(month),json.dumps(payload,ensure_ascii=False)))
    (folder/'registration.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'status':'frozen','month':str(month),'count':len(rows),'skipped':skipped}

def evaluate(store):
    now=pd.Timestamp(datetime.now(ZoneInfo('Asia/Shanghai')).date())
    with connect() as c: cohorts=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM cohorts ORDER BY month')]
    nav=None;out=[]
    for cohort in cohorts:
        month=pd.Period(cohort['month'],freq='M'); rows=cohort['predictions']
        item={k:v for k,v in cohort.items() if k!='predictions'}
        item.update(registered=len(rows),evaluated=0,missing=len(rows),state='awaiting_outcome',mae=None)
        if now>month.end_time.normalize():
            if nav is None:nav=store.nav_frame()
            errors=[]
            for r in rows:
                g=nav[nav.fund_id==r['fund_id']].sort_values('date').set_index('date')
                ret=g.nav.pct_change(fill_method=None)
                ret[g.index.to_series().diff().dt.days>10]=np.nan
                period=ret[(ret.index>=month.start_time)&(ret.index<=month.end_time)].dropna()
                if len(period)<15 or (month.end_time.normalize()-period.index.max()).days>7:continue
                actual=float(period.std()*np.sqrt(252)*100)
                errors.append({k:abs(r[k]-actual) for k in ('neural','ridge','persistence')})
            item.update(evaluated=len(errors),missing=len(rows)-len(errors),state='evaluated' if errors else 'missing_data')
            if errors:item['mae']={k:float(np.mean([e[k] for e in errors])) for k in errors[0]}
        out.append(item)
    return {'cohorts':out,'mature_months':sum(r['state']=='evaluated' for r in out),
            'boundary':'注册不可通过应用覆盖；本地文件并非外部公证。评估使用当前入库净值，数据修订可能改变成绩。月份尚未结束绝不计算验证成绩。'}
