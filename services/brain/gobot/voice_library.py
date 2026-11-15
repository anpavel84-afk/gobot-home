"""Public opening inventory + semantic cache keys. Never synthesizes on lookup."""
import hashlib,json,unicodedata
from .speech_openings import OpeningCache
from .speech_formatter import SpeechFormatter
from .audio import TTS_MODEL

def cache_key(text,*,voice='marin',provider='openai',model=TTS_MODEL,version='1',language='ru',
              style='natural',speed=1.,sample_rate=24000,privacy_scope='public'):
    payload={'text':unicodedata.normalize('NFC',text).strip(),'voice':voice,'provider':provider,'model':model,
        'version':version,'language':language,'style':style,'speed':speed,'formatter':SpeechFormatter.version,
        'format':'pcm_s16le_wav','sample_rate':sample_rate,'privacy_scope':privacy_scope}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

class VoiceLibrary:
    def __init__(self,cache=None):self.cache=cache or OpeningCache()
    def inventory(self):
        entries=[]
        for ident,row in self.cache.entries.items():
            clip=self.cache.clip('marin',ident)
            entries.append({'id':ident,'text':row['text'],'role':'filler','success_confirmation':False,
                'status':'ready' if clip else 'missing','duration_seconds':clip['duration_seconds'] if clip else None,
                'source':'existing_owner_approved_openai_cache','voice':'marin','model':TTS_MODEL,
                'format':'wav_pcm16_mono_24000','url':clip['url'] if clip else None})
        return {'entries':entries,'ready':sum(e['status']=='ready' for e in entries),'total':len(entries),
            'runtime_generation':False,'dynamic_templates':[
                {'id':'timer.success','condition':'verified_timer_created','status':'missing_dynamic_audio'},
                {'id':'weather.summary','condition':'fresh_verified_weather','status':'missing_dynamic_audio'},
                {'id':'clarify.duration','condition':'current_pending','status':'missing_dynamic_audio'}]}
    def dry_run(self):
        inventory=self.inventory();missing=[e for e in inventory['entries'] if e['status']=='missing']
        return {'dry_run':True,'requests_executed':0,'missing_ids':[e['id'] for e in missing],
            'characters':sum(len(e['text']) for e in missing),'estimated_usd':None,
            'price_not_verified':True,'mass_synthesis_authorized':False}
