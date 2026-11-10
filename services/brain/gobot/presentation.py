"""Transport-independent gobot.ui v2 presentation contract and local intent policy."""
import re
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field,model_validator

VisualType=Literal['image_card','image_gallery','info_card','timer_widget','weather_card','status_card','music_card','rich_answer']
ASSET=r'^/api/visual/assets/[a-f0-9]{64}/(?:browser|preview|device)\.jpg$'

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class VisualSource(Strict):
    label:str=Field(max_length=160)
    url:str|None=Field(default=None,max_length=1500)
    @model_validator(mode='after')
    def trusted_link(self):
        if self.url:
            from urllib.parse import urlsplit
            u=urlsplit(self.url)
            if u.scheme!='https' or u.hostname not in {'commons.wikimedia.org','creativecommons.org','openverse.org','www.openverse.org','api.openverse.org','flickr.com','www.flickr.com'} or u.username or u.password or u.port not in {None,443}:raise ValueError('Untrusted source link')
        return self

class VisualImage(Strict):
    asset_id:str=Field(pattern=r'^[a-f0-9]{64}$')
    url:str=Field(pattern=ASSET)
    preview_variant:str=Field(pattern=ASSET)
    device_variant:str=Field(pattern=ASSET)
    caption:str=Field(max_length=400)
    alt:str=Field(max_length=400)
    mime_type:Literal['image/jpeg']='image/jpeg'
    width:int=Field(ge=1,le=1200)
    height:int=Field(ge=1,le=1200)
    source:VisualSource
    attribution:str=Field(max_length=600)
    license:str=Field(max_length=100)
    license_url:str|None=Field(default=None,max_length=200)
    changes:str='Scaled and re-encoded; device image padded to square; metadata removed'
    @model_validator(mode='after')
    def paths(self):
        for value in (self.url,self.preview_variant,self.device_variant):
            if '/'+self.asset_id+'/' not in value:raise ValueError('Asset identity mismatch')
        if self.license_url:VisualSource(label='license',url=self.license_url)
        return self

class VisualAction(Strict):
    type:Literal['open_image','view_source','dismiss','timer_cancel']
    label:str=Field(max_length=80)
    asset_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{64}$')
    timer_id:str|None=Field(default=None,pattern=r'^[a-f0-9-]{36}$')

class VisualMetadata(Strict):
    state:Literal['ready','loading','unavailable','expired','cancelled']='ready'
    reason:str|None=Field(default=None,max_length=100)
    cache_hit:bool=False
    query_sent_to_source:bool=False
    approximate_match:bool=False
    selection_basis:Literal['local_state','curated_visual_review','source_metadata_search_unverified']='local_state'
    deadline:float|None=Field(default=None,allow_inf_nan=False)
    duration_ms:int|None=Field(default=None,ge=1,le=86400000)
    timer_id:str|None=Field(default=None,pattern=r'^[a-f0-9-]{36}$')
    facts:dict[str,str]=Field(default_factory=dict,max_length=12)
    device_width:Literal[240]=240
    device_height:Literal[240]=240
    device_max_bytes:Literal[65536]=65536

class Presentation(Strict):
    namespace:Literal['gobot.ui']='gobot.ui'
    version:Literal[2]=2
    id:str=Field(max_length=100)
    type:VisualType
    title:str=Field(min_length=1,max_length=160)
    subtitle:str=Field(default='',max_length=300)
    text:str=Field(default='',max_length=2000)
    images:list[VisualImage]=Field(default_factory=list,max_length=4)
    actions:list[VisualAction]=Field(default_factory=list,max_length=6)
    metadata:VisualMetadata=Field(default_factory=VisualMetadata)
    source:VisualSource=Field(default_factory=lambda:VisualSource(label='GoBot · локально'))
    expires_at:float|None=Field(default=None,allow_inf_nan=False)
    updated_at:float=Field(default_factory=time.time,allow_inf_nan=False)
    cache_key:str|None=Field(default=None,max_length=100)
    @model_validator(mode='after')
    def complete(self):
        if self.type in {'image_card','image_gallery'} and self.metadata.state=='ready' and not self.images:raise ValueError('Ready image response needs actual images')
        if self.type=='timer_widget' and self.metadata.state=='ready' and self.metadata.deadline is None:raise ValueError('Timer requires server deadline')
        return self

@dataclass(frozen=True)
class VisualIntent:
    kind:str
    query:str=''
    gallery:bool=False
    catalog_id:str|None=None

