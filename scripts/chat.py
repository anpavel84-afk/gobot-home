import json,sys
from pathlib import Path
import httpx
r=Path(__file__).resolve().parents[1];keys=json.loads((r/'run/keys.json').read_text())
with httpx.Client(trust_env=False,timeout=30) as client:
    with client.stream('POST','http://127.0.0.1:18781/api/v1/chat/stream',headers={'Authorization':'Bearer '+keys['api_token']},json={'text':' '.join(sys.argv[1:]) or 'Привет, GoBot!','provider':'mock'}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('data: '):
                obj=json.loads(line[6:])
                if obj['type']=='text_delta':print(obj['data']['text'],end='',flush=True)
                elif obj['type']=='final':print('\n[mock; provider='+obj['data']['provider']+']')
