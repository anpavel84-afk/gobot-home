"""Public, reviewed OpenAI opening clips. Runtime lookup never synthesizes audio."""
import hashlib,json,os,re,wave,io,time,threading
from pathlib import Path
from .audio import TTS_MODEL,OPENAI_VOICES

ROOT=Path(__file__).resolve().parents[3]
CATALOG=ROOT/'services/brain/speech-openings.json'

def catalog():
    value=json.loads(CATALOG.read_text(encoding='utf-8'))
    rows=value['entries']
    if value.get('version')!=1 or len(rows)!=100 or len({r['id'] for r in rows})!=100:raise ValueError('invalid_opening_catalog')
    return rows

def category(text,context):
    lower=text.casefold()
    if re.search(r'сравни|чем .*отлич|разниц',lower):return 'comparison'
    if re.search(r'придумай|сочини|расскажи сказку',lower):return 'creative'
    if (context.get('messages') or context.get('recent_dialogue')) and re.match(r'^(?:а |и |еще|ещё|продолж|подробн)',lower):return 'continuation'
    if re.search(r'как (?:приготовить|сделать|построить|настроить|поставить)|порядок действий',lower):return 'howto'
    if re.search(r'что такое|как устроен|как работает|объясни|почему',lower):return 'explanation'
    return 'general'

class OpeningCache:
    def __init__(self,root=None):
        self.root=Path(root or ROOT/'data/speech-openings');self.unavailable_reason=None;self.previous={};self.lock=threading.Lock()
        try:self.entries={row['id']:row for row in catalog()}
        except (OSError,ValueError,KeyError,TypeError):self.entries={};self.unavailable_reason='opening_catalog_invalid_or_missing'
    def key(self,voice,ident):
        if voice not in OPENAI_VOICES or ident not in self.entries:raise ValueError('invalid_opening')
        return hashlib.sha256(json.dumps([voice,ident,self.entries[ident]['text'],TTS_MODEL],ensure_ascii=False).encode()).hexdigest()
    def clip(self,voice,ident,*,validate_audio=True):
        try:
            key=self.key(voice,ident);path=self.root/(key+'.wav');meta=self.root/(key+'.json')
            if path.is_symlink() or meta.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):return None
            if meta.stat().st_size>4096 or path.stat().st_size>600000:return None
            info=json.loads(meta.read_text(encoding='utf8'))
            if info.get('voice')!=voice or info.get('model')!=TTS_MODEL or info.get('text')!=self.entries[ident]['text'] or info.get('source')!='openai':return None
            if not validate_audio:return {'id':ident,'voice':voice,'text':info['text'],'url':'/api/speech/openings/'+voice+'/'+ident+'.wav','characters':info['characters']}
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=info.get('sha256'):return None
            with wave.open(io.BytesIO(raw),'rb') as wav:
                if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=24000 or not 0<wav.getnframes()<=240000:return None
                duration=wav.getnframes()/24000
            return {'id':ident,'voice':voice,'text':info['text'],'url':'/api/speech/openings/'+voice+'/'+ident+'.wav','path':path,'characters':info['characters'],'duration_seconds':duration}
        except (OSError,ValueError,KeyError,TypeError,wave.Error,EOFError):return None
    def put(self,voice,ident,pcm,rate,speech_text):
        key=self.key(voice,ident)
        if rate!=24000 or not pcm or len(pcm)%2 or len(pcm)>480000:raise ValueError('invalid_opening_audio')
        self.root.mkdir(parents=True,exist_ok=True)
        data=io.BytesIO()
        with wave.open(data,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
        raw=data.getvalue();info={'source':'openai','model':TTS_MODEL,'voice':voice,'id':ident,'text':self.entries[ident]['text'],'speech_text':speech_text,'characters':len(speech_text),'sha256':hashlib.sha256(raw).hexdigest()}
        # Bound this public-phrase cache. Missing metadata/audio is a silent skip.
        files=list(self.root.glob('*.wav'))
        total=sum(p.stat().st_size for p in files)
        for old in sorted(files,key=lambda p:p.stat().st_mtime):
            if total+len(raw)<=32*1024*1024:break
            total-=old.stat().st_size;old.unlink();old.with_suffix('.json').unlink(missing_ok=True)
        for suffix,content in [('.wav',raw),('.json',json.dumps(info,ensure_ascii=False).encode())]:
            tmp=self.root/(key+suffix+'.tmp');tmp.write_bytes(content);os.replace(tmp,self.root/(key+suffix))
    def select(self,text,voice,context,turn,session=None):
        kind=category(text,context)
        rows=[r for r in self.entries.values() if r['category']==kind and r.get('enabled',True)]
        value=text.casefold()
        def suitable(row):
            requirement=row.get('requires')
            if requirement=='two_options':return bool(re.search(r'\b(?:два|две|двух|2|оба)\b',value))
            if requirement=='story':return bool(re.search(r'сказк|истори|рассказ',value))
            if requirement=='scene':return bool(re.search(r'мир|планет|картин|сцен|город|образ|представ',value))
            return True
        rows=[r for r in rows if suitable(r)]
        # A stable shuffle per turn prevents a permanently repeated opening.
        rows.sort(key=lambda r:hashlib.sha256((turn+r['id']).encode()).digest())
        # No full WAV read is required to choose prompt metadata. HTTP delivery
        # performs the checksum/format validation independently and may skip it.
        key=session or turn
        with self.lock:last=self.previous.get(key,(None,0))[0]
        rows.sort(key=lambda r:len(r['text']))
        for row in rows:
            if row['id']==last:continue
            ready=self.clip(voice,row['id'],validate_audio=False)
            if ready:
                with self.lock:
                    self.previous={k:v for k,v in self.previous.items() if time.time()-v[1]<3600}
                    if len(self.previous)>=256:self.previous.pop(next(iter(self.previous)))
                    self.previous[key]=(row['id'],time.time())
                return {k:v for k,v in ready.items() if k!='path'}
        return None
    def status(self,voice):
        return {'voice':voice,'catalog_count':len(self.entries),'ready_count':sum(self.clip(voice,k) is not None for k in self.entries),'legacy_denis_filler':False,'runtime_synthesis':False,'unavailable_reason':self.unavailable_reason}
