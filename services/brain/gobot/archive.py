"""Local archive, scoped retrieval and topic state. No background model calls.

All queries authorize by owner before returning content. Extractive summaries
remain attributed source data, never accepted decisions or inferred facts.
"""
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SCHEMA='''
CREATE TABLE IF NOT EXISTS topics(id TEXT PRIMARY KEY,owner TEXT NOT NULL,label TEXT NOT NULL,created REAL,updated REAL,generation INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY,conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,topic_id TEXT REFERENCES topics(id),started REAL,last_seen REAL,closed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS archive_messages(message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,owner TEXT,topic_id TEXT REFERENCES topics(id),episode_id TEXT REFERENCES episodes(id) ON DELETE CASCADE,namespace TEXT,status TEXT);
CREATE TABLE IF NOT EXISTS turn_topics(turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,topic_id TEXT,episode_id TEXT,outcome TEXT,reason TEXT);
CREATE TABLE IF NOT EXISTS topic_summaries(topic_id TEXT REFERENCES topics(id) ON DELETE CASCADE,version INTEGER,content TEXT,source_message_ids TEXT,boundary INTEGER,generation INTEGER,created REAL,PRIMARY KEY(topic_id,version));
CREATE TABLE IF NOT EXISTS retrieval_chunks(id INTEGER PRIMARY KEY,message_id INTEGER UNIQUE REFERENCES messages(id) ON DELETE CASCADE,owner TEXT,topic_id TEXT,content TEXT,created REAL);
CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(content,content='retrieval_chunks',content_rowid='id',tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS chunks_insert AFTER INSERT ON retrieval_chunks BEGIN INSERT INTO archive_fts(rowid,content) VALUES(new.id,new.content); END;
CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON retrieval_chunks BEGIN INSERT INTO archive_fts(archive_fts,rowid,content) VALUES('delete',old.id,old.content); END;
CREATE TABLE IF NOT EXISTS context_runs(turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,topic_id TEXT,metadata TEXT,created REAL);
CREATE TABLE IF NOT EXISTS provider_sessions(turn_id TEXT PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,provider TEXT,session_id TEXT,mode TEXT,usage TEXT,provider_overhead_tokens INTEGER);
CREATE TABLE IF NOT EXISTS memory_facts(id INTEGER PRIMARY KEY,legacy_id INTEGER UNIQUE REFERENCES facts(id) ON DELETE CASCADE,owner TEXT,scope TEXT,content TEXT,provenance TEXT,confirmation TEXT,valid_from REAL,valid_until REAL,supersedes INTEGER REFERENCES memory_facts(id),deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS request_keys(owner TEXT,kind TEXT,external_id TEXT,turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,PRIMARY KEY(owner,kind,external_id));
CREATE TABLE IF NOT EXISTS utterance_drafts(owner TEXT,utterance_id TEXT,text TEXT,final INTEGER,updated REAL,PRIMARY KEY(owner,utterance_id));
CREATE TABLE IF NOT EXISTS speech_segments(turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,segment_id TEXT,sequence INTEGER,speech_text TEXT,status TEXT,played_ms REAL DEFAULT 0,PRIMARY KEY(turn_id,segment_id));
CREATE TABLE IF NOT EXISTS memory_jobs(topic_id TEXT PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,generation INTEGER,requested REAL);
CREATE TABLE IF NOT EXISTS pending_actions(id TEXT PRIMARY KEY,owner TEXT,conversation_id TEXT,kind TEXT,payload TEXT,expires REAL,status TEXT);
CREATE TABLE IF NOT EXISTS auxiliary_usage(day TEXT,kind TEXT,tokens INTEGER,attempts INTEGER,PRIMARY KEY(day,kind));
CREATE INDEX IF NOT EXISTS archive_owner_topic ON archive_messages(owner,topic_id,message_id);
CREATE INDEX IF NOT EXISTS chunks_scope ON retrieval_chunks(owner,topic_id,created);
'''

STOP={'это','что','как','мне','меня','мы','ты','его','она','они','оно','для','про','расскажи','пожалуйста','гобот','было','были','есть','или','уже','теперь','давай','наш','наша','наши','снова','вернись','вернемся','обсуждали','помнишь','разговор','по','этой','того','том','который','была','спроси','codex','antigravity'}
def terms(text):
    # Prefix FTS tolerates common Russian endings without downloading a model.
    return list(dict.fromkeys(w[:max(4,len(w)-3)] if len(w)>6 else w for w in re.findall(r'[а-яёa-z0-9]+',text.lower()) if len(w)>2 and w not in STOP))[:16]

