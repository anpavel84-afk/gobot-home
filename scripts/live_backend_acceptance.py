"""At most four separately owner-approved Luna generation calls, sequential, no retries.
Only fixed synthetic questions/context. No Live voice session or household audio.
"""
import argparse,asyncio,json,sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))

async def run(tools_suite=False):
    from gobot.owner_testing import OwnerTesting
    from gobot.live_backend import LiveBackend
    from gobot.context_manager import ContextManager
    owner=OwnerTesting(ROOT/'run/owner-testing');policy=owner.policy()
    if not policy.live_backend_enabled or policy.developer_live_backend_limit<(10 if tools_suite else 4):raise SystemExit('Explicit Luna developer admission required')
    backend=LiveBackend(ROOT/'run/live',owner);context=ContextManager.configured();results=[];previous=[]
    cases=[
        ('explanation','Что такое чёрная дыра? Объясни коротко.'),
        ('continuity','А расскажи ещё один интересный факт по этой же теме.'),
        ('numbers_dates','Перепиши числа словами, сохраняя смысл: встреча 25 декабря 2026 года в 14:35, цена 1250 рублей, скидка 17 процентов.'),
        ('semantic_subject','Чем пауки отличаются от насекомых? Ответь двумя предложениями.')]
    if tools_suite:cases=[('garden','Что такое мульчирование?'),('cooking','Чем заменить разрыхлитель?'),('language','Объясни разницу между say и tell'),
        ('science','Почему лёд плавает?'),('learning','Объясни дроби ребёнку'),('home','Как организовать кабели на столе?'),
        ('writing','Напиши короткое приглашение на ужин'),('games','Загадай короткую загадку про Луну'),
        ('technical','Зачем нужна идемпотентность?'),('planning','Составь черновой список покупок для овощного супа')]
    for label,question in cases:
        packet=context.pack(question,{'messages':previous,'facts':[],'retrieved':[]},'FAST_CHAT');chunks=[]
        async def delivered(text):chunks.append(text)
        try:
            result=await backend.answer(question,packet,binding=policy.allowed_client_id,operation='luna-canary-'+uuid4().hex,developer=True,on_text=delivered)
            results.append({'case':label,'question':question,'actual_model':result['model'],'text':result['text'],'usage':result['usage'],
                'counted_input_tokens':result['input_count'],'timings':result['timings'],'estimated_usd':result['estimated_usd'],'delivered_chunks':len(chunks)})
            previous=[{'role':'user','content':question},{'role':'assistant','content':result['text']}]
        except Exception as error:
            results.append({'case':label,'failure_code':str(error) if isinstance(error,(ValueError,PermissionError,RuntimeError)) else type(error).__name__})
            break # No automatic paid retry, and do not burn later cases on an admission/contract failure.
    report={'synthetic_only':True,'model':'gpt-6-luna','test_path':'direct_production_backend','live_session_created':False,'iphone':False,
        'acoustic_verified':False,'max_generations':len(cases),'auto_retries':0,'results':results,'estimated_usd':sum(r.get('estimated_usd') or 0 for r in results)}
    (ROOT/('docs/skills-luna-acceptance.json' if tools_suite else 'docs/live-backend-acceptance.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--real',action='store_true');parser.add_argument('--tools-suite',action='store_true');args=parser.parse_args()
    if not args.real:raise SystemExit('Owner-approved bounded developer budget and --real required')
    asyncio.run(run(args.tools_suite))
