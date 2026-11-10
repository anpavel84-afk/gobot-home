import sqlite3, json, hashlib, time, threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied REAL);
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, device_id TEXT NOT NULL, created REAL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE, role TEXT, content TEXT, provider TEXT, turn_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS sessions(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, last_seen REAL, active INTEGER);
CREATE TABLE IF NOT EXISTS summaries(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE, content TEXT, provider TEXT);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, device_id TEXT, content TEXT, consent INTEGER CHECK(consent=1), provider TEXT, created REAL);
CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE, request_hash TEXT, status TEXT, provider TEXT, trace TEXT, result TEXT, updated REAL);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,id);
CREATE TABLE IF NOT EXISTS stage_metrics(tag TEXT,provider TEXT,stage TEXT,milliseconds REAL,created REAL,
 PRIMARY KEY(tag,provider,stage));
"""
class Conflict(Exception): pass
class Memory:
    def __init__(self,path):
        self.path=path; Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            from .visual_memory import SCHEMA as VISUAL_SCHEMA
            if (c.execute("SELECT 1 FROM sqlite_master WHERE name='messages'").fetchone()
                    and not c.execute("SELECT 1 FROM sqlite_master WHERE name='active_visual_subjects'").fetchone()
                    and c.execute('SELECT count(*) FROM messages').fetchone()[0]):
                directory=Path(path).parent/'backups';directory.mkdir(exist_ok=True)
                with sqlite3.connect(directory/('before-visual-memory-'+str(time.time_ns())+'.sqlite')) as backup:
                    c.backup(backup)
                    if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('visual_memory_backup_failed')
            c.executescript(SCHEMA+VISUAL_SCHEMA);c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(1,?)",(time.time(),))
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(3,?)',(time.time(),))
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(6,?)',(time.time(),))
        from .archive import Archive
        self.archive=Archive(self);self.transient={};self.transient_lock=threading.Lock();self.visual_cancelled={};self.transient_pending={}
    def set_pending(self,req,kind,payload=None):
        from uuid import uuid4
        action={'id':str(uuid4()),'kind':kind,'payload':{**(payload or {}),'_profile_epoch':req.profile_epoch},'expires':time.time()+120}
        if not req.remember:
            with self.transient_lock:
                now=time.time();self.transient_pending={k:v for k,v in self.transient_pending.items() if v['expires']>now}
                if len(self.transient_pending)>=256:raise Conflict('pending_capacity')
                self.transient_pending[(req.device_id,req.conversation_id,req.profile_epoch)]=action
        else:
            with self.connect() as c:
                c.execute("UPDATE pending_actions SET status='superseded' WHERE owner=? AND conversation_id=? AND status='pending'",(req.device_id,req.conversation_id))
                c.execute("INSERT INTO pending_actions VALUES(?,?,?,?,?,?,'pending')",(action['id'],req.device_id,req.conversation_id,kind,json.dumps(action['payload']),action['expires']))
        return action
    def settle_pending(self,req,status,ident=None):
        if not req.remember:
            with self.transient_lock:
                key=(req.device_id,req.conversation_id,req.profile_epoch);pending=self.transient_pending.get(key)
                if pending and (ident is None or pending['id']==ident):self.transient_pending.pop(key,None)
        else:
            with self.connect() as c:
                c.execute("UPDATE pending_actions SET status=? WHERE owner=? AND conversation_id=? AND status='pending' AND expires>? AND (? IS NULL OR id=?)",(status,req.device_id,req.conversation_id,time.time(),ident,ident))
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path, timeout=5);c.row_factory=sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA foreign_keys=ON");c.execute("PRAGMA secure_delete=ON")
        try:
            with c: yield c
        finally: c.close()
    def recover(self):
        with self.connect() as c:
            c.execute("UPDATE turns SET status='cancelled',result='',updated=? WHERE status='running'",(time.time(),))
            c.execute("UPDATE sessions SET active=0")
            c.execute("UPDATE archive_messages SET status='cancelled' WHERE status='running'")
    def start(self,req):
        payload=req.model_dump(exclude={"correlation_id","turn_id","request_id","utterance_id","event_id","trace_id"})
        if payload.get('profile_epoch') is None:payload.pop('profile_epoch',None)
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        if not req.remember:
            with self.transient_lock:
                now=time.time();self.transient={k:v for k,v in self.transient.items() if now-v['updated']<3600}
                keys={req.turn_id,*[v for v in (req.request_id,req.utterance_id,req.event_id) if v]}
                for row in self.transient.values():
                    if row['owner']==req.device_id and keys&row['keys']:
                        if row['request_hash']!=digest or row['status']=='running':raise Conflict('temporary request conflict or active')
                        return {k:v for k,v in row.items() if k not in {'keys','owner'}}
                if len(self.transient)>=256:raise Conflict('temporary memory capacity reached')
                self.transient[req.turn_id]={'owner':req.device_id,'conversation':req.conversation_id,'epoch':req.profile_epoch,'text':req.text,'keys':keys,'request_hash':digest,'status':'running','result':'','provider':'','updated':now}
                return
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM turns WHERE id=?",(req.turn_id,)).fetchone()
            for kind in ('request_id','utterance_id','event_id'):
                value=getattr(req,kind)
                if value:
                    previous=c.execute('SELECT t.* FROM request_keys k JOIN turns t ON t.id=k.turn_id WHERE k.owner=? AND k.kind=? AND k.external_id=?',(req.device_id,kind,value)).fetchone()
                    if previous:row=previous;break
            if row:
                if row['request_hash']!=digest:raise Conflict("turn_id payload conflict")
                if row['status']=='running':raise Conflict("turn already running")
                return dict(row)
            if c.execute("SELECT 1 FROM turns WHERE conversation_id=? AND status='running'",(req.conversation_id,)).fetchone():raise Conflict("conversation already has an active turn")
            conv=c.execute("SELECT device_id FROM conversations WHERE id=?",(req.conversation_id,)).fetchone()
            if conv and conv[0]!=req.device_id:raise Conflict("conversation ownership conflict")
            c.execute("INSERT OR IGNORE INTO conversations VALUES(?,?,?)",(req.conversation_id,req.device_id,time.time()))
            c.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,1)",(req.conversation_id,time.time()))
            c.execute("INSERT INTO turns VALUES(?,?,?,'running','','','',?)",(req.turn_id,req.conversation_id,digest,time.time()))
            message=c.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'user',?,'input',?,?)",(req.conversation_id,req.text,req.turn_id,time.time())).lastrowid
            for kind in ('request_id','utterance_id','event_id'):
                value=getattr(req,kind)
                if value:c.execute('INSERT INTO request_keys VALUES(?,?,?,?)',(req.device_id,kind,value,req.turn_id))
            self.archive.begin(c,req,message)
    def finish(self,req,status,text,provider,trace):
        if not req.remember:
            with self.transient_lock:
                row=self.transient.get(req.turn_id)
                if row and row['status']=='completed':
                    if status=='completed':
                        from .visual_memory import confirmed
                        row.update(trace=json.dumps(trace),updated=time.time(),visual=confirmed(trace) if req.turn_id not in self.visual_cancelled else None)
                    return
                if row and row['status']=='running':
                    from .visual_memory import confirmed
                    row.update(status=status,result=text,provider=provider,trace=json.dumps(trace),updated=time.time(),visual=confirmed(trace) if status=='completed' and req.turn_id not in self.visual_cancelled else None)
                    if status!='completed' or req.new_topic:
                        for other in self.transient.values():
                            if other is not row and other['owner']==req.device_id and other['conversation']==req.conversation_id:other.pop('visual',None)
            return
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT status FROM turns WHERE id=?",(req.turn_id,)).fetchone()
            if row and row[0]=='completed':
                if status=='completed':
                    c.execute('UPDATE turns SET trace=?,updated=? WHERE id=?',(json.dumps(trace),time.time(),req.turn_id))
                    from .visual_memory import finish as finish_visual
                    finish_visual(self,c,req,status,provider,trace)
                return
            if not row or row[0]!='running': return
            c.execute("UPDATE turns SET status=?,result=?,provider=?,trace=?,updated=? WHERE id=?",(status,text,provider,json.dumps(trace),time.time(),req.turn_id))
            c.execute("UPDATE sessions SET active=0,last_seen=? WHERE conversation_id=?",(time.time(),req.conversation_id))
            if status=='completed':
                c.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'assistant',?,?,?,?)",(req.conversation_id,text,provider,req.turn_id,time.time()))
                rows=c.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 6",(req.conversation_id,)).fetchall()
                # Deterministic extractive summary, never presented as a model-generated summary.
                summary='\n'.join(f"{r[0]}: {r[1][:300]}" for r in reversed(rows))[-1800:]
                c.execute("INSERT OR REPLACE INTO summaries VALUES(?,?,'extractive')",(req.conversation_id,summary))
            elif text:
                c.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'assistant',?,?,?,?)",(req.conversation_id,text,provider,req.turn_id,time.time()))
            self.archive.finish(c,req,status,provider)
            from .visual_memory import finish as finish_visual
            finish_visual(self,c,req,status,provider,trace)
    def context(self,req):
        context=self._context(req)
        from .visual_memory import active
        if req.remember:context['active_visual_subject']=active(self,req,context)
        else:
            with self.transient_lock:context['active_visual_subject']=active(self,req,context)
        return context
    def _context(self,req):
        if not req.remember:
            with self.transient_lock:
                rows=[v for key,v in self.transient.items() if key!=req.turn_id and v['owner']==req.device_id and v['conversation']==req.conversation_id and v['status']=='completed' and time.time()-v['updated']<3600][-6:]
                messages=[item for row in rows for item in ({'role':'user','content':row['text'],'provider':'input'},{'role':'assistant','content':row['result'],'provider':row['provider']})]
                pending=self.transient_pending.get((req.device_id,req.conversation_id,req.profile_epoch))
                if pending and pending['expires']<=time.time():pending=None
                return {'messages':messages,'summary':'','facts':[],'original_question':'','pending_action':dict(pending) if pending else None}
        if req.mode is not None or req.provider in {'codex','antigravity','google','gemini'}:return self.archive.topic_context(req)
        with self.connect() as c:
            owner=c.execute('SELECT device_id FROM conversations WHERE id=?',(req.conversation_id,)).fetchone()
            if owner and owner[0]!=req.device_id:return {'messages':[],'summary':'','facts':[]}
            msgs=[dict(x) for x in c.execute("SELECT role,content,provider FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12",(req.conversation_id,))][::-1]
            row=c.execute("SELECT content FROM summaries WHERE conversation_id=?",(req.conversation_id,)).fetchone()
            facts=[x[0] for x in c.execute("SELECT content FROM facts WHERE device_id IN (?, 'family:home') AND consent=1",(req.device_id,))]
            origin=c.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user' ORDER BY id LIMIT 1",(req.conversation_id,)).fetchone()
            return {'messages':msgs,'summary':row[0] if row else '', 'facts':facts,'original_question':origin[0] if origin else ''}
    def history(self,conversation,device):
        with self.connect() as c:
            owner=c.execute('SELECT device_id FROM conversations WHERE id=?',(conversation,)).fetchone()
            if not owner or owner[0]!=device:return {'messages':[]}
            rows=c.execute("""SELECT m.id,m.role,m.content,m.provider,m.turn_id,a.status,a.namespace,t.trace
                FROM messages m LEFT JOIN archive_messages a ON a.message_id=m.id
                LEFT JOIN turns t ON m.role='assistant' AND t.id=m.turn_id AND t.status='completed'
                WHERE m.conversation_id=? ORDER BY m.id DESC LIMIT 100""",(conversation,)).fetchall()
        messages=[]
        from .presentation import Presentation
        for row in reversed(rows):
            message=dict(row)
            raw=message.pop('trace')
            if raw:
                try:
                    for entry in json.loads(raw):
                        if entry.get('visual_plan_rejected') or entry.get('optional_visual_error'):message['recover_illustration']=True
                        if 'presentation' in entry:
                            frame=Presentation.model_validate(entry['presentation'])
                            if frame.images:
                                message.setdefault('presentations',[]).append(frame.model_dump())
                                message['presentation']=frame.model_dump()
                except (ValueError,TypeError,AttributeError):pass
            messages.append(message)
        return {'messages':messages}
    def clear_visual_turn(self,turn):
        with self.transient_lock:
            self.visual_cancelled[turn]=time.time()
            if len(self.visual_cancelled)>2048:self.visual_cancelled.pop(next(iter(self.visual_cancelled)))
            row=self.transient.get(turn)
            if row:
                rows=[v for v in self.transient.values() if v['owner']==row['owner'] and v['conversation']==row['conversation']]
                if rows[-1] is row:
                    for other in rows:other.pop('visual',None)
                else:row.pop('visual',None)
        with self.connect() as c:
            c.execute('''DELETE FROM active_visual_subjects WHERE turn_id=? OR
                (conversation_id IN (SELECT conversation_id FROM turns WHERE id=?) AND NOT EXISTS
                 (SELECT 1 FROM messages WHERE conversation_id=active_visual_subjects.conversation_id AND role='user'
                  AND id>(SELECT MAX(id) FROM messages WHERE turn_id=? AND role='user')))''',(turn,turn,turn))
    def status(self,turn):
        with self.connect() as c:
            r=c.execute("SELECT id,status,provider,updated FROM turns WHERE id=?",(turn,)).fetchone();return dict(r) if r else None
    def add_fact(self,device,text,consent,provider='owner'):
        if consent is not True:raise ValueError('Explicit consent required')
        with self.connect() as c:
            now=time.time();ident=c.execute("INSERT INTO facts(device_id,content,consent,provider,created) VALUES(?,?,1,?,?)",(device,text,provider,now)).lastrowid
            scope='family' if device=='family:home' else 'personal' if device.startswith('personal:') else 'guest'
            c.execute('INSERT INTO memory_facts(legacy_id,owner,scope,content,provenance,confirmation,valid_from) VALUES(?,?,?,?,?,?,?)',(ident,device,scope,text,provider,'explicit_consent',now))
    def purge(self,conversation=None,older_than=None):
        if conversation is None and older_than is None:raise ValueError('Explicit purge scope required')
        with self.connect() as c:
            if conversation:c.execute("DELETE FROM conversations WHERE id=?",(conversation,))
            else:c.execute("DELETE FROM conversations WHERE created<?",(older_than,))
        with self.connect() as c:c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    def forget_facts(self,device):
        with self.connect() as c:
            c.execute('DELETE FROM memory_facts WHERE owner=?',(device,))
            c.execute("DELETE FROM facts WHERE device_id=?",(device,))
            c.execute('DELETE FROM topic_summaries WHERE topic_id IN (SELECT id FROM topics WHERE owner=?)',(device,))
            c.execute('DELETE FROM memory_jobs WHERE topic_id IN (SELECT id FROM topics WHERE owner=?)',(device,))
    def record_metrics(self,tag,provider,values):
        import math
        allowed={'stt_final','stt_first_interim','speech_end_to_stt_final','llm_first_token','total_text','tts_first_chunk','first_audio_server','speaker_identity'}
        rows=[(tag,provider,name,float(value),time.time()) for name,value in values.items() if name in allowed and value is not None and isinstance(value,(int,float)) and math.isfinite(value) and 0<=value<86400000]
        if not rows:return
        with self.connect() as c:
            c.executemany('INSERT OR REPLACE INTO stage_metrics VALUES(?,?,?,?,?)',rows)
            c.execute('DELETE FROM stage_metrics WHERE created<?',(time.time()-30*86400,))
    def metric_summary(self):
        from .metrics import percentiles
        grouped={}
        with self.connect() as c:
            for row in c.execute('SELECT provider,stage,milliseconds FROM stage_metrics ORDER BY created DESC LIMIT 5000'):
                grouped.setdefault(row[0]+':'+row[1],[]).append(row[2])
        return {key:percentiles(samples) for key,samples in grouped.items()}
