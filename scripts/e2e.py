"""Free loopback text + signed Bridge + XiaoZhi fixture-device E2E."""
import asyncio,json,sys,time,statistics,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
import httpx,websockets
from gobot.protocol import pack_opus,unpack_opus
from gobot.ui import MockUIRenderer
keys=json.loads((ROOT/'run/keys.json').read_text());headers={'Authorization':'Bearer '+keys['api_token']}
async def text(client,route='fast'):
    start=time.perf_counter();first=None;events=[]
    async with client.stream('POST','http://127.0.0.1:18781/api/v1/chat/stream',headers=headers,json={'text':'Привет, GoBot','provider':'mock','route':route,'device_id':'e2e','conversation_id':'benchmark-'+str(uuid.uuid4())}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith('data: '):
                obj=json.loads(line[6:]);events.append(obj)
                if obj['type']=='text_delta' and first is None:first=(time.perf_counter()-start)*1000
    assert events[-1]['type']=='final'
    assert ''.join(e['data']['text'] for e in events if e['type']=='text_delta').strip()==events[-1]['data']['text']
    if route=='agent':assert events[-1]['data']['provider']=='bridge:mock' and len(events[-1]['data']['trace'])==1
    return {'llm_first_delta_mock_ms':first,'text_e2e_mock_ms':(time.perf_counter()-start)*1000}
async def device(version=1,abort=False,disconnect=False):
    headers={'Authorization':'Bearer '+keys['device_token'],'Device-Id':'mock-device','Client-Id':'fixture','Protocol-Version':str(version)}
    async with websockets.connect('ws://127.0.0.1:18783/xiaozhi/v1/',additional_headers=headers,open_timeout=2) as ws:
        await ws.send(json.dumps({'type':'hello','version':version,'transport':'websocket','audio_params':{'format':'opus','sample_rate':24000,'channels':1,'frame_duration':20}}));hello=json.loads(await asyncio.wait_for(ws.recv(),3));assert hello['type']=='hello'
        await ws.send(json.dumps({'type':'listen','state':'start','mode':'manual'}));await ws.send(pack_opus(b'\xf8\xff\xfe',version));await ws.send(json.dumps({'type':'listen','state':'stop'}))
        if disconnect:return {'disconnected':True}
        events=[];audio=0;renderer=MockUIRenderer();abort_sent=False
        while True:
            message=await asyncio.wait_for(ws.recv(),5)
            if isinstance(message,bytes):unpack_opus(message,version);audio+=1;continue
            obj=json.loads(message);events.append(obj)
            if obj['type']=='custom':renderer.enqueue(obj)
            if abort and obj.get('state')=='start' and not abort_sent:await ws.send(json.dumps({'type':'abort'}));abort_sent=True
            if obj['type']=='tts' and obj.get('state')=='stop':break
        if abort:assert abort_sent
        else:
            assert [e['text'] for e in events if e.get('state')=='sentence_start']==['Таймер на пять минут подготовлен.','Команда показана в mock-интерфейсе.']
            assert audio==2 and renderer.gui_tick()['timer.start']['duration_ms']==300000
        return {'version':version,'audio_fixture_frames':audio,'abort':abort,'mock':True,'actual_playback_measured':False}
async def main():
    records=[]
    async with httpx.AsyncClient(trust_env=False,timeout=20) as client:
        for port in [18781,18782,18784]:assert (await client.get(f'http://127.0.0.1:{port}/healthz')).status_code==200
        assert (await client.get('http://127.0.0.1:18781/api/v1/status')).status_code==401
        import io
        from PIL import Image
        image=io.BytesIO();Image.new('RGB',(240,240),'navy').save(image,format='JPEG');data=image.getvalue()
        minted=await client.post('http://127.0.0.1:18784/api/v1/images',headers={**headers,'Content-Type':'image/jpeg'},content=data)
        minted.raise_for_status();download=await client.get(minted.json()['url'])
        assert download.content==data and download.headers['content-type']=='image/jpeg' and int(download.headers['content-length'])==len(data)
        for _ in range(20):records.append(await text(client))
        await text(client,'agent')
    try:
        async with websockets.connect('ws://127.0.0.1:18783/xiaozhi/v1/',additional_headers={'Device-Id':'mock-device','Authorization':'Bearer invalid'}) as ws:await ws.recv()
        raise AssertionError('Bad device accepted')
    except websockets.exceptions.ConnectionClosedError as e:assert e.code==1008
    devices=[await device(v) for v in [1,2,3]]
    await device(1,abort=True);await device(1,disconnect=True);await device(1)
    metrics={}
    for key in records[0]:
        values=sorted(r[key] for r in records);metrics[key]={'p50':statistics.median(values),'p95':values[int(.95*(len(values)-1))],'n':len(values)}
    result={'mode':'mock-only','metrics':metrics,'devices':devices,'passed':['health','authenticated JPEG HTTP delivery','authenticated SSE','SQLite persistence','signed host bridge','hello','device auth rejection','v1/v2/v3 fixture framing','listen','tts order','timer UI queue','abort','lost connection','reconnect'],'unmeasured':['VAD','STT real speech','TTS first real chunk','first physical Opus playback','actual upstream interoperability']}
    (ROOT/'docs/e2e-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