class PresentationDecision:
    def detect(self,text):
        lower=text.strip().lower()
        if re.search(r'\bне\s+(?:показывай|покажи|показывать)|без\s+(?:картинок|изображений|фото)',lower):return None
        if re.search(r'(?:какая|как\w*|покажи|что).{0,35}погод|^погода\??$',lower):return VisualIntent('weather')
        if re.search(r'что (?:сейчас )?играет|текущ\w* трек|покажи.*(?:плеер|музык)',lower):return VisualIntent('music')
        if re.search(r'покажи.*(?:статус|состояни[ея]).*(?:гобот|систем|сервер)|^статус (?:гобот|системы)',lower):return VisualIntent('status')
        if not re.search(r'\b(?:покажи|показать|покажите|показывай|покажешь|увидеть)\b|как выгляд(?:ит|ят)|^(?:фото|фотография|изображение|картинка|галерея)\s|(?:пришли|скинь|выведи).*?(?:фото|картин|изображен)',lower):return None
        if re.search(r'истори|памят|факт[ыо]|настройк|список|парол|ключ|файл|таймер',lower):return None
        if re.search(r'схем|диаграм',lower):
            return VisualIntent('diagram',query=text[:160],catalog_id='gobot-pipeline' if re.search(r'гобот|gobot|голосов\w* (?:контур|конвейер)',lower) else None)
        if re.search(r'карточк.*(?:результат|ответ)',lower):return VisualIntent('info',query=text[:160])
        query=re.sub(r'^.*?\b(?:покажи(?:те)?|показать|показывай|покажешь|увидеть|пришли|скинь|выведи)\b[,\s:]*','',text,flags=re.I)
        query=re.sub(r'^мне\s+','',query,flags=re.I)
        query=re.sub(r'^(?:мне\s+)?(?:как выгляд(?:ит|ят)|фото(?:графии|графию)?|картинк[иу]|изображени[ея]|примеры?|галерею)\s*','',query,flags=re.I).strip(' .?!«»"')[:180]
        if not query:return VisualIntent('image',query='',gallery=False)
        catalog=None
        if re.search(r'бычь[её] ?сердц|oxheart|cuor di bue',lower):catalog='oxheart'
        elif re.search(r'лабрадор|labrador',lower) and not re.search(r'ч[её]рн|шоколад|black|chocolate',lower):catalog='labrador'
        elif re.search(r'raspberry\s*pi|распберри|рас[пб]ерри\s*пи',lower) and not re.search(r'zero|pico|raspberry\s*pi\s*[1-9]|рас[пб]ерри\s*пи\s*[1-9]',lower):catalog='raspberry-pi'
        return VisualIntent('image',query=query,gallery=bool(catalog=='oxheart' or re.search(r'галере|несколько|фотографии|картинки|примеры',lower)),catalog_id=catalog)

def frame_id(turn,key):return str(uuid5(NAMESPACE_URL,'gobot.visual:'+turn+':'+key))

class CompactImage(Strict):
    asset_id:str=Field(pattern=r'^[a-f0-9]{64}$')
    variant:Literal['device']='device'
    width:Literal[240]=240
    height:Literal[240]=240
    mime:Literal['image/jpeg']='image/jpeg'
    max_bytes:Literal[65536]=65536

class CompactCredit(Strict):
    author:str=Field(max_length=600)
    source:VisualSource
    license:str=Field(max_length=100)
    license_url:str|None=Field(default=None,max_length=200)
    changes:str=Field(max_length=200)

class ESP32Presentation(Strict):
    namespace:Literal['gobot.ui']='gobot.ui'
    version:Literal[2]=2
    command:Literal['presentation.show']='presentation.show'
    id:str=Field(max_length=100)
    type:VisualType
    title:str=Field(max_length=80)
    text:str=Field(max_length=240)
    state:Literal['ready','loading','unavailable','expired','cancelled']
    image:CompactImage|None=None
    credit:CompactCredit|None=None
    deadline:float|None=Field(default=None,allow_inf_nan=False)
    @model_validator(mode='after')
    def credit_required(self):
        if self.image and not self.credit:raise ValueError('Image credit must not be dropped')
        return self

def esp32_projection(frame:Presentation):
    """Compact JSON only. Native firmware must enqueue it in the GUI task.
    Image download/MCP invocation is separately capability/permission gated.
    """
    payload={'namespace':'gobot.ui','version':2,'command':'presentation.show','id':frame.id,'type':frame.type,'title':frame.title[:80],'text':frame.text[:240],'state':frame.metadata.state}
    if frame.images:
        image=frame.images[0]
        payload['image']={'asset_id':image.asset_id,'variant':'device','width':240,'height':240,'mime':'image/jpeg','max_bytes':65536}
        payload['credit']={'author':image.attribution,'source':image.source.model_dump(),'license':image.license,'license_url':image.license_url,'changes':image.changes}
    if frame.metadata.deadline is not None:payload['deadline']=frame.metadata.deadline
    import json
    payload=ESP32Presentation.model_validate(payload).model_dump(exclude_none=True)
    if len(json.dumps(payload,ensure_ascii=False).encode())>8192:raise ValueError('Device UI metadata limit')
    return {'type':'custom','payload':payload}
