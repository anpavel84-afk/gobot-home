"""Opt-in owner diagnostic journal. DPAPI ciphertext, bounded, no semantic memory.

No provider credentials, audio, embeddings, prompts or context archives. Text
transcripts are recorded only under the separate explicit diagnostic consent.
SQLite writes/encryption run on a bounded worker, never on the voice loop.
"""
import asyncio
import hashlib
import json
import math
import queue
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DENIED = {'authorization','api_key','key','secret','password','cookie','cookies','headers',
          'sdp','audio','raw_audio','pcm','embedding','embeddings','fingerprint',
          'instructions','context','packet','stdout','stderr','preferences','profile',
          'environment','env','latitude','longitude','input_audio','output_audio','voiceprint',
          'access_token','refresh_token','token','client_secret','session','input'}


def clean(value,depth=0):
    if depth>5:return '[depth limit]'
    if type(value) is float:return value if math.isfinite(value) else '[nonfinite]'
    if value is None or type(value) in (bool,int):return value
    if isinstance(value,str):
        value=re.sub(r'\bsk-[A-Za-z0-9_-]{16,}', '[redacted key]',value)
        value=re.sub(r'(?i)\bBearer\s+\S+','Bearer [redacted]',value)
        value=re.sub(r'(?i)((?:api[_ -]?key|password|пароль|access[_ -]?token)\s*[:=]\s*)[^\s,;]+',r'\1[redacted]',value)
        value=re.sub(r'(https?://[^\s?]+)\?[^\s]+',r'\1?[query omitted]',value)
        return value[:16000]+('[truncated]' if len(value)>16000 else '')
    if isinstance(value,dict):
        return {str(k)[:80]:clean(v,depth+1) for k,v in list(value.items())[:64]
                if str(k).casefold() not in DENIED and not re.search(r'(?i)credential|biometric|private_key|session_token',str(k))}
    if isinstance(value,(list,tuple)):return [clean(v,depth+1) for v in value[:64]]
    return '[unsupported value]'


