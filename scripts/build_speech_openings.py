"""Explicit one-time OpenAI clip preparation; never called by the voice runtime."""
import argparse,asyncio,json,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.speech_openings import OpeningCache,catalog
from gobot.speech_formatter import SpeechFormatter
from gobot.audio import Speech

async def build(args):
    cache=OpeningCache();formatter=SpeechFormatter();rows=catalog()[:args.limit]
    work=[(row,formatter.format(row['text'])) for row in rows if cache.clip(args.voice,row['id']) is None]
    required=sum(len(text) for _,text in work)
    summary={'clips':len(work),'characters':required,'voice':args.voice,'paid_requests_made':0}
    if not args.execute:print(json.dumps(summary));return
    if not args.owner_authorized or len(work)>args.max_requests or required>args.max_characters:raise SystemExit('Explicit authorization/budget missing or insufficient')
    journal=ROOT/'run/speech-opening-authorized-build.json'
    if journal.exists():raise SystemExit('Existing one-time journal: inspect it; no automatic retry/resume')
    ledger={'authorized_requests':args.max_requests,'authorized_characters':args.max_characters,'voice':args.voice,'attempts':[],'characters_reserved':0,'closed':False}
    def save():journal.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf8')
    save();failures=0
    async with Speech().turn() as synth:
        for row,text in work:
            entry={'id':row['id'],'characters':len(text),'status':'reserved','started':time.time()}
            ledger['attempts'].append(entry);ledger['characters_reserved']+=len(text);save()
            try:
                chunks=[];rate=None
                async for pcm,rate in synth.synthesize(text,'openai',args.voice,paid_consent=True):
                    chunks.append(pcm)
                    if sum(map(len,chunks))>480000:raise ValueError('opening_audio_too_long')
                cache.put(args.voice,row['id'],b''.join(chunks),rate,text)
                entry['status']='completed';failures=0
            except Exception as error:
                entry['status']='failed';entry['error_type']=type(error).__name__;failures+=1
            save()
            if len(ledger['attempts'])%5==0 or entry['status']=='failed':print(json.dumps({'attempts':len(ledger['attempts']),'characters':ledger['characters_reserved'],'ready':cache.status(args.voice)['ready_count']}),flush=True)
            if failures>=3:break
    ledger['closed']=True;save();print(json.dumps({'completed':True,**cache.status(args.voice),'attempts':len(ledger['attempts']),'characters':ledger['characters_reserved']}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--voice',default='marin');p.add_argument('--limit',type=int,choices=range(1,101),default=100)
    p.add_argument('--execute',action='store_true');p.add_argument('--owner-authorized',action='store_true');p.add_argument('--max-requests',type=int,default=0);p.add_argument('--max-characters',type=int,default=0)
    asyncio.run(build(p.parse_args()))
