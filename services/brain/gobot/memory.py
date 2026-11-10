import sqlite3, json, hashlib, time
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
"""
class Conflict(Exception): pass
class Memory:
    def __init__(self,path):
        self.path=path; Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript(SCHEMA);c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(1,?)",(time.time(),))
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
    def start(self,req):
        payload=req.model_dump(exclude={"correlation_id"});digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT * FROM turns WHERE id=?",(req.turn_id,)).fetchone()
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
            c.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'user',?,'input',?,?)",(req.conversation_id,req.text,req.turn_id,time.time()))
    def finish(self,req,status,text,provider,trace):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=c.execute("SELECT status FROM turns WHERE id=?",(req.turn_id,)).fetchone()
            if not row or row[0]!='running': return
            c.execute("UPDATE turns SET status=?,result=?,provider=?,trace=?,updated=? WHERE id=?",(status,text,provider,json.dumps(trace),time.time(),req.turn_id))
            c.execute("UPDATE sessions SET active=0,last_seen=? WHERE conversation_id=?",(time.time(),req.conversation_id))
            if status=='completed':
                c.execute("INSERT INTO messages(conversation_id,role,content,provider,turn_id,created) VALUES(?,'assistant',?,?,?,?)",(req.conversation_id,text,provider,req.turn_id,time.time()))
                rows=c.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 6",(req.conversation_id,)).fetchall()
                # Deterministic extractive summary, never presented as a model-generated summary.
                summary='\n'.join(f"{r[0]}: {r[1][:300]}" for r in reversed(rows))[-1800:]
                c.execute("INSERT OR REPLACE INTO summaries VALUES(?,?,'extractive')",(req.conversation_id,summary))
    def context(self,req):
        with self.connect() as c:
            msgs=[dict(x) for x in c.execute("SELECT role,content,provider FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 12",(req.conversation_id,))][::-1]
            row=c.execute("SELECT content FROM summaries WHERE conversation_id=?",(req.conversation_id,)).fetchone()
            facts=[x[0] for x in c.execute("SELECT content FROM facts WHERE device_id=? AND consent=1",(req.device_id,))]
            return {'messages':msgs,'summary':row[0] if row else '', 'facts':facts}
    def status(self,turn):
        with self.connect() as c:
            r=c.execute("SELECT id,status,provider,updated FROM turns WHERE id=?",(turn,)).fetchone();return dict(r) if r else None
    def add_fact(self,device,text,consent,provider='owner'):
        if consent is not True:raise ValueError('Explicit consent required')
        with self.connect() as c:c.execute("INSERT INTO facts(device_id,content,consent,provider,created) VALUES(?,?,1,?,?)",(device,text,provider,time.time()))
    def purge(self,conversation=None,older_than=None):
        if conversation is None and older_than is None:raise ValueError('Explicit purge scope required')
        with self.connect() as c:
            if conversation:c.execute("DELETE FROM conversations WHERE id=?",(conversation,))
            else:c.execute("DELETE FROM conversations WHERE created<?",(older_than,))
        with self.connect() as c:c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    def forget_facts(self,device):
        with self.connect() as c:c.execute("DELETE FROM facts WHERE device_id=?",(device,))
