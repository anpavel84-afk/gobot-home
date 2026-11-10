"""Local opt-in family profiles, encrypted voice vectors and conservative matching.
Cosine similarity is not probability. No production thresholds exist before calibration.
"""
import hashlib,hmac,json,math,secrets,time
from uuid import uuid4
from .secrets_store import _dpapi

SCHEMA='''
CREATE TABLE IF NOT EXISTS family_profiles(id TEXT PRIMARY KEY,name TEXT,age TEXT,avatar TEXT,
 consent INTEGER,parent_consent INTEGER,enabled INTEGER,pin_salt BLOB,pin_hash BLOB,epoch TEXT);
CREATE TABLE IF NOT EXISTS voice_vectors(id TEXT PRIMARY KEY,profile_id TEXT REFERENCES family_profiles(id) ON DELETE CASCADE,
 kind TEXT,vector BLOB,seconds REAL,created REAL);
CREATE TABLE IF NOT EXISTS speaker_calibration(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT);
'''

def normalized(vector):
    if not isinstance(vector,list) or not 2<=len(vector)<=512 or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in vector):raise ValueError('invalid_embedding')
    norm=math.sqrt(sum(x*x for x in vector))
    if norm<1e-8:raise ValueError('empty_embedding')
    return [x/norm for x in vector]
def cosine(a,b):
    if len(a)!=len(b):raise ValueError('embedding_model_mismatch')
    return sum(x*y for x,y in zip(a,b))
def pin_hash(pin,salt):
    if not isinstance(pin,str) or not 6<=len(pin)<=128:raise ValueError('pin_minimum_6_characters')
    return hashlib.scrypt(pin.encode(),salt=salt,n=16384,r=8,p=1)

