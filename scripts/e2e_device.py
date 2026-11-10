"""Free private-HTTPS transport check; no microphone, CLI or paid speech calls.

This is not a Safari/render/acoustic test. Profile mutations remain in unit fixtures.
"""
import asyncio,json,sqlite3,time
from pathlib import Path
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1]
BASE='https://plan.tailffc57c.ts.net:18786'

async def main():
    namespace='ephemeral-device-check-'+str(uuid4())
    results=[];timer_id=None
    async with httpx.AsyncClient(trust_env=False,timeout=30) as client:
        for path in ['/device','/device.js','/device-renderer.js','/device-settings.js','/device.css','/manifest.webmanifest','/device-icon-192.png','/device-icon-512.png']:
            response=await client.get(BASE+path);response.raise_for_status()
            assert int(response.headers['content-length'])==len(response.content)
            results.append({'asset':path,'status':response.status_code,'bytes':len(response.content)})
        profile=(await client.get(BASE+'/api/device/profile')).json()
        again=(await client.get(BASE+'/api/device/profile')).json()
        assert profile['profile']['client_id']==again['profile']['client_id']
        assert not profile['capabilities']['physical_device_connected'] and not profile['activation']['configured']
        assert (await client.post(BASE+'/api/device/profile',headers={'Origin':'https://example.invalid'},json={})).status_code==403
        for text,mode in [('Привет, ГоБот!','mock'),('Что такое солнечное затмение?','mock'),('Поставь таймер на 5 минут','auto')]:
            turn=str(uuid4());started=time.perf_counter()
            response=await client.post(BASE+'/api/chat/stream',headers={'Origin':BASE},json={
                'text':text,'mode':mode,'conversation_id':namespace,'turn_id':turn,'request_id':turn,
                'client_kind':'device','remember':False,'speak':False,'usage_consent':False,
                'paid_tts_consent':False})
            response.raise_for_status();events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            assert events[-1]['type']=='final'
            assert not any(e['type']=='audio_chunk' for e in events)
            scenes=[e for e in events if e['type']=='screen_scene'];assert scenes
            assert all(e['turn_id']==turn for e in events)
            frames=[e['data']['presentation'] for e in events if e['type']=='visual_response']
            if mode=='auto':
                assert events[-1]['data']['provider']=='local'
                frame=next(f for f in frames if f['type']=='timer_widget');timer_id=frame['metadata']['timer_id']
                try:
                    timers=(await client.get(BASE+'/api/device/timers')).json()['timers']
                    active=next(t for t in timers if t['id']==timer_id)
                    assert 290<active['deadline']-time.time()<=300
                finally:
                    stopped=await client.post(BASE+'/api/visual/timer/cancel',headers={'Origin':BASE},json={'timer_id':timer_id});stopped.raise_for_status()
                assert not any(t['id']==timer_id for t in (await client.get(BASE+'/api/device/timers')).json()['timers'])
            results.append({'case':text,'diagnostic_mode':mode,'provider':events[-1]['data']['provider'],
                'scene':scenes[-1]['data']['scene']['scene_type'],'frames':len(frames),'ms':round((time.perf_counter()-started)*1000,2)})
    with sqlite3.connect(ROOT/'data/gobot.sqlite') as db:
        saved=db.execute('SELECT count(*) FROM messages WHERE conversation_id=?',(namespace,)).fetchone()[0]
    assert saved==0
    report={'transport':'private Tailscale HTTPS, certificate verified','checks':results,
        'profile_id_survives_fetch':True,'cross_origin_write_rejected':True,'test_timer_cancelled':True,
        'persistent_test_messages':saved,'paid_api_calls':0,'cli_calls':0,'microphone_calls':0,
        'iphone_or_browser_render_verified':False,'wake_word_configured':False}
    (ROOT/'docs/device-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