class DebugJournal:
    def __init__(self,root,owner,*,protect=None,unprotect=None,clock=time.time):
        from .secrets_store import _dpapi
        self.root=Path(root);self.path=self.root/'journal.sqlite';self.owner=owner;self.clock=clock
        self.protect=protect or _dpapi;self.unprotect=unprotect or (lambda blob:_dpapi(blob,decrypt=True))
        self.pending=queue.Queue(maxsize=512);self.worker=None;self.lock=threading.RLock()
        self.dropped=0;self.last_error=None;self.written=0;self.stopping=False
        if self.path.exists():self.start_worker() # Expire old records even when recording is off.

    def start_worker(self):
        with self.lock:
            if not self.worker:
                self.worker=threading.Thread(target=self._work,name='gobot-debug-journal',daemon=True);self.worker.start()

    @staticmethod
    def scope(owner,client,epoch=None):
        return hashlib.sha256(json.dumps([owner,client,epoch or None],separators=(',',':')).encode()).hexdigest()

    @contextmanager
    def connect(self):
        self.root.mkdir(parents=True,exist_ok=True)
        c=sqlite3.connect(self.path,timeout=5)
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA secure_delete=ON')
        c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,scope TEXT NOT NULL,session TEXT NOT NULL,created REAL NOT NULL,engine TEXT NOT NULL,kind TEXT NOT NULL,sealed BLOB NOT NULL)')
        c.execute('CREATE INDEX IF NOT EXISTS journal_scope_session ON events(scope,session,id)')
        try:
            with c:yield c
        finally:c.close()

    def session_event(self,s,engine,kind,data=None):
        try:
            return self.append(binding=s.owner_test_binding,owner=s.offer.device_id,client=s.offer.client_id,
                epoch=s.offer.profile_epoch,session=s.id,engine=engine,kind=kind,data=data,
                turn=s.current.id if s.current else None)
        except Exception:self.last_error='journal_enqueue_failed';self.dropped+=1;return False

    def legacy_event(self,req,kind,data=None):
        flow=getattr(req,'_mode_flow',None)
        return self.append(binding=flow.binding if flow else req.client_id,
            owner=flow.owner if flow else req.device_id,client=flow.client if flow else req.client_id,
            epoch=flow.epoch if flow else req.profile_epoch,session=flow.id if flow else req.conversation_id,
            engine='A',kind=kind,data=data,turn=req.turn_id)

    def purge(self):
        if self.path.exists():
            with self.connect() as c:c.execute('DELETE FROM events WHERE created<?',(self.clock()-self.owner.policy().debug_journal_retention_days*86400,))

    def enabled(self,binding):
        p=self.owner.policy()
        return bool(p.debug_journal_enabled and self.owner.bound(binding))

    def append(self,*,binding,owner,client,epoch=None,session,engine,kind,data=None,turn=None):
        try:return self._append(binding=binding,owner=owner,client=client,epoch=epoch,session=session,engine=engine,kind=kind,data=data,turn=turn)
        except Exception:self.last_error='journal_enqueue_failed';self.dropped+=1;return False

    def _append(self,*,binding,owner,client,epoch=None,session,engine,kind,data=None,turn=None):
        if self.stopping or not self.enabled(binding):return False
        if engine not in {'A','B','C','brain'}:return False
        if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,80}',kind):return False
        # Record transport activity as metadata; never enqueue the audio itself.
        if kind in {'audio_chunk','audio'}:return False
        from .telemetry import code_commit
        payload={'turn_id':turn,'data':clean(data or {}),'code_commit':code_commit(),
                 'diagnostic_only':True,'transcript_is_audio_hypothesis':True}
        item=(self.scope(owner,client,epoch),str(session)[:100],self.clock(),engine,kind,
              json.dumps(payload,ensure_ascii=False,separators=(',',':')),binding)
        self.start_worker()
        try:self.pending.put_nowait(item);return True
        except queue.Full:self.dropped+=1;self.last_error='journal_queue_full';return False

    def _work(self):
        while True:
            try:item=self.pending.get(timeout=30)
            except queue.Empty:
                if self.stopping:return
                try:self.purge()
                except Exception:self.last_error='journal_cleanup_failed'
                continue
            if item is None:self.pending.task_done();return
            batch=[item]
            while len(batch)<32:
                try:
                    extra=self.pending.get_nowait()
                    if extra is None:self.pending.task_done();self.pending.put(None);break
                    batch.append(extra)
                except queue.Empty:break
            try:
                p=self.owner.policy();rows=[]
                for scope,session,created,engine,kind,payload,binding in batch:
                    if self.enabled(binding):rows.append((scope,session,created,engine,kind,self.protect(payload.encode())))
                if rows:
                    with self.connect() as c:
                        c.executemany('INSERT INTO events(scope,session,created,engine,kind,sealed) VALUES(?,?,?,?,?,?)',rows)
                        c.execute('DELETE FROM events WHERE created<?',(self.clock()-p.debug_journal_retention_days*86400,))
                        # Payload and row caps, in addition to retention; WAL/page
                        # overhead is separate from this bounded payload allowance.
                        c.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 50000)')
                        total=c.execute('SELECT coalesce(sum(length(sealed)),0) FROM events').fetchone()[0]
                        while total>32*1024*1024:
                            c.execute('DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY id LIMIT 256)')
                            total=c.execute('SELECT coalesce(sum(length(sealed)),0) FROM events').fetchone()[0]
                    self.written+=len(rows)
            except Exception:
                self.last_error='journal_write_failed';self.dropped+=len(batch)
            finally:
                for _ in batch:self.pending.task_done()

    async def flush(self,timeout=5):
        until=time.monotonic()+timeout
        while self.pending.unfinished_tasks and time.monotonic()<until:await asyncio.sleep(.01)
        return self.pending.unfinished_tasks==0

    async def close(self):
        await self.flush();self.stopping=True
        if self.worker:
            try:self.pending.put_nowait(None)
            except queue.Full:self.last_error='journal_shutdown_pending'
            await asyncio.to_thread(self.worker.join,2)

    def status(self,binding):
        p=self.owner.policy()
        return {'enabled':self.enabled(binding),'retention_days':p.debug_journal_retention_days,
                'encrypted':'Windows DPAPI','raw_audio':False,'semantic_memory':False,
                'queued':self.pending.qsize(),'written_this_process':self.written,
                'dropped_events':self.dropped,'error':self.last_error,'payload_limit_bytes':32*1024*1024}

    def sessions(self,scope):
        if not self.path.exists():return []
        self.purge()
        with self.connect() as c:
            rows=c.execute('SELECT session,min(created),max(created),count(*),max(engine) FROM events WHERE scope=? AND created>=? GROUP BY session ORDER BY max(created) DESC LIMIT 30',
                           (scope,self.clock()-self.owner.policy().debug_journal_retention_days*86400)).fetchall()
        return [{'session_id':r[0],'started_at':r[1],'last_event_at':r[2],'events':r[3],'engine':r[4]} for r in rows]

    def read(self,scope,session,*,before=None):
        if not self.path.exists():return {'events':[],'next_before':None}
        self.purge()
        with self.connect() as c:
            rows=c.execute('SELECT id,created,engine,kind,sealed FROM events WHERE scope=? AND session=? AND created>=? AND id<? ORDER BY id DESC LIMIT 200',
                           (scope,session,self.clock()-self.owner.policy().debug_journal_retention_days*86400,before or 2**63-1)).fetchall()
        result=[]
        for ident,created,engine,kind,sealed in reversed(rows):
            try:payload=json.loads(self.unprotect(sealed).decode())
            except Exception:payload={'data':{'error':'journal_decryption_failed'}}
            result.append({'id':ident,'created':created,'engine':engine,'kind':kind,**payload})
        return {'events':result,'next_before':rows[-1][0] if len(rows)==200 else None}

    def clear(self,scope,session=None):
        if not self.path.exists():return 0
        with self.connect() as c:
            c.execute('DELETE FROM events WHERE scope=?'+(' AND session=?' if session else ''),(scope,session) if session else (scope,))
            return c.total_changes
