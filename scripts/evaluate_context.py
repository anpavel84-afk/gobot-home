"""Free deterministic synthetic day, isolated from the owner's database/CLI."""
import json,sys,tempfile,time,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.context_manager import ContextManager,tokens
from gobot.live_agents import context_prompt

def run():
    directory=ROOT/'run/evaluations';directory.mkdir(parents=True,exist_ok=True)
    sizes=[];elapsed=[];returns=[];topic_ids={};builder=ContextManager()
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        memory=Memory(str(Path(temporary)/'synthetic.sqlite'))
        subjects=['теплица','космос','кулинария','математика','садоводство','электричество','литература','аквариум','музыка','велосипед']
        for index in range(200):
            subject=subjects[(index//10)%len(subjects)]
            text=('Вернёмся к теме '+subject if index>=100 and index%10==0 else 'Обсудим тему '+subject if index%10==0 else 'А подробнее про '+subject+'?')
            # Simulate production provenance only inside this disposable DB.
            req=ChatRequest(text=text,device_id='synthetic:one',conversation_id='offline-evaluation-day',mode='fast')
            memory.start(req);start=time.perf_counter();packet=builder.pack(text,memory.context(req),'FAST_CHAT');elapsed.append((time.perf_counter()-start)*1000)
            sizes.append(tokens(context_prompt(text,packet)))
            if index%10==0 and index<100:topic_ids[subject]=packet['topic']['topic_id']
            if index>=100 and index%10==0:returns.append(packet['topic']['outcome']=='resume_topic' and packet['topic']['topic_id']==topic_ids[subject])
            memory.archive.record_context(req,packet,'fixture_not_a_real_provider')
            memory.finish(req,'completed','Синтетический материал о теме '+subject+'. '+('Разбираем условия, возможные решения и открытые вопросы. '*16),'fixture_not_a_real_provider',[])
            memory.archive.maintain_one()
        correct_scope=not memory.archive.search('synthetic:other','теплица')
        aliases=['парник','вселенная','приготовление еды','алгебра','уход за растениями','напряжение','книги','рыбки','мелодии','двухколёсный транспорт']
        lexical_hits=sum(bool(memory.archive.search('synthetic:one',query)) for query in subjects)
        synonym_hits=sum(bool(memory.archive.search('synthetic:one',query)) for query in aliases)
        with memory.connect() as c:
            summaries=c.execute('SELECT content FROM topic_summaries').fetchall();attributed=0;valid=0
            for row in summaries:
                for quote in json.loads(row[0])['source_excerpts']:
                    attributed+=1;source=c.execute('SELECT content FROM messages WHERE id=?',(quote['id'],)).fetchone()
                    valid+=bool(source and source[0].startswith(quote['excerpt']))
        assert max(sizes)<=6000 and correct_scope
        result={'synthetic':True,'turns':200,'real_model_calls':0,'api_cost':0,'cli_quota_used':0,
                'packet_tokens':{'start':sizes[0],'middle':sizes[99],'end':sizes[-1],'maximum':max(sizes),'p50':statistics.median(sizes),'p95':sorted(sizes)[189]},
                'context_build_ms':{'p50':statistics.median(elapsed),'p95':sorted(elapsed)[189]},
                'explicit_returns':{'passed':sum(returns),'total':len(returns)},'cross_owner_leaks':0,
                'retrieval_probe':{'lexical_hits':lexical_hits,'lexical_queries':10,'synonym_hits':synonym_hits,'synonym_queries':10,'not_a_representative_recall_benchmark':True},
                'summary_source_checks':{'valid_attributed_excerpts':valid,'total':attributed,'semantic_adequacy':'not measured'},
                'token_count_kind':'cl100k tokenizer estimate; not actual CLI input usage',
                'provider_history':'fresh ephemeral thread/process; no live CLI used in evaluation',
                'limitations':['Generated data, not family conversations','FTS prefix lexical search; no measured semantic recall','Extractive summaries do not infer accepted decisions','No actual model correctness comparison','No physical playback or network timing in this benchmark']}
    (ROOT/'docs/context-evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':run()
