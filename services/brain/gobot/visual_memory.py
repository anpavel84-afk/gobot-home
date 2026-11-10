"""Scoped, expiring visual continuity within GoBot memory, never a public cache.

No result grants access to history. A profile epoch mismatch, explicit new topic,
cancel or deletion invalidates the association. Temporary conversations stay RAM-only.
"""
import json,time

SCHEMA='''CREATE TABLE IF NOT EXISTS active_visual_subjects(
 owner TEXT,conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
 topic_id TEXT,turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
 profile_epoch TEXT,subject TEXT,anchors TEXT,source TEXT,confirmed REAL,expires REAL,
 PRIMARY KEY(owner,conversation_id));'''
TTL=3600

def active(memory,req,context):
    topic=context.get('topic',{})
    if req.new_topic or topic.get('outcome') in {'new_topic','ambiguous'}:return None
    if not req.remember:
        rows=[v for v in memory.transient.values() if v['owner']==req.device_id and v['conversation']==req.conversation_id
              and v.get('epoch')==req.profile_epoch and v.get('visual') and time.time()-v['updated']<TTL]
        return dict(rows[-1]['visual']) if rows else None
    with memory.connect() as c:
        row=c.execute('SELECT * FROM active_visual_subjects WHERE owner=? AND conversation_id=? AND profile_epoch IS ? AND expires>?',
            (req.device_id,req.conversation_id,req.profile_epoch,time.time())).fetchone()
    if not row or row['topic_id']!=topic.get('topic_id'):return None
    return {'subject':row['subject'],'anchors':json.loads(row['anchors']),'source':row['source'],
            'source_turn_id':row['turn_id'],'topic_id':row['topic_id'],'conversation_id':row['conversation_id'],'confirmed':row['confirmed'],'expires':row['expires']}

def confirmed(trace):
    for entry in reversed(trace):
        value=entry.get('visual_decision',{})
        if value.get('subject_confirmed') and value.get('visual_subject'):
            return {'subject':value['visual_subject'],'anchors':value.get('anchors') or [value['visual_subject']],
                    'source':value['subject_resolution_method'],'confirmed':time.time(),'expires':time.time()+TTL}
    return None

def finish(memory,c,req,status,provider,trace):
    from .archive import diagnostic
    if req.turn_id in memory.visual_cancelled:return
    if status!='completed' or req.new_topic:
        c.execute('DELETE FROM active_visual_subjects WHERE owner=? AND conversation_id=?',(req.device_id,req.conversation_id))
    if status!='completed' or diagnostic(req) or provider in {'mock','bridge:mock'}:return
    value=confirmed(trace)
    if not value:return
    topic=c.execute('SELECT topic_id,outcome FROM turn_topics WHERE turn_id=?',(req.turn_id,)).fetchone()
    if not topic or topic['outcome']=='side_action':return
    c.execute('INSERT OR REPLACE INTO active_visual_subjects VALUES(?,?,?,?,?,?,?,?,?,?)',
        (req.device_id,req.conversation_id,topic['topic_id'],req.turn_id,req.profile_epoch,value['subject'],
         json.dumps(value['anchors']),value['source'],value['confirmed'],value['expires']))
    c.execute('DELETE FROM active_visual_subjects WHERE expires<?',(time.time(),))
