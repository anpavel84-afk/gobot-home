"""Bounded local PCM mirror into the existing opt-in SpeakerIdentity worker."""
import asyncio,time
from uuid import uuid4

class NativeSpeakerIdentity:
    def __init__(self,session):
        self.session=session;self.segments={};self.current=None;self.last_profile=None
    def status(self):
        iam=self.session.manager.identity;identity=iam.speaker_identity;family=iam.family
        if not self.session.offer.speaker_consent:return {'enabled':False,'ready':False,'reason':'local_speaker_consent_required'}
        if not identity or not identity.engine.installed():return {'enabled':True,'ready':False,'reason':'speaker_model_not_installed'}
        profiles=family.profiles()
        eligible=[p for p in profiles if p['enabled'] and p['consent'] and (p['age']!='child' or p['parent_consent'])]
        if not eligible:return {'enabled':True,'ready':False,'reason':'no_enrolled_consenting_profiles'}
        if not family.calibration():return {'enabled':True,'ready':False,'reason':'calibration_required'}
        return {'enabled':True,'ready':True,'reason':None,'experimental':True,'private_authorization':False}
    def begin(self):
        # Server-generated nonce binds audio to one live capture, not an arbitrary profile ID.
        ident=str(uuid4());self.current=ident
        self.segments={ident:{'submitted':False,'created':time.monotonic(),'revision':len(self.session.turns)+1}}
        return ident
    async def accept(self,segment,pcm):
        s=self.session;entry=self.segments.get(segment)
        if s.closed or segment!=self.current or not entry or entry['submitted'] or time.monotonic()-entry['created']>65:raise ValueError('stale_or_duplicate_speaker_segment')
        entry['submitted']=True
        if len(pcm)>192000 or len(pcm)%2:raise ValueError('speaker_pcm_limit')
        state=await asyncio.to_thread(self.status)
        if not state['ready']:
            s.emit('speaker_identity',state='unknown',reason=state['reason'],personal_authorized=False)
            return {'accepted':False,'reason':state['reason']}
        async def identify():
            started=time.monotonic()
            result=await s.manager.identity.speaker_identity.identify(pcm)
            # An old reply/segment may never change the identity of a later turn.
            if s.closed or self.current!=segment:return
            profile=result.get('profile_id') if result.get('state')=='recognized' else None
            changed=bool(self.last_profile and profile!=self.last_profile)
            self.last_profile=profile
            s.emit('speaker_identity',state=result.get('state','unknown'),reason=result.get('reason'),
                   presumed_profile_id=profile,similarity=result.get('similarity'),experimental=True,
                   identification_ms=round((time.monotonic()-started)*1000,2),personal_authorized=False,
                   ui_identity='tentative_match' if profile else 'unknown',segment_id=segment)
            if s.personalization and profile!=s.access.confirmed_profile_id or changed:
                await s.manager.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'speaker_changed_or_uncertain')
            elif hasattr(s,'speaker_cycle'):s.speaker_cycle()
        s.spawn(identify())
        return {'accepted':True,'local_only':True,'raw_audio_saved':False,'external_stt_calls':0}
