from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finsocratic.data_hub import collect,status
from finsocratic.storage import WorkspaceStore
collect(WorkspaceStore())
result=status()
print(result['state'],len([i for i in result['items'] if i['status']=='ready']), 'ready')
for item in result['items']:
    if item['status']=='failed':print(item['id'],item['error'])