class Family:
    def __init__(self,memory):
        self.memory=memory
        with memory.connect() as c:
            c.executescript(SCHEMA)
            c.execute('INSERT OR IGNORE INTO schema_migrations VALUES(2,?)',(time.time(),))
    def profiles(self):
        with self.memory.connect() as c:
            return [dict(row) for row in c.execute('''SELECT p.id,p.name,p.age,p.avatar,p.consent,p.parent_consent,p.enabled,
                (SELECT count(*) FROM voice_vectors WHERE profile_id=p.id AND kind='enroll') AS segments,
                coalesce((SELECT sum(seconds) FROM voice_vectors WHERE profile_id=p.id AND kind='enroll'),0) AS seconds
                FROM family_profiles p ORDER BY p.name''')]
    def create(self,name,age,pin,avatar='',consent=False,parent_consent=False):
        if not isinstance(consent,bool) or not isinstance(parent_consent,bool):raise ValueError('explicit_boolean_consent_required')
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or age not in {'adult','child'} or not isinstance(avatar,str) or len(avatar)>24:raise ValueError('invalid_profile')
        if consent and age=='child' and not parent_consent:raise ValueError('parent_consent_required')
        salt=secrets.token_bytes(16);hashed=pin_hash(pin,salt);ident=str(uuid4())
        with self.memory.connect() as c:
            if c.execute('SELECT count(*) FROM family_profiles').fetchone()[0]>=10:raise ValueError('profile_limit')
            c.execute('INSERT INTO family_profiles VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,name.strip(),age,avatar,int(bool(consent)),int(bool(parent_consent)),0,salt,hashed,str(uuid4())))
        return {'id':ident}
    def verify_pin(self,ident,pin):
        with self.memory.connect() as c:row=c.execute('SELECT * FROM family_profiles WHERE id=?',(ident,)).fetchone()
        if not row or not hmac.compare_digest(pin_hash(pin,row['pin_salt']),row['pin_hash']):raise ValueError('invalid_profile_or_pin')
        return {'id':ident,'epoch':row['epoch'],'name':row['name']}
    def session_valid(self,ident,epoch):
        with self.memory.connect() as c:row=c.execute('SELECT epoch FROM family_profiles WHERE id=?',(ident,)).fetchone()
        return bool(row and hmac.compare_digest(row[0],epoch))
    def enable(self,ident,enabled):
        with self.memory.connect() as c:
            row=c.execute('SELECT * FROM family_profiles WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('unknown_profile')
            if enabled and (not row['consent'] or row['age']=='child' and not row['parent_consent']):raise ValueError('biometric_consent_required')
            c.execute('UPDATE family_profiles SET enabled=? WHERE id=?',(int(bool(enabled)),ident))
            c.execute('DELETE FROM speaker_calibration')
    def store(self,ident,vector,seconds,kind='enroll'):
        if kind not in {'enroll','validation','unknown'}:raise ValueError('invalid_sample_kind')
        if kind!='unknown':
            profile=next((p for p in self.profiles() if p['id']==ident),None)
            if not profile or not profile['consent'] or profile['age']=='child' and not profile['parent_consent']:raise ValueError('biometric_consent_required')
            if seconds<6:raise ValueError('enrollment_segment_too_short')
        elif ident is not None:raise ValueError('unknown_sample_profile_must_be_empty')
        vector=normalized(vector);encrypted=_dpapi(json.dumps(vector).encode())
        with self.memory.connect() as c:
            if c.execute('SELECT count(*) FROM voice_vectors WHERE profile_id IS ? AND kind=?',(ident,kind)).fetchone()[0]>=12:raise ValueError('sample_limit')
            c.execute('INSERT INTO voice_vectors VALUES(?,?,?,?,?,?)',(str(uuid4()),ident,kind,encrypted,seconds,time.time()))
            c.execute('DELETE FROM speaker_calibration')
    def vectors(self):
        with self.memory.connect() as c:rows=c.execute('SELECT profile_id,kind,vector FROM voice_vectors').fetchall()
        return [{'profile_id':r[0],'kind':r[1],'vector':json.loads(_dpapi(r[2],decrypt=True))} for r in rows]
    def reset_voice(self,ident):
        with self.memory.connect() as c:
            c.execute('DELETE FROM voice_vectors WHERE profile_id IS ?',(ident,));c.execute('DELETE FROM speaker_calibration')
        with self.memory.connect() as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def delete(self,ident):
        self.memory.archive.forget_owner('personal:'+ident)
        with self.memory.connect() as c:
            c.execute('DELETE FROM family_profiles WHERE id=?',(ident,));c.execute('DELETE FROM speaker_calibration')
            c.execute('DELETE FROM conversations WHERE device_id=?',('personal:'+ident,))
            c.execute('DELETE FROM facts WHERE device_id=?',('personal:'+ident,))
        with self.memory.connect() as c:c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def calibration(self):
        with self.memory.connect() as c:r=c.execute('SELECT data FROM speaker_calibration WHERE id=1').fetchone()
        return json.loads(r[0]) if r else None
    def calibrate(self):
        profiles={p['id']:p for p in self.profiles() if p['enabled']}
        data=self.vectors();templates={ident:[v['vector'] for v in data if v['profile_id']==ident and v['kind']=='enroll'] for ident in profiles}
        if len(profiles)<2 or any(len(templates[k])<3 or profiles[k]['seconds']<30 for k in profiles):raise ValueError('need_3_enrollment_segments_and_30_seconds_per_profile')
        validation=[v for v in data if v['kind']=='validation' and v['profile_id'] in profiles]
        if any(sum(v['profile_id']==k for v in validation)<2 for k in profiles):raise ValueError('need_2_held_out_validation_segments_per_profile')
        unknown=[v for v in data if v['kind']=='unknown']
        if not unknown:raise ValueError('need_opt_in_unknown_speaker_validation')
        positives=[];negatives=[];gaps=[]
        for sample in validation+unknown:
            scores={k:max(cosine(sample['vector'],ref) for ref in refs) for k,refs in templates.items()}
            own=sample['profile_id'] if sample['kind']=='validation' else None
            for k,score in scores.items():(positives if k==own else negatives).append(score)
            if own:gaps.append(scores[own]-max(score for k,score in scores.items() if k!=own))
        if min(positives)<=max(negatives) or min(gaps)<=0:raise ValueError('calibration_scores_overlap_recognition_disabled')
        result={'threshold':(min(positives)+max(negatives))/2,'margin':min(gaps),
                'min_genuine':min(positives),'max_impostor':max(negatives),'validation_segments':len(validation),
                'unknown_segments':len(unknown),'source':'owner-labelled-held-out-embeddings','created':time.time(),
                'accuracy_claim':False}
        with self.memory.connect() as c:c.execute('INSERT OR REPLACE INTO speaker_calibration VALUES(1,?)',(json.dumps(result),))
        return result
    def identify(self,vector):
        calibration=self.calibration()
        if not calibration:return {'state':'unknown','reason':'calibration_required','personal_authorized':False}
        vector=normalized(vector);profiles={p['id']:p for p in self.profiles() if p['enabled']}
        templates=self.vectors();scores=[]
        for ident,profile in profiles.items():
            refs=[v['vector'] for v in templates if v['profile_id']==ident and v['kind']=='enroll']
            if refs:scores.append((max(cosine(vector,ref) for ref in refs),ident,profile['name']))
        scores.sort(reverse=True)
        if not scores or scores[0][0]<calibration['threshold']:return {'state':'unknown','personal_authorized':False}
        best=scores[0];gap=best[0]-scores[1][0] if len(scores)>1 else 2
        if len(scores)>1 and (scores[1][0]>=calibration['threshold'] or gap+1e-8<calibration['margin']):return {'state':'ambiguous','similarity':best[0],'personal_authorized':False}
        return {'state':'recognized','profile_id':best[1],'name':best[2],'similarity':best[0],
                'personal_authorized':False,'requires_pin_for_personal_history':True,'experimental':True}
