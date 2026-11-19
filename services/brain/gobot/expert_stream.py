"""Typed, backwards-compatible answer deltas across the signed Host Bridge.

Only a verified assistant answer is eligible for speech. Transport strings without
metadata remain usable by legacy text consumers, but are never trusted by the
expert narrator. This module contains no provider access or authorization policy.
"""

ANSWER_PHASES = frozenset({'partial_answer', 'final_answer'})
EXPERT_CUE_ID = 'service.expert.accepted'
EXPERT_CUE_TEXT = 'Передаю задачу эксперту'


class AnswerDelta(str):
    def __new__(cls, text, *, item_id=None, phase=None, job_id=None,
                verified=False, completed=False):
        value = super().__new__(cls, text)
        value.item_id = item_id
        value.phase = phase
        value.job_id = job_id
        value.verified = bool(verified)
        value.completed = bool(completed)
        return value

    @property
    def speakable(self):
        return self.verified and self.phase in ANSWER_PHASES

    def metadata(self):
        return {'item_id': self.item_id, 'phase': self.phase,
                'job_id': self.job_id, 'verified': self.verified,
                'completed': self.completed}


def conversation_binding(session):
    """A socket ID is intentionally not part of a logical conversation identity."""
    offer = session.offer
    access = session.access
    return (getattr(offer, 'device_id', None), getattr(offer, 'client_id', None),
            getattr(offer, 'profile_epoch', None), offer.conversation_id,
            access.effective_scope, getattr(access, 'context_conversation', None),
            getattr(access, 'confirmed_profile_id', None),
            getattr(offer, 'confirmed_profile_epoch', None))


def expert_service_cache(root=None):
    """Fixed public service phrase using the existing cache, never personal text.

    Adding the entry in this private cache instance preserves the existing reviewed
    100-opening catalog. Preparation must still use separately admitted generation;
    lookup below never calls a model or creates a file.
    """
    from .speech_openings import OpeningCache
    cache=OpeningCache(root)
    cache.entries={**cache.entries,EXPERT_CUE_ID:{'id':EXPERT_CUE_ID,
        'text':EXPERT_CUE_TEXT,'category':'service','enabled':True}}
    return cache


def load_expert_service_cue(root=None):
    """Return validated public PCM or an honest missing result; no synthesis."""
    import hashlib
    import io
    import json
    import wave
    from .audio import TTS_MODEL
    result={'status':'missing','id':EXPERT_CUE_ID,'text':EXPERT_CUE_TEXT,
            'voice':'marin','model':TTS_MODEL,'runtime_generation':False}
    cache=expert_service_cache(root)
    clip=cache.clip('marin',EXPERT_CUE_ID)
    if not clip:return result
    try:
        raw=clip['path'].read_bytes()
        meta=json.loads(clip['path'].with_suffix('.json').read_text(encoding='utf-8'))
        sha=hashlib.sha256(raw).hexdigest()
        if (sha!=meta.get('sha256') or meta.get('text')!=EXPERT_CUE_TEXT or
                meta.get('voice')!='marin' or meta.get('model')!=TTS_MODEL):return result
        with wave.open(io.BytesIO(raw),'rb') as wav:
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=24000:return result
            pcm=wav.readframes(wav.getnframes())
        return {**result,'status':'ready','pcm':pcm,'sample_rate':24000,
                'duration_seconds':len(pcm)/48000,'sha256':sha}
    except (OSError,ValueError,KeyError,wave.Error,EOFError):return result
