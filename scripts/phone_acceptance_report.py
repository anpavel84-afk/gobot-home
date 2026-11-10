"""Summarize existing content-free traces of the authorized phone run only."""
import argparse,hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def summarize(client):
    events={e['name']:e['ms'] for e in client.get('events',[])}
    started=events.get('filler_started');finished=events.get('opening_completed')
    answer=events.get('first_answer_playback');preempted=events.get('opening_preempted',events.get('filler_preempted'))
    silence=max(0,answer-finished) if answer is not None and finished is not None and finished<=answer else 0 if answer is not None and preempted is not None else None
    return {'clock_domain':'client_monotonic','earcon_ms':events.get('earcon_started'),
        'first_text_ms':events.get('first_text'),'opening_start_ms':started,'opening_complete_ms':finished,
        'opening_preempted_ms':preempted,'useful_playback_ms':answer,'silence_after_opening_ms':silence,
        'playback_complete_ms':events.get('playback_complete'),'followup_opened_ms':events.get('followup_opened'),
        'error_recorded':'error' in events,'cancel_recorded':'cancelled' in events,
        'acoustic_measurement':False,'raw_text_or_audio_included':False}

def collect(budget_path,telemetry_path,metrics_path):
    budget=json.loads(Path(budget_path).read_text());allowed=set(budget['request_hashes']);groups={}
    with sqlite3.connect(telemetry_path) as db:
        rows=db.execute('SELECT id,domain,data,created FROM traces WHERE created>=? ORDER BY created',(budget['created'],)).fetchall()
    for ident,domain,raw,created in rows:
        digest=hashlib.sha256(ident.encode()).hexdigest()
        if digest in allowed:groups.setdefault(digest,{})[domain]=json.loads(raw)
    out=[]
    for group in groups.values():
        if 'client_monotonic' not in group:continue
        row=summarize(group['client_monotonic']);row['index']=len(out)+1
        bridge=group.get('bridge',{});spans={e['name']:e['ms'] for e in bridge.get('events',[])}
        row['bridge']={'clock_domain':'bridge','prompt_to_init_ms':spans['provider_initialized']-spans['prompt_sent'] if 'provider_initialized' in spans and 'prompt_sent' in spans else None,
            'prompt_to_first_delta_ms':spans['assistant_delta']-spans['prompt_sent'] if 'assistant_delta' in spans and 'prompt_sent' in spans else None,
            'provider_input_usage':'unavailable in content-free trace'}
        brain=group.get('brain',{});meta=brain.get('metadata',{});row['model']=meta.get('model');row['context_tokens_estimate']=meta.get('context_tokens')
        turn=meta.get('turn_id')
        row['tts_characters_submitted']=None
        if turn:
            with sqlite3.connect(metrics_path) as db:
                found=db.execute("SELECT milliseconds FROM stage_metrics WHERE tag=? AND stage='tts_characters_submitted'",(turn,)).fetchone()
            if found:row['tts_characters_submitted']=found[0]
        out.append(row)
    return {'scope':'only trace IDs admitted by the one-time phone budget; no conversation content read',
        'status':'traces_collected_owner_observation_required' if out else 'awaiting_physical_iphone_run','n':len(out),'rows':out,
        'budget':{k:budget[k] for k in ['stt_attempts','stt_seconds','chat_reservations','tts_characters_reserved']},
        'physical_iphone_result':'awaiting owner confirmation','p95':None,'additional_opening_synthesis_requests':0,
        'limits':{'stt_attempts':3,'stt_seconds':45,'flash_requests':2,'tts_characters':800}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='docs/phone-acceptance-results.json');args=p.parse_args()
    report=collect(ROOT/'run/phone-acceptance/budget.json',ROOT/'data/telemetry.sqlite',ROOT/'data/gobot.sqlite')
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
