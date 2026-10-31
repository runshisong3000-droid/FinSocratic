"""Auditable, local learning from real FOF histories; never a manager-skill label."""
from __future__ import annotations
import hashlib
import json
import re
import threading
import uuid
import warnings
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from scipy.stats import t
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error
from .data import DATA_HOME
from .storage import json_safe

HOME = DATA_HOME / 'learning'
LOCK = threading.Lock()
FEATURES = ['vol21', 'vol63', 'return21', 'return63', 'drawdown63', 'downside63']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(json_safe(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def status():
    path = HOME / 'status.json'
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'state': 'idle'}
    pointer = HOME / 'latest.json'
    if pointer.exists():
        run = json.loads(pointer.read_text(encoding='utf-8'))['run_id']
        state['report'] = json.loads((HOME / run / 'report.json').read_text(encoding='utf-8'))
    return state


def family(name):
    # Conservative name-based share class grouping; not legal product identifiers.
    return re.sub(r'[A-ZＡ-Ｚ]+$', '', re.sub(r'\s+', '', name)).strip()


def posterior(values, strength=4):
    """NIG prior: mu0=0, kappa=strength, alpha=2, beta=.02^2 (quarterly)."""
    x = np.asarray(values, dtype=float)
    n = len(x); mean = float(x.mean()) if n else 0.
    k = strength + n; a = 2 + n / 2
    b = .02**2 + .5 * float(((x - mean)**2).sum()) + strength*n*mean**2/(2*k)
    mu = n*mean/k; scale = np.sqrt(b/(a*k))
    lo, hi = t.ppf([.025, .975], 2*a, loc=mu, scale=scale)
    return {'quarters': n, 'mean_quarterly_excess': mu, 'credible_interval_95': [lo, hi],
            'probability_positive_mean': float(t.sf(0, 2*a, loc=mu, scale=scale)), 'prior_strength': strength}


def attribution_diagnostics(matched, excess):
    """Researcher-style robustness card for one product's relative-return claim."""
    x = np.asarray(excess, dtype=float)
    if len(x) == 0:
        return {'status': 'insufficient_data'}
    positive = float((x > 0).mean())
    blocks = [x[i:i+4] for i in range(0, len(x), 4) if len(x[i:i+4]) >= 3]
    block_means = [float(b.mean()) for b in blocks]
    last = x[-min(8, len(x)):]
    # A claim is stronger when it survives time slicing and the recent window.
    signs = {'all': float(x.mean()), 'first_half': float(x[:max(1,len(x)//2)].mean()),
             'second_half': float(x[len(x)//2:].mean()), 'recent_8q': float(last.mean())}
    stable = sum(v > 0 for v in block_means) / len(block_means) if block_means else None
    return {'status': 'available', 'positive_quarter_share': positive,
            'rolling_4q_mean': block_means, 'positive_4q_block_share': stable,
            'period_means': signs, 'best_quarter': float(x.max()), 'worst_quarter': float(x.min()),
            'worst_quarter_date': matched.iloc[int(x.argmin())].date,
            'peer_count_range': [int(matched['count'].min()), int(matched['count'].max())],
            'interpretation': ('持续性较弱：正收益主要集中在少数季度，需优先核对风格暴露或幸存者偏差。'
                               if stable is not None and stable < .5 else
                               '存在时间分段证据，但仍需任职区间、持仓和风险因子控制。')}


def robustness_matrix(matched):
    """Compare peer definitions and bootstrap the sign of the relative-return claim."""
    if len(matched) < 8:
        return {'status': 'insufficient_data'}
    out = {}
    for label in ('median', 'mean', 'trimmed_mean'):
        if label not in matched:
            continue
        x = (matched['return'] - matched[label]).to_numpy(dtype=float)
        rng = np.random.default_rng(42)
        boot = rng.choice(x, size=(2000,len(x)), replace=True).mean(axis=1)
        out[label] = {'quarters': len(x), 'mean_excess': float(x.mean()),
                      'positive_share': float((x > 0).mean()),
                      'bootstrap_ci_95': [float(np.quantile(boot,.025)), float(np.quantile(boot,.975))],
                      'bootstrap_positive_mean': float((boot > 0).mean())}
    # Leave one period out: a robust claim should not depend on one exceptional quarter.
    x = (matched['return'] - matched['median']).to_numpy(dtype=float)
    loo = np.array([(np.delete(x, i)).mean() for i in range(len(x))])
    return {'status': 'available', 'benchmarks': out,
            'leave_one_quarter_out_range': [float(loo.min()), float(loo.max())],
            'benchmark_agreement': len({round(v['mean_excess'], 4) > 0 for v in out.values()}) == 1,
            'interpretation': ('结论对同类基准定义较稳健，但仍不是风险调整后的因果归因。'
                               if len(out) >= 2 and len({round(v['mean_excess'], 4) > 0 for v in out.values()}) == 1
                               else '结论依赖同类基准定义或个别季度，不能直接归因于经理能力。')}


def research_readiness(profile, nav, matched, bayes, passed_model):
    """Separate evidence readiness from performance; missing evidence lowers readiness."""
    checks = []
    obs = len(nav)
    span = (nav.date.max() - nav.date.min()).days if obs else 0
    checks.append({'key': 'history', 'label': '历史净值跨度', 'ready': obs >= 252 and span >= 365,
                   'detail': f'{obs} 条观测，跨度 {span} 天'})
    checks.append({'key': 'peer', 'label': '同类可比样本', 'ready': bayes is not None and len(matched) >= 8,
                   'detail': f'{len(matched)} 个共同季度'})
    checks.append({'key': 'stability', 'label': '时间分段可计算', 'ready': bool(bayes and bayes.get('diagnostics')),
                   'detail': '可以分段检查；可计算不代表表现稳定' if bayes else '季度样本不足'})
    manifest = profile.get('source_manifest') or {}
    checks.append({'key': 'provenance', 'label': '净值来源可追溯', 'ready': bool(manifest.get('source_url') and manifest.get('sha256')),
                   'detail': '已记录来源链接与哈希' if manifest.get('source_url') else '缺少来源清单'})
    manager_start = profile.get('manager_start_date')
    inception = profile.get('inception')
    if manager_start and inception:
        tenure_detail = f"现任经理 {profile.get('manager', '未注明')}（{manager_start} 起），成立 {inception}"
    elif manager_start or inception:
        tenure_detail = '仅有成立或任职日期之一，任职区间不完整'
    else:
        tenure_detail = '尚未拿到经理任职披露'
    checks.append({'key': 'tenure', 'label': '经理任职来源', 'ready': bool(manager_start and profile.get('manager_tenure_source')),
                   'detail': tenure_detail})
    fof_count = profile.get('fof_holdings_count')
    if fof_count:
        fof_detail = (f"底层基金 {fof_count} 只（{profile.get('fof_holdings_report_date', '日期未知')} 披露，"
                      f"占净值合计 {profile.get('fof_holdings_weight_sum', '未注明')}%）")
    else:
        fof_detail = '尚未形成跨期底层持仓证据'
    checks.append({'key': 'holdings', 'label': '跨期持仓完整性核验', 'ready': bool(profile.get('holdings_completeness_verified')),
                   'detail': fof_detail})
    checks.append({'key': 'model', 'label': '风险模型时间外验证', 'ready': bool(passed_model),
                   'detail': '神经网络同时优于两条基线' if passed_model else '当前网络未同时优于两条基线'})
    ready = sum(c['ready'] for c in checks)
    if ready >= 6: grade = 'A·可进入深度复核'
    elif ready >= 4: grade = 'B·证据可用但需补强'
    else: grade = 'C·只能形成研究假设'
    robust = bayes.get('robustness', {}) if bayes else {}
    diag = bayes.get('diagnostics', {}) if bayes else {}
    ci_low = (bayes.get('credible_interval_95') or [1])[0] if bayes else 1
    if bayes and ci_low > 0 and robust.get('benchmark_agreement'):
        verdict = '模型假设下相对收益区间为正；经理因果归因仍待任职、持仓和风险调整核验'
    elif bayes and robust.get('benchmark_agreement') and diag.get('positive_4q_block_share', 0) >= .5:
        verdict = '点估计方向一致；区间与近期表现仍需审阅，不能证明经理能力'
    else:
        verdict = '只能形成待验证研究假设'
    return {'grade': grade, 'verdict': verdict, 'ready_count': ready, 'total': len(checks), 'checks': checks,
            'next_best_evidence': [c['label'] for c in checks if not c['ready']][:3]}


def panel(store):
    funds = [f for f in store.list_funds() if not f['is_sample'] and 'FOF' in f['strategy']]
    profiles = {f['fund_id']: f for f in funds}
    raw = store.nav_frame()
    raw = raw[raw.fund_id.isin(profiles)].copy()
    # Exclude incomplete calendar month and invalid observations, never forward fill.
    cutoff = pd.Timestamp.today().normalize().replace(day=1)
    raw = raw[(raw.date < cutoff) & (raw.nav > 0)].sort_values(['fund_id', 'date'])
    counts = raw.groupby('fund_id').size().to_dict()
    representatives = {}
    for f in sorted(funds, key=lambda f: (-counts.get(f['fund_id'], 0), f['fund_id'])):
        representatives.setdefault(family(f['name']), f['fund_id'])
    ids = set(representatives.values())
    selected = raw[raw.fund_id.isin(ids)]
    aliases = {f['fund_id']: representatives[family(f['name'])] for f in funds}
    return profiles, raw, selected, aliases


def features(nav):
    g = nav.set_index('date').sort_index()
    r = g.nav.pct_change(fill_method=None)
    # Long observation gaps do not become artificial one-day returns.
    r[g.index.to_series().diff().dt.days > 10] = np.nan
    f = pd.DataFrame(index=g.index)
    f['vol21'] = r.rolling(21, min_periods=18).std()*np.sqrt(252)*100
    f['vol63'] = r.rolling(63, min_periods=55).std()*np.sqrt(252)*100
    f['return21'] = g.nav.pct_change(21, fill_method=None)*100
    f['return63'] = g.nav.pct_change(63, fill_method=None)*100
    f['drawdown63'] = (g.nav/g.nav.rolling(63).max()-1)*100
    f['downside63'] = r.clip(upper=0).pow(2).rolling(63, min_periods=55).mean().pow(.5)*np.sqrt(252)*100
    f['date'] = g.index
    f['month'] = g.index.to_period('M')
    last = f.groupby('month').tail(1).set_index('month')
    # Reject stale month endpoints; keep actual observation date.
    last = last[(last.index.to_timestamp(how='end').normalize()-last.date).dt.days <= 7]
    monthly = r.groupby(r.index.to_period('M')).agg(['std', 'count'])
    monthly['target'] = monthly['std']*np.sqrt(252)*100
    monthly.loc[monthly['count'] < 15, 'target'] = np.nan
    last['target'] = [monthly['target'].get(m+1, np.nan) for m in last.index]
    last['target_date'] = [(m+1).end_time.normalize() for m in last.index]
    return last.dropna(subset=FEATURES).reset_index(drop=True)


def train(store):
    if not LOCK.acquire(blocking=False):
        return
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    folder = HOME / run_id
    def progress(stage):
        write(HOME/'status.json', {'state': 'running', 'run_id': run_id, 'stage': stage})
    try:
        progress('建立真实净值快照，合并重复份额')
        profiles, raw, nav, aliases = panel(store)
        folder.mkdir(parents=True, exist_ok=True)
        nav.to_csv(folder/'nav_snapshot.csv.gz', index=False, compression='gzip')
        digest = hashlib.sha256(pd.util.hash_pandas_object(nav, index=False).values.tobytes()).hexdigest()
        write(folder/'sources.json', [{'fund_id': fid, 'name': profiles[fid]['name'], 'strategy': profiles[fid]['strategy'],
                                      'source': profiles[fid].get('source_manifest')} for fid in sorted(set(nav.fund_id))])
        frames = []; quarterly = []
        for fid, g in nav.groupby('fund_id'):
            frame = features(g); frame['fund_id'] = fid; frames.append(frame)
            indexed = g.set_index('date')
            q = indexed.nav.resample('QE').last()
            endpoint = indexed.index.to_series().resample('QE').last()
            q[(q.index.to_series()-endpoint).dt.days > 7] = np.nan
            q[indexed.nav.resample('QE').count() < 40] = np.nan
            # Complete quarters only, no interpolation across missing quarters.
            q = q[q.index < pd.Timestamp.today().to_period('Q').start_time]
            qr = q.pct_change(fill_method=None).dropna()
            for d, value in qr.items():
                quarterly.append({'date': d, 'fund_id': fid, 'strategy': profiles[fid]['strategy'], 'return': value})
        data = pd.concat(frames, ignore_index=True)
        labeled = data.dropna(subset=['target']).copy()
        dates = sorted(labeled.target_date.unique())
        if len(dates) < 30 or len(labeled) < 500:
            raise ValueError('训练需要至少30个月、500条有效基金月样本。')
        train_end, val_end = dates[int(len(dates)*.6)-1], dates[int(len(dates)*.8)-1]
        tr = labeled[labeled.target_date <= train_end]
        va = labeled[(labeled.target_date > train_end) & (labeled.target_date <= val_end)]
        te = labeled[labeled.target_date > val_end]
        scaler = StandardScaler().fit(tr[FEATURES])
        x = scaler.transform(tr[FEATURES]); y = tr.target.to_numpy()
        progress('训练两层神经网络；按目标月份分离训练、验证与测试')
        from .neural_risk import fit_risk_ensemble
        net, optimization = fit_risk_ensemble(x, y, scaler.transform(va[FEATURES]), va.target.to_numpy(), scaler)
        fit_warnings = []
        ridge = Ridge(alpha=10).fit(x, y)
        def predictions(frame, model):
            return np.maximum(model.predict(scaler.transform(frame[FEATURES])), 0)
        def scores(frame):
            return {'neural_mae': mean_absolute_error(frame.target, predictions(frame, net)),
                    'ridge_mae': mean_absolute_error(frame.target, predictions(frame, ridge)),
                    'persistence_mae': mean_absolute_error(frame.target, frame.vol21)}
        validation, test = scores(va), scores(te)
        eligible = validation['neural_mae'] < min(validation['ridge_mae'], validation['persistence_mae'])
        # A held-out failure remains visible; it is not tuned away.
        passed = eligible and test['neural_mae'] < min(test['ridge_mae'], test['persistence_mae'])
        joblib.dump({'model': net, 'scaler': scaler, 'ridge': ridge, 'features': FEATURES}, folder/'model.joblib')
        labeled.to_csv(folder/'training_samples.csv.gz', index=False, compression='gzip')
        holdout = te[['fund_id', 'date', 'target_date', 'target', 'vol21']].copy()
        holdout['neural_prediction'] = predictions(te, net)
        holdout['ridge_prediction'] = predictions(te, ridge)
        holdout.to_csv(folder/'holdout_predictions.csv', index=False)
        progress('更新贝叶斯后验、先验敏感性与每只基金研究卡')
        qdata = pd.DataFrame(quarterly)
        cards = {}
        for fid, g in data.groupby('fund_id'):
            recent = g.sort_values('date').iloc[[-1]]
            own = qdata[qdata.fund_id == fid]
            peers = qdata[(qdata.fund_id != fid) & (qdata.strategy == profiles[fid]['strategy'])]
            peer = peers.groupby('date')['return'].agg(['median', 'mean', 'count'])
            peer['trimmed_mean'] = peers.groupby('date')['return'].apply(
                lambda s: s.sort_values().iloc[max(0, int(len(s)*.1)):max(1, int(len(s)*.9))].mean())
            matched = own.merge(peer, left_on='date', right_index=True).reset_index(drop=True)
            matched = matched[matched['count'] >= 5].sort_values('date')
            excess = (matched['return']-matched['median']).to_numpy()
            bayes = None
            if len(excess) >= 8:
                bayes = {**posterior(excess), 'sensitivity': [posterior(excess, k) for k in (1, 12)],
                         'recent_12_quarters': posterior(excess[-12:]),
                         'start': matched.date.min(), 'end': matched.date.max(),
                         'minimum_peer_count': int(matched['count'].min()),
                         'diagnostics': attribution_diagnostics(matched, excess),
                         'robustness': robustness_matrix(matched),
                         'updates': [{'date': matched.iloc[i-1].date, **posterior(excess[:i])} for i in range(1, len(excess)+1)]}
            readiness = research_readiness(profiles[fid], nav[nav.fund_id == fid], matched, bayes, passed)
            cards[fid] = {'fund_id': fid, 'name': profiles[fid]['name'], 'bayesian': bayes,
                          'neural': {'as_of': recent.iloc[0].date, 'forecast_month_end': recent.iloc[0].target_date,
                                     'predicted_annualized_vol_pct': float(predictions(recent, net)[0]),
                                     'persistence_vol_pct': float(recent.iloc[0].vol21),
                                     'status': 'research_signal' if passed else 'experimental_not_validated'},
                          'bayesian_status': 'available' if bayes else '不足8个季度或不足5个同类产品',
                          'research_readiness': readiness}
        report = {'run_id': run_id, 'created_at': datetime.now(timezone.utc).isoformat(),
                  'source_fund_share_classes': raw.fund_id.nunique(), 'independent_name_groups': nav.fund_id.nunique(),
                  'nav_observations': len(nav), 'training_samples': len(labeled), 'snapshot_sha256': digest,
                  'data_start': nav.date.min(), 'data_end': nav.date.max(), 'features': FEATURES,
                  'architecture': '3-seed MLP 6 → 32 → 16 → 1; chronological early stopping + validation blend',
                  'optimization': optimization,
                  'target': '下一完整自然月日收益标准差 × √252，单位：年化百分点',
                  'split': {'train_end': pd.Timestamp(train_end), 'validation_end': pd.Timestamp(val_end),
                            'test_end': pd.Timestamp(dates[-1]), 'train_rows': len(tr), 'validation_rows': len(va), 'test_rows': len(te)},
                  'validation': validation, 'test': test, 'neural_passed_baselines': bool(passed),
                  'iterations': sum(m['best_epoch'] for m in optimization['members']), 'loss_curve': net.loss_curve_,
                  'training_warnings': [str(w.message) for w in fit_warnings],
                  'bayesian_covered': sum(c['bayesian'] is not None for c in cards.values()),
                  'limitations': ['历史测试期此前已被审阅，本次为历史回测，非全新独立验证；候选选择只使用验证集。', '估计基金相对同类表现，不是经理个人能力；未对齐任职区间或风险因子。',
                    '贝叶斯采用季度收益差的独立正态假设；序列相关、厚尾可能使区间偏窄。先验中心0、季度尺度2%、强度4，提供1/12敏感性。',
                    '按当前目录和名称合并份额，存在存续偏差、历史类别变化与漏合并风险；同类中位数不是可投资基准。',
                    '神经网络为小型监督风险模型，未微调大语言模型；时间外结果不是未来业绩保证。',
                    '第三方收益指数复权尚未逐条对账；拒绝缺失窗口，不补造观测。'],
                  'storage': str(folder)}
        write(folder/'cards.json', {'cards': cards, 'aliases': aliases})
        write(folder/'report.json', report)
        write(HOME/'latest.json', {'run_id': run_id})
        write(HOME/'status.json', {'state': 'complete', 'run_id': run_id, 'stage': '训练及时间外评估已完成'})
    except Exception as error:
        write(HOME/'status.json', {'state': 'failed', 'run_id': run_id, 'error': str(error)[:300]})
        raise
    finally:
        LOCK.release()


def fund_evidence(fund_id):
    info = status(); report = info.get('report')
    if not report:
        return {'status': 'not_trained', 'message': '尚无已完成训练，请先运行本地学习。'}
    saved = json.loads((HOME/report['run_id']/'cards.json').read_text(encoding='utf-8'))
    representative = saved['aliases'].get(fund_id, fund_id)
    card = saved['cards'].get(representative)
    if not card:
        return {'status': 'insufficient_data', 'message': '该基金不在本次有效训练样本中。'}
    # Retire legacy heuristic grades without silently rewriting archived experiments.
    card=dict(card)
    old=card.get('research_readiness',{})
    card['research_readiness']={**old,'grade':'待逐项核验','verdict':'统计模型描述相对表现；任职与完整持仓需独立证据。',
        'checks':[c for c in old.get('checks',[]) if c['key'] in ('history','peer','provenance')],
        'total':3,'ready_count':sum(c['ready'] for c in old.get('checks',[]) if c['key'] in ('history','peer','provenance')),
        'next_best_evidence':['经理任职原始披露','跨期持仓完整性核验','风险调整与替代解释']}
    if card.get('bayesian',{}):
        rob=card['bayesian'].get('robustness',{})
        if rob.get('benchmarks'):
            crosses=any(v['bootstrap_ci_95'][0]<=0<=v['bootstrap_ci_95'][1] for v in rob['benchmarks'].values())
            rob['interpretation']='点估计方向比较不等于显著优势；至少一个区间跨零，证据仍不确定。' if crosses else '重采样区间未跨零；仍依赖样本和独立同分布假设，不代表经理因果能力。'
    return {'status': 'ready', 'requested_fund_id': fund_id, 'representative_fund_id': representative,
            'run_id': report['run_id'], 'card': card, 'test': report['test'],
            'neural_passed_baselines': report['neural_passed_baselines'], 'limitations': report['limitations']}
