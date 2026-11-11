"""Portable browser-device profile; no claim of physical ESP32 compatibility."""
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,model_validator

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')

class ScreenPreferences(Strict):
    automatic_illustrations:bool=True
    visual_strategy:Literal['question_only','question_then_refine','answer_only']='question_then_refine'
    style:Literal['minimal','balanced','rich']='rich'
    prefer_real_photos:bool=True
    generation_allowed:bool=False
    generation_mode:Literal['off','missing','helpful']='off'
    generation_provider:Literal['codex','openai']='openai'
    generation_consent:bool=False
    generation_daily_limit:int=Field(default=0,ge=0,le=100)
    source_preference:Literal['auto','photos','illustrations']='auto'
    visual_source_policy:Literal['wikimedia_first','wikimedia_only','wikimedia_generate']='wikimedia_generate'
    thematic_icons:bool=True
    hold_after_response_seconds:int=Field(default=12,ge=0,le=120)
    return_to_idle:bool=True

class DeviceDisplay(Strict):
    shape:Literal['circle']='circle'
    width:int=Field(default=240,ge=128,le=480)
    height:int=Field(default=240,ge=128,le=480)
    safe_inset:int=Field(default=35,ge=16,le=80)
    @model_validator(mode='after')
    def square(self):
        if self.width!=self.height or self.safe_inset>=self.width/2:raise ValueError('Invalid display geometry')
        return self

class DeviceSkin(Strict):
    skin_id:Literal['classic','soft','minimal']='classic'
    version:Literal[1]=1
    face_color:str=Field(default='#a3e5cd',pattern=r'^#[a-fA-F0-9]{6}$')
    background:str=Field(default='#0c141a',pattern=r'^#[a-fA-F0-9]{6}$')
    eyes:Literal['default','round','oval','line']='default'
    mouth:Literal['default','smile','neutral','small']='default'
    animation_intensity:float=Field(default=.6,ge=0,le=1,allow_inf_nan=False)
    reduced_motion:bool=False
    idle_screen:Literal['face','clock','image']='face'

class FeedbackPreferences(Strict):
    enabled:bool=True
    filler_enabled:bool=True
    quiet:bool=False
    threshold_ms:int=Field(default=2250,ge=2000,le=2500)
    volume:float=Field(default=.22,ge=0,le=.5,allow_inf_nan=False)

class ConversationPolicy(Strict):
    followup_enabled:bool=True
    followup_seconds:int=Field(default=12,ge=5,le=30)
    silence_ms:int=Field(default=900,ge=600,le=2000)
    min_speech_ms:int=Field(default=300,ge=200,le=1000)
    echo_guard_ms:int=Field(default=350,ge=200,le=1500)

class WeatherPreferences(Strict):
    enabled:bool=False
    location_name:str=Field(default='',max_length=160)
    latitude:float|None=Field(default=None,ge=-90,le=90,allow_inf_nan=False)
    longitude:float|None=Field(default=None,ge=-180,le=180,allow_inf_nan=False)
    provider:Literal['open_meteo']='open_meteo'
    @model_validator(mode='after')
    def configured(self):
        if self.enabled and (not self.location_name or self.latitude is None or self.longitude is None):raise ValueError('Weather needs a confirmed location')
        return self

class VoicePreferences(Strict):
    realtime_model:Literal['gpt-realtime-2.1-mini','gpt-realtime-2.1']='gpt-realtime-2.1-mini'
    audio_preset:Literal['baseline','quiet_ptt','browser_ns_off','browser_ec_off','browser_agc_on','browser_agc_off','server_noise_off','server_far_field','server_strength_half','vad_sensitive']='baseline'
    expert_quota_consent:bool=False
    engine:Literal['legacy','realtime','live']='legacy'
    realtime_consent:bool=False
    personalization_mode:Literal['guest','confirmed_profile']='guest'
    speaker_identity_enabled:bool=True
    # None preserves existing client choices until explicitly set.
    voice:Literal['marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse']|None=None
    volume:float|None=Field(default=None,ge=0,le=1,allow_inf_nan=False)
    speak:bool|None=None
    mode:Literal['auto','fast','reasoning','codex','google']|None=None

class DeviceProfile(Strict):
    version:Literal[1]=1
    client_id:str=Field(default_factory=lambda:'browser-device-'+str(uuid4()),pattern=r'^browser-device-[a-f0-9-]{36}$')
    client_kind:Literal['browser_device']='browser_device'
    display:DeviceDisplay=Field(default_factory=DeviceDisplay)
    skin:DeviceSkin=Field(default_factory=DeviceSkin)
    screen:ScreenPreferences=Field(default_factory=ScreenPreferences)
    feedback:FeedbackPreferences=Field(default_factory=FeedbackPreferences)
    conversation:ConversationPolicy=Field(default_factory=ConversationPolicy)
    weather:WeatherPreferences=Field(default_factory=WeatherPreferences)
    voice:VoicePreferences=Field(default_factory=VoicePreferences)
    interaction_mode:Literal['hold','toggle','wake']='hold'
    keep_screen_awake:bool=False
    has_screensaver:bool=False

    def capabilities(self):
        return {'client_id':self.client_id,'kind':'browser_device','physical_device_connected':False,
                'display':self.display.model_dump(),'ui_version':2,'input':['push_to_talk','tap_to_toggle'],
                'audio':['browser_capture','server_stt','server_tts','realtime_webrtc_candidate'],'wake_word':'not_configured',
                'states':['idle','listening','recognizing','thinking','speaking','error','muted','offline'],
                'face_primitives':['ellipse','line','arc'],'skin':self.skin.model_dump(),
                'animation':{'speaking_input':'actual_local_playback_rms','phoneme_sync':False,'blink_period_ms':11938,'listening_pulse_period_ms':1571},
                'assets':{'screensaver_ref':'profile_screensaver' if self.has_screensaver else None,'private':True},
                'image_generation_provider':self.screen.generation_provider,'screen':self.screen.model_dump(),
                'conversation_policy':self.conversation.model_dump(),
                'conversation_states':['STANDBY','ACTIVATED','LISTENING','PROCESSING','SPEAKING','FOLLOWUP_LISTENING','CANCELLED','ERROR','OFFLINE']}

class DeviceSceneCommand(Strict):
    namespace:Literal['gobot.ui']='gobot.ui'
    version:Literal[2]=2
    command:Literal['scene.show']='scene.show'
    turn_id:str=Field(max_length=100)
    scene_type:Literal['avatar','icon','image','diagram','widget','info_card']
    strategy:Literal['retrieve_photo','generate_illustration','render_diagram','render_widget','show_emoji_or_icon','show_avatar']
    title:str=Field(max_length=80)
    icon:str|None=Field(default=None,max_length=12)
    duration_seconds:int=Field(ge=0,le=120)
    preserve_visual:bool=False

def compact_scene(scene,turn_id):
    return {'type':'custom','payload':DeviceSceneCommand(turn_id=turn_id,scene_type=scene.scene_type,strategy=scene.visual_strategy,
        title=scene.visual_subject[:80],icon=scene.visual_payload.get('icon'),duration_seconds=scene.scene_duration,preserve_visual=scene.preserve_visual).model_dump(exclude_none=True)}
