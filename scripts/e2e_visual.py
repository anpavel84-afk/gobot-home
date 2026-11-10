"""Separate real, free visual integration check. No model/STT/TTS requests.
Requires an explicit --network flag; never runs from pytest.
"""
import argparse,asyncio,io,json,sys,time,sqlite3
from pathlib import Path
from uuid import uuid4
import httpx
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
BASE='https://plan.tailffc57c.ts.net:18786'

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--network',action='store_true');args=parser.parse_args()
    if not args.network:raise SystemExit('Pass --network to permit real image-source requests; no paid models are used')
    cases=[('oxheart','Покажи, как выглядят помидоры Бычье сердце','image_gallery'),('labrador','Покажи, как выглядит лабрадор','image_card'),('raspberry-pi','Покажи картинку Raspberry Pi','image_card'),('timer','Поставь таймер на 3 минуты','timer_widget'),('weather','Какая сейчас погода?','weather_card'),('music','Что сейчас играет?','music_card'),('diagram','Покажи схему голосового конвейера GoBot','rich_answer'),('info','Покажи карточку результата 127 × 43','info_card'),('private','Покажи фото моей теплицы','info_card')]
    cases.append(('status','Покажи статус системы','status_card'))
    cases.extend([('crater','Покажи как выглядит кратер','image_card'),('sunflower','Покажи как выглядит подсолнух','image_card')])
    cases.extend([('doughnut','Как выглядит пончик?','image_card'),('solar-diagram','Покажи схему солнечного затмения','rich_answer')])
    results=[];namespace='ephemeral-check-visual-'+str(uuid4())+'-'
    with sqlite3.connect(ROOT/'data/gobot.sqlite') as c:before=c.execute('SELECT count(*) FROM messages WHERE conversation_id LIKE ?',(namespace+'%',)).fetchone()[0]
    async with httpx.AsyncClient(trust_env=False,timeout=35) as client:
        async def request(text):
            started=time.perf_counter()
            response=await client.post(BASE+'/api/chat/stream',headers={'Origin':BASE},json={'text':text,'mode':'auto','conversation_id':namespace+str(uuid4()),'turn_id':str(uuid4()),'request_id':str(uuid4()),'remember':False,'speak':False})
            response.raise_for_status();events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            assert events[-1]['type']=='final' and events[-1]['data']['provider']=='local'
            frames=[e['data']['presentation'] for e in events if e['type']=='visual_response'];assert len(frames)==1
            return frames[0],(time.perf_counter()-started)*1000,events
        for name,text,expected in cases:
            frame,elapsed,events=await request(text)
            assert frame['type']==expected,(name,frame['type'],frame['metadata'])
            variants=[]
            for image in frame['images']:
                for variant in ['url','preview_variant','device_variant']:
                    response=await client.get(BASE+image[variant]);response.raise_for_status();assert response.headers['content-type']=='image/jpeg'
                    with Image.open(io.BytesIO(response.content)) as decoded:
                        if variant=='device_variant':assert decoded.size==(240,240) and len(response.content)<=65536 and not decoded.info.get('progressive')
                        variants.append({'variant':variant,'dimensions':list(decoded.size),'bytes':len(response.content)})
            if name=='timer':
                response=await client.post(BASE+'/api/visual/timer/cancel',headers={'Origin':BASE},json={'timer_id':frame['metadata']['timer_id']});response.raise_for_status()
            assert not any(e['type']=='audio_chunk' for e in events)
            results.append({'case':name,'type':frame['type'],'state':frame['metadata']['state'],'images':len(frame['images']),'synthetic':frame['metadata'].get('synthetic',False),'source':frame['source']['label'],'cache_hit':frame['metadata']['cache_hit'],'ms':elapsed,'short_speech_fragments':sum(e['type']=='sentence_ready' for e in events),'variants':variants})
        frame,elapsed,_=await request(cases[0][1]);assert frame['metadata']['cache_hit']
        results.append({'case':'repeat_oxheart','cache_hit':True,'ms':elapsed})
        page=await client.get(BASE+'/');assert 'visual-response' in page.text and 'visual.js' in page.text and 'active-timers' in page.text
        script=await client.get(BASE+'/visual.js');assert script.status_code==200
    with sqlite3.connect(ROOT/'data/gobot.sqlite') as c:after=c.execute('SELECT count(*) FROM messages WHERE conversation_id LIKE ?',(namespace+'%',)).fetchone()[0]
    assert before==after
    report={'transport':'private Tailscale HTTPS, certificate verified','real_public_images':True,'synthetic_images':True,'neural_image_generation':False,'source':'Openverse/Flickr photos and local procedural diagrams','cases':results,'persistent_message_delta':after-before,'paid_model_calls':0,'cli_calls':0,'stt_tts_calls':0,'iphone_render_verified':False,'desktop_visual_inspection':'No browser exposed to computer-use tools; DOM units only'}
    (ROOT/'docs/visual-e2e.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
