"""Reproducible public-data collection, with an on-disk acquisition ledger."""
from __future__ import annotations
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from .data import DATA_HOME
from .market_data import fetch_fund_list, fetch_fund_nav, fund_source_manifest, _get

HUB = DATA_HOME / 'public_research'
LEDGER = HUB / 'acquisition.json'
LOCK = threading.Lock()
CODES = ['005156','005215','005217','005218','005220','005221','005809','005925',
         '005957','005976','005979','006042','006245','006289','006290','006292',
         '006294','006295','006296','006297','006298','006303','006305','006306','006307','006321']
REPORTS = [
    {'id':'nf-2025q2','code':'005215','title':'南方全天候2025年第二季度报告','date':'2025-06-30','kind':'季报','provider':'南方基金官网','url':'https://www.nffund.com/main/files/2025/07/18/448922561903.pdf'},
    {'id':'nf-2025h1','code':'005215','title':'南方全天候2025年中期报告','date':'2025-06-30','kind':'中报','provider':'南方基金官网','url':'https://www.nffund.com/main/files/2025/08/29/741927426632.pdf'},
    {'id':'nf-2024annual','code':'005215','title':'南方全天候2024年年度报告','date':'2024-12-31','kind':'年报','provider':'东方财富披露镜像','url':'https://pdf.dfcfw.com/pdf/H2_AN202503311649423150_1.pdf'},
    {'id':'nf-2025prospectus','code':'005215','title':'南方全天候2025年更新招募说明书','date':'2025-09-22','kind':'招募说明书','provider':'工商银行披露镜像','url':'https://media.icbc.com.cn/fund/report/4805948_fcdb.pdf'},
    {'id':'hx-2025annual','code':'005218','title':'华夏聚惠2025年年度报告','date':'2025-12-31','kind':'年报','provider':'华夏基金官网','url':'https://www.chinaamc.com.cn/upload/resources/file/2026/03/31/6974c4ef82024e3694f3b447ba4891b2.pdf'},
    {'id':'js-2025q2','code':'005156','title':'嘉实领航2025年第二季度报告','date':'2025-06-30','kind':'季报','provider':'巨潮资讯披露','url':'https://static.cninfo.com.cn/finalpage/2025-07-21/1224233620.PDF'},
    {'id':'js-2025h1','code':'005156','title':'嘉实领航2025年中期报告','date':'2025-06-30','kind':'中报','provider':'东方财富披露镜像','url':'https://pdf.dfcfw.com/pdf/H2_AN202508291736331164_1.pdf'},
    {'id':'js-2025q4','code':'005156','title':'嘉实领航2025年第四季度报告','date':'2025-12-31','kind':'季报','provider':'同花顺披露镜像','url':'https://notice.10jqka.com.cn/api/pdf/5a6f2b584012d560.pdf'},
]


def status():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding='utf-8'))
    return {'state':'idle','items':[], 'storage':str(HUB), 'total':len(CODES)+len(REPORTS)}


def _save(data):
    HUB.mkdir(parents=True, exist_ok=True)
    temp = LEDGER.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(LEDGER)


def collect(store):
    if not LOCK.acquire(blocking=False):
        return
    now = lambda: datetime.now(timezone.utc).isoformat()
    ledger = {'state':'running','started_at':now(),'storage':str(HUB),'total':len(CODES)+len(REPORTS),'items':[]}
    try:
        _save(ledger)
        directory = fetch_fund_list().set_index('code')
        directory.to_csv(HUB/'fund_directory.csv',encoding='utf-8-sig')
        def download_nav(code):
            item = directory.loc[code]
            nav = fetch_fund_nav(code)
            if len(nav)<3:
                raise ValueError('有效净值不足三个观测')
            manifest = fund_source_manifest(code)
            folder=HUB/'nav';folder.mkdir(exist_ok=True)
            nav.to_csv(folder/f'{code}.csv',index=False,encoding='utf-8-sig')
            profile={'fund_id':f'CN-{code}','name':item['name'],'manager':f'待核对管理人 · {code}',
                     'strategy':item['type'],'description':manifest['return_basis'],'source_manifest':manifest,
                     'data_origin':'public_market','inception':None}
            old=store.get_fund(profile['fund_id'])
            if old and old.get('profile_disclosure'):
                profile.update({k:old[k] for k in ('manager','inception','profile_disclosure')})
            count=store.save_market_fund(profile,nav)
            return {'id':code,'kind':'净值','name':item['name'],'status':'ready','observations':count,
                    'start':nav.iloc[0]['date'],'end':nav.iloc[-1]['date'],'source_url':manifest['source_url'],
                    'sha256':manifest['sha256'],'retrieved_at':manifest['retrieved_at'],'cache_stale':manifest['cache_stale']}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(download_nav,code):code for code in CODES}
            for future in as_completed(futures):
                code=futures[future]
                try: record=future.result()
                except Exception as error: record={'id':code,'kind':'净值','status':'failed','error':str(error)[:300]}
                ledger['items'].append(record);_save(ledger)
        folder=HUB/'reports';folder.mkdir(exist_ok=True)
        for report in REPORTS:
            try:
                path=folder/f"{report['id']}.pdf"
                raw=path.read_bytes() if path.exists() else _get(report['url'])
                if not raw.startswith(b'%PDF') or len(raw)>40_000_000:
                    raise ValueError('无效PDF或文件超过40MB')
                if not path.exists():path.write_bytes(raw)
                doc=store.add_document(f"CN-{report['code']}",report['title']+'.pdf',raw,period='reference')
                record={**report,'status':'ready','bytes':len(raw),'pages':len(doc['chunks']),'document_id':doc['id'],
                        'sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()}
                path.with_suffix('.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as error:record={**report,'status':'failed','error':str(error)[:300]}
            ledger['items'].append(record);_save(ledger)
        ledger['state']='complete';ledger['finished_at']=now()
    except Exception as error:
        ledger.update(state='failed',error=str(error)[:300])
    finally:
        _save(ledger);LOCK.release()


def original_path(document_id):
    record=next((r for r in status()['items'] if r.get('document_id')==document_id and r.get('status')=='ready'),None)
    if record is None:return None
    path=HUB/'reports'/f"{record['id']}.pdf"
    return path if path.is_file() else None
