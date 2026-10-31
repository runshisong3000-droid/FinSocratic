"""Content-addressed original uploads stored only in the workspace data drive."""
import hashlib
import json
from .data import DATA_HOME

ROOT=DATA_HOME/'source_archive'

def archive(document,raw,source_url=None):
    ROOT.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(raw).hexdigest()
    (ROOT/(digest+'.bin')).write_bytes(raw)
    metadata={'id':document['id'],'sha256':digest,'name':document['name'],'source_url':source_url}
    (ROOT/(document['id']+'.json')).write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf-8')
    return metadata

def original(document_id):
    if not document_id.startswith('DOC-') or not document_id[4:].isalnum():return None
    index=ROOT/(document_id+'.json')
    if not index.exists():return None
    meta=json.loads(index.read_text(encoding='utf-8'))
    path=ROOT/(meta['sha256']+'.bin')
    return (path,meta) if path.exists() else None