def diagnostic(req):
    return req.conversation_id.startswith(('benchmark-','live-approved-','browser-fixture-','synthetic-','fixture-','ephemeral-check-')) or req.device_id in {'e2e','phone-demo'} or req.mode=='mock' or req.provider=='mock' or req.mode is None and req.provider not in {'codex','antigravity','google','gemini'}

class Archive:
    idle_seconds=600
    def __init__(self,memory):
        self.memory=memory
        # SQLite online backup includes committed WAL pages; never copy .sqlite alone.
        with memory.connect() as c:
            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='archive_messages'").fetchone()
            migration=c.execute('SELECT 1 FROM schema_migrations WHERE version=5').fetchone()
            if (not exists or not migration) and c.execute('SELECT count(*) FROM messages').fetchone()[0]:
                directory=Path(memory.path).parent/'backups';directory.mkdir(exist_ok=True)
                path=directory/('before-archive-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.sqlite')
                backup=sqlite3.connect(path)
                try:c.backup(backup);assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                finally:backup.close()
            c.executescript(SCHEMA)
            # Legacy conversations are explicitly unsegmented, not falsely labelled topics.
            for conv in c.execute('SELECT * FROM conversations WHERE id IN (SELECT conversation_id FROM messages WHERE id NOT IN (SELECT message_id FROM archive_messages))').fetchall():
                topic=str(uuid4());episode=str(uuid4());now=conv['created']
                c.execute('INSERT INTO topics VALUES(?,?,?,?,?,0)',(topic,conv['device_id'],'Архив · тема не размечена',now,now))
                c.execute('INSERT INTO episodes VALUES(?,?,?,?,?,1)',(episode,conv['id'],topic,now,now))
                rows=c.execute('SELECT m.*,t.provider AS turn_provider,t.status AS turn_status FROM messages m LEFT JOIN turns t ON t.id=m.turn_id WHERE m.conversation_id=? AND m.id NOT IN (SELECT message_id FROM archive_messages)',(conv['id'],)).fetchall()
                for row in rows:
                    namespace='diagnostic' if row['turn_provider'] in {'mock','bridge:mock',''} or row['turn_provider'] is None or conv['device_id']=='phone-demo' else 'production'
                    status=row['turn_status'] or 'unknown'
                    c.execute('INSERT INTO archive_messages VALUES(?,?,?,?,?,?)',(row['id'],conv['device_id'],topic,episode,namespace,status))
                    if namespace=='production' and status=='completed':self._index(c,row['id'],conv['device_id'],topic,row['content'],row['created'])
            c.execute("INSERT OR IGNORE INTO memory_facts(legacy_id,owner,scope,content,provenance,confirmation,valid_from) SELECT id,device_id,CASE WHEN device_id='family:home' THEN 'family' WHEN device_id LIKE 'personal:%' THEN 'personal' ELSE 'guest' END,content,provider,'explicit_consent',created FROM facts WHERE consent=1")
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(4,?)',(time.time(),))
            if not migration:
                c.execute("UPDATE archive_messages SET namespace='diagnostic' WHERE message_id IN (SELECT m.id FROM messages m JOIN conversations co ON co.id=m.conversation_id WHERE co.device_id IN ('e2e','phone-demo') OR co.id GLOB 'benchmark-*' OR co.id GLOB 'live-approved-*' OR co.id GLOB 'browser-fixture-*' OR co.id GLOB 'synthetic-*' OR co.id GLOB 'fixture-*' OR co.id GLOB 'ephemeral-check-*')")
                c.execute("DELETE FROM retrieval_chunks WHERE message_id IN (SELECT message_id FROM archive_messages WHERE namespace='diagnostic')")
                c.execute("DELETE FROM topic_summaries WHERE topic_id IN (SELECT topic_id FROM archive_messages WHERE namespace='diagnostic')")
                c.execute('INSERT INTO schema_migrations VALUES(5,?)',(time.time(),))

    @staticmethod
    def _index(c,message,owner,topic,content,created):
        c.execute('INSERT OR IGNORE INTO retrieval_chunks(message_id,owner,topic_id,content,created) VALUES(?,?,?,?,?)',(message,owner,topic,content,created))

    def search(self,owner,query,limit=5,since=None,until=None,topic=None):
        tokens=terms(query)
        with self.memory.connect() as c:
            filters='r.owner=?';args=[owner]
            if since is not None:filters+=' AND r.created>=?';args.append(since)
            if until is not None:filters+=' AND r.created<=?';args.append(until)
            if topic:filters+=' AND r.topic_id=?';args.append(topic)
            if not tokens:return []
            expression=' OR '.join('"'+token+'"*' for token in tokens)
            rows=c.execute('SELECT r.*,bm25(archive_fts) AS rank FROM archive_fts JOIN retrieval_chunks r ON r.id=archive_fts.rowid WHERE archive_fts MATCH ? AND '+filters+' ORDER BY rank,r.created DESC LIMIT ?', [expression,*args,min(limit,20)]).fetchall()
            return [dict(row) for row in rows]

    def period(self,owner,since,until,limit=20):
        with self.memory.connect() as c:
            # Cover distinct topics/time buckets, rather than a topical top-k.
            rows=c.execute('SELECT r.* FROM retrieval_chunks r WHERE owner=? AND created>=? AND created<=? GROUP BY topic_id,CAST(created/86400 AS INTEGER) ORDER BY created LIMIT ?',(owner,since,until,min(limit,30))).fetchall()
            return [dict(r) for r in rows]

    def source(self,owner,message_id):
        with self.memory.connect() as c:
            row=c.execute("SELECT m.id,m.role,m.content,m.created FROM messages m JOIN archive_messages a ON a.message_id=m.id WHERE m.id=? AND a.owner=? AND a.namespace='production' AND a.status='completed'",(message_id,owner)).fetchone()
            return dict(row) if row else None

    def begin(self,c,req,message_id):
        now=time.time();owner=req.device_id
        current=c.execute('SELECT e.*,t.label FROM episodes e JOIN topics t ON t.id=e.topic_id WHERE e.conversation_id=? ORDER BY e.last_seen DESC LIMIT 1',(req.conversation_id,)).fetchone()
        text=req.text.lower();outcome='continue' if current else 'new_topic';reason='active_topic' if current else 'first_turn';topic=current['topic_id'] if current else None
        explicit_new=bool(getattr(req,'new_topic',False) or re.search(r'новая тема|новый разговор|поговорим о другом',text))
        side=bool(re.match(r'^(?:гобот[,! ]+)?(?:поставь|запусти|отмени|останови)\s+таймер',text))
        pending=c.execute("SELECT 1 FROM pending_actions WHERE owner=? AND conversation_id=? AND kind='timer_duration' AND status='pending' AND expires>?",(owner,req.conversation_id,now)).fetchone()
        if pending and re.fullmatch(r'(?:на )?(?:\d+|одну|две|три|четыре|пять|десять)\s+(?:минут\w*|секунд\w*|час\w*)[.!]?',text):side=True
        resume=bool(re.search(r'верн[её]мся|вернись|помнишь|обсуждали|говорили.*(?:вчера|недел)',text))
        if explicit_new:topic=None;outcome='new_topic';reason='explicit_new_topic'
        elif side:outcome='side_action';reason='timer_preserves_topic'
        elif resume:
            found=self.search(owner,req.text,5)
            if found:topic=found[0]['topic_id'];outcome='resume_topic';reason='scoped_fts_match'
            else:outcome='ambiguous';reason='no_matching_archive_source'
        elif re.fullmatch(r'(?:а )?(?:он|она|оно|они|это)(?:\?|\.)?',text.strip()) and not current:
            outcome='ambiguous';reason='reference_without_active_topic'
        elif current and len(terms(text))>=2:
            recent=c.execute("SELECT m.content FROM messages m JOIN archive_messages a ON a.message_id=m.id WHERE a.topic_id=? AND a.owner=? AND m.role='user' ORDER BY m.id DESC LIMIT 2",(topic,owner)).fetchall()
            if recent and not set(terms(text))&set(terms(current['label']+' '+' '.join(r[0] for r in recent))) and not re.match(r'^(?:а |почему|как именно|подробнее|объясни|продолж|спроси|что думает)',text):
                topic=None;outcome='new_topic';reason='topic_entities_changed'
        if not topic:
            topic=str(uuid4());c.execute('INSERT INTO topics VALUES(?,?,?,?,?,0)',(topic,owner,req.text[:100],now,now))
        fresh=not current or current['topic_id']!=topic or now-current['last_seen']>self.idle_seconds or current['closed']
        if fresh:
            if current:c.execute('UPDATE episodes SET closed=1 WHERE id=?',(current['id'],))
            episode=str(uuid4());c.execute('INSERT INTO episodes VALUES(?,?,?,?,?,0)',(episode,req.conversation_id,topic,now,now))
        else:episode=current['id'];c.execute('UPDATE episodes SET last_seen=? WHERE id=?',(now,episode))
        c.execute('UPDATE topics SET updated=? WHERE id=?',(now,topic))
        c.execute('INSERT INTO turn_topics VALUES(?,?,?,?,?)',(req.turn_id,topic,episode,outcome,reason))
        c.execute('INSERT INTO archive_messages VALUES(?,?,?,?,?,?)',(message_id,owner,topic,episode,'diagnostic' if diagnostic(req) else 'production','running'))

    def finish(self,c,req,status,provider):
        topic=c.execute('SELECT * FROM turn_topics WHERE turn_id=?',(req.turn_id,)).fetchone()
        if not topic:return
        namespace='diagnostic' if diagnostic(req) or provider in {'mock','bridge:mock'} else 'production'
        for row in c.execute('SELECT * FROM messages WHERE turn_id=?',(req.turn_id,)).fetchall():
            c.execute('INSERT OR REPLACE INTO archive_messages VALUES(?,?,?,?,?,?)',(row['id'],req.device_id,topic['topic_id'],topic['episode_id'],namespace,status))
            if namespace=='production' and status=='completed' and topic['outcome']!='side_action':self._index(c,row['id'],req.device_id,topic['topic_id'],row['content'],row['created'])
        if namespace=='production' and status=='completed':
            generation=c.execute('SELECT generation FROM topics WHERE id=?',(topic['topic_id'],)).fetchone()[0]
            # A single local job per changed topic, bounded globally. No paid worker.
            if c.execute('SELECT count(*) FROM memory_jobs').fetchone()[0]<32:
                c.execute('INSERT OR REPLACE INTO memory_jobs VALUES(?,?,?)',(topic['topic_id'],generation,time.time()))

    def topic_context(self,req):
        with self.memory.connect() as c:
            route=c.execute('SELECT tt.*,t.label FROM turn_topics tt JOIN topics t ON t.id=tt.topic_id WHERE turn_id=?',(req.turn_id,)).fetchone()
            if not route:return {}
            rows=c.execute("SELECT m.id,m.role,m.content,m.provider FROM messages m JOIN archive_messages a ON a.message_id=m.id WHERE a.owner=? AND a.topic_id=? AND a.namespace='production' AND a.status='completed' AND m.turn_id!=? ORDER BY m.id DESC LIMIT 12",(req.device_id,route['topic_id'],req.turn_id)).fetchall()
            summary=c.execute('SELECT * FROM topic_summaries WHERE topic_id=? ORDER BY version DESC LIMIT 1',(route['topic_id'],)).fetchone()
            facts=[dict(r) for r in c.execute("SELECT id,content,scope,provenance,confirmation,valid_from,supersedes FROM memory_facts WHERE owner IN (?, 'family:home') AND deleted=0 AND confirmation='explicit_consent' AND (valid_until IS NULL OR valid_until>?) ORDER BY id DESC LIMIT 20",(req.device_id,time.time()))]
            pending=c.execute("SELECT id,kind,expires FROM pending_actions WHERE owner=? AND conversation_id=? AND status='pending' AND expires>? ORDER BY expires DESC LIMIT 1",(req.device_id,req.conversation_id,time.time())).fetchone()
        retrieved=self.search(req.device_id,req.text,5)
        return {'messages':[dict(r) for r in reversed(rows)],'summary':summary['content'] if summary else '',
                'summary_sources':json.loads(summary['source_message_ids']) if summary else [],'facts':facts,
                'fact_sources':[r['id'] for r in facts], 'original_question':'','retrieved':retrieved,'topic':dict(route),'pending_action':dict(pending) if pending else None}

    def maintain_one(self):
        """Incremental attributed excerpts only. Transaction guards deletion/revisions."""
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            job=c.execute('SELECT * FROM memory_jobs ORDER BY requested LIMIT 1').fetchone()
            if not job:return
            c.execute('DELETE FROM memory_jobs WHERE topic_id=?',(job['topic_id'],))
            topic=c.execute('SELECT generation FROM topics WHERE id=?',(job['topic_id'],)).fetchone()
            if not topic or topic[0]!=job['generation']:return
            previous=c.execute('SELECT * FROM topic_summaries WHERE topic_id=? ORDER BY version DESC LIMIT 1',(job['topic_id'],)).fetchone()
            boundary=previous['boundary'] if previous else 0
            rows=c.execute("SELECT m.id,m.role,m.content FROM messages m JOIN archive_messages a ON a.message_id=m.id WHERE a.topic_id=? AND a.namespace='production' AND a.status='completed' AND m.id>? ORDER BY m.id LIMIT 16",(job['topic_id'],boundary)).fetchall()
            if len(rows)<8:return
            excerpts=[{'id':r['id'],'role':r['role'],'excerpt':r['content'][:180]} for r in rows]
            prior=json.loads(previous['content']).get('source_excerpts',[]) if previous else []
            selected=(prior+excerpts)[-8:]
            content=json.dumps({'kind':'attributed_excerpts_not_inferred_decisions','source_excerpts':selected,'decisions':[],'open_questions':[]},ensure_ascii=False)
            c.execute('INSERT INTO topic_summaries VALUES(?,?,?,?,?,?,?)',(job['topic_id'],(previous['version']+1) if previous else 1,content,json.dumps([r['id'] for r in selected]),rows[-1]['id'],job['generation'],time.time()))

    def record_context(self,req,packet,provider):
        with self.memory.connect() as c:
            c.execute('INSERT OR REPLACE INTO context_runs VALUES(?,?,?,?)',(req.turn_id,packet.get('topic',{}).get('topic_id'),json.dumps(packet['_context_meta']),time.time()))
            c.execute('INSERT OR REPLACE INTO provider_sessions VALUES(?,?,NULL,?,NULL,NULL)',(req.turn_id,provider,'fresh_ephemeral'))

    def record_usage(self,req,usage,session_id=None):
        with self.memory.connect() as c:c.execute('UPDATE provider_sessions SET usage=?,session_id=? WHERE turn_id=?',(json.dumps(usage) if usage else None,session_id,req.turn_id))

    def inspect(self,owner,conversation):
        with self.memory.connect() as c:
            topic=c.execute('SELECT t.id,t.label,e.id AS episode_id FROM episodes e JOIN topics t ON t.id=e.topic_id WHERE e.conversation_id=? AND t.owner=? ORDER BY e.last_seen DESC LIMIT 1',(conversation,owner)).fetchone()
            facts=[dict(r) for r in c.execute('SELECT id,content,scope,provenance,confirmation FROM memory_facts WHERE owner IN (?,\'family:home\') AND deleted=0 ORDER BY id DESC LIMIT 50',(owner,))]
            run=c.execute('SELECT cr.metadata,cr.turn_id,ps.session_id,ps.mode,ps.usage FROM context_runs cr JOIN turns tr ON tr.id=cr.turn_id JOIN conversations co ON co.id=tr.conversation_id LEFT JOIN provider_sessions ps ON ps.turn_id=tr.id WHERE co.id=? AND co.device_id=? ORDER BY cr.created DESC LIMIT 1',(conversation,owner)).fetchone()
            return {'topic':dict(topic) if topic else None,'facts':facts,'context':dict(run) if run else None,'auxiliary_model_tokens':0,'auxiliary_limit_fraction':0.1,'auxiliary_absolute_limit':2000,'paid_memory_processing_enabled':False}

    def revise_fact(self,owner,fact_id,content=None):
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM memory_facts WHERE id=? AND owner=? AND deleted=0',(fact_id,owner)).fetchone()
            if not old:return False
            c.execute('UPDATE memory_facts SET deleted=1,content=\'\',valid_until=? WHERE id=?',(time.time(),fact_id))
            if old['legacy_id']:
                c.execute('UPDATE memory_facts SET legacy_id=NULL WHERE id=?',(fact_id,))
                c.execute('DELETE FROM facts WHERE id=?',(old['legacy_id'],))
            if content:
                c.execute('INSERT INTO memory_facts(owner,scope,content,provenance,confirmation,valid_from,supersedes) VALUES(?,?,?,?,?,?,?)',(owner,old['scope'],content,'owner_correction','explicit_consent',time.time(),fact_id))
            # Facts are never mined from messages. Clear derived summaries/jobs to
            # prevent any stale cached copy after correction/deletion.
            c.execute('DELETE FROM topic_summaries WHERE topic_id IN (SELECT id FROM topics WHERE owner=?)',(owner,))
            c.execute('DELETE FROM memory_jobs WHERE topic_id IN (SELECT id FROM topics WHERE owner=?)',(owner,))
            c.execute('UPDATE topics SET generation=generation+1 WHERE owner=?',(owner,))
            return True

    def utterance(self,owner,ident,text,final=False):
        with self.memory.connect() as c:
            previous=c.execute('SELECT final FROM utterance_drafts WHERE owner=? AND utterance_id=?',(owner,ident)).fetchone()
            if previous and previous[0]:return False
            c.execute('INSERT OR REPLACE INTO utterance_drafts VALUES(?,?,?,?,?)',(owner,ident,text,int(final),time.time()))
            return True

    def speech(self,req,segment_id,sequence,text,status):
        if not req.remember:return
        with self.memory.connect() as c:
            c.execute('INSERT INTO speech_segments(turn_id,segment_id,sequence,speech_text,status) VALUES(?,?,?,?,?) ON CONFLICT(turn_id,segment_id) DO UPDATE SET status=excluded.status',(req.turn_id,segment_id,sequence,text,status))

    def playback(self,owner,turn,segment,milliseconds):
        with self.memory.connect() as c:
            c.execute("UPDATE speech_segments SET played_ms=MAX(played_ms,?),status='client_playback_reported' WHERE turn_id=? AND segment_id=? AND turn_id IN (SELECT t.id FROM turns t JOIN conversations co ON co.id=t.conversation_id WHERE co.device_id=?)",(max(0,min(milliseconds,120000)),turn,segment,owner))

    def forget_conversation(self,owner,conversation):
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            exists=c.execute('SELECT 1 FROM conversations WHERE id=? AND device_id=?',(conversation,owner)).fetchone()
            if not exists:return False
            topics=[r[0] for r in c.execute('SELECT DISTINCT topic_id FROM episodes WHERE conversation_id=?',(conversation,))]
            for topic in topics:
                c.execute('UPDATE topics SET generation=generation+1 WHERE id=?',(topic,))
                c.execute('DELETE FROM topic_summaries WHERE topic_id=?',(topic,));c.execute('DELETE FROM memory_jobs WHERE topic_id=?',(topic,))
            c.execute('DELETE FROM pending_actions WHERE owner=? AND conversation_id=?',(owner,conversation))
            c.execute('DELETE FROM conversations WHERE id=?',(conversation,))
            for topic in topics:c.execute('DELETE FROM topics WHERE id=? AND NOT EXISTS (SELECT 1 FROM episodes WHERE topic_id=?)',(topic,topic))
            return True

    def forget_owner(self,owner):
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM conversations WHERE device_id=?',(owner,))
            c.execute('DELETE FROM topics WHERE owner=?',(owner,))
            c.execute('DELETE FROM memory_facts WHERE owner=?',(owner,))
            c.execute('DELETE FROM facts WHERE device_id=?',(owner,))
            c.execute('DELETE FROM utterance_drafts WHERE owner=?',(owner,))
            c.execute('DELETE FROM pending_actions WHERE owner=?',(owner,))
        with self.memory.transient_lock:
            self.memory.transient={k:v for k,v in self.memory.transient.items() if v['owner']!=owner}

    def rename_topic(self,owner,topic,label):
        with self.memory.connect() as c:return c.execute('UPDATE topics SET label=?,updated=? WHERE id=? AND owner=?',(label[:100],time.time(),topic,owner)).rowcount==1

    def reserve_auxiliary(self,kind,tokens,*,enabled=False,fraction=.1,absolute=2000):
        """Fail closed without measured provider usage. Reserve before each attempt.
        This gate is not connected to an autonomous model worker.
        """
        if not enabled or kind not in {'summary','extraction','classification'} or not isinstance(tokens,int) or tokens<=0:return False
        if not 0<=fraction<=.1 or not 0<=absolute<=100000:return False
        now=datetime.now(timezone.utc);day=now.strftime('%Y-%m-%d');start=now.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        with self.memory.connect() as c:
            c.execute('BEGIN IMMEDIATE');observed=0
            for row in c.execute('SELECT ps.usage FROM provider_sessions ps JOIN turns t ON t.id=ps.turn_id WHERE t.updated>=? AND ps.usage IS NOT NULL',(start,)):
                usage=json.loads(row[0]);observed+=usage.get('total_tokens',usage.get('totalTokens',0))
            allowance=min(int(observed*fraction),absolute)
            used=c.execute('SELECT COALESCE(sum(tokens),0) FROM auxiliary_usage WHERE day=?',(day,)).fetchone()[0]
            if used+tokens>allowance:return False
            c.execute('INSERT INTO auxiliary_usage VALUES(?,?,?,1) ON CONFLICT(day,kind) DO UPDATE SET tokens=tokens+excluded.tokens,attempts=attempts+1',(day,kind,tokens))
            return True
