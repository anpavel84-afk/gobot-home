import io,time,secrets
from urllib.parse import urlparse
from pydantic import BaseModel,ConfigDict,Field,model_validator
from typing import Literal
from PIL import Image
class UICommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    namespace:Literal['gobot.ui']='gobot.ui'
    version:Literal[1]=1
    command:Literal['timer.start','weather.show','status.show','music.now_playing','notification.show']
    duration_ms:int|None=Field(default=None,ge=1,le=86400000)
    text:str|None=Field(default=None,max_length=400)
    @model_validator(mode='after')
    def check(self):
        if self.command=='timer.start' and self.duration_ms is None:raise ValueError('Timer requires duration_ms')
        if self.command!='timer.start' and self.text is None:raise ValueError('Widget requires text')
        return self
class MockUIRenderer:
    def __init__(self):self.state={};self.queue=[]
    def enqueue(self,envelope):
        if envelope.get('type')!='custom':raise ValueError('Not a UI envelope')
        if envelope.get('payload',{}).get('version')==2:
            from .presentation import ESP32Presentation
            command=ESP32Presentation.model_validate(envelope['payload'])
        else:command=UICommand.model_validate(envelope['payload'])
        if len(self.queue)>=16:raise ValueError('UI queue full')
        self.queue.append(command)
    def gui_tick(self):
        for cmd in self.queue:self.state[cmd.command]=cmd.model_dump()
        self.queue.clear();return self.state
class ImageStore:
    def __init__(self,base_url='http://127.0.0.1:18784'):
        u=urlparse(base_url)
        if u.scheme!='http' or u.hostname!='127.0.0.1' or u.username or u.password or u.path:raise ValueError('Only explicit local origin')
        self.base_url=base_url;self.items={}
    def add(self,data,mime='image/jpeg',ttl=30):
        if mime!='image/jpeg' or len(data)>65536 or not 1<=ttl<=60:raise ValueError('Invalid image policy')
        with Image.open(io.BytesIO(data)) as image:
            if image.format!='JPEG' or image.size!=(240,240) or image.info.get('progressive') or image.info.get('progression'):raise ValueError('Baseline 240x240 JPEG required')
            image.verify()
        self.items={k:v for k,v in self.items.items() if v[0]>time.time()}
        if len(self.items)>=16:raise ValueError('Image store full')
        key=secrets.token_urlsafe(24);self.items[key]=(time.time()+ttl,data)
        return self.base_url+'/images/'+key
    def get(self,key):
        item=self.items.get(key)
        if not item or item[0]<time.time():self.items.pop(key,None);raise KeyError('Image expired')
        return item[1]
    def mcp_call(self,url,capabilities,user_permission,request_id=1):
        if not user_permission or 'self.screen.preview_image' not in capabilities:raise PermissionError('User tool/capability required')
        prefix=self.base_url+'/images/'
        if not url.startswith(prefix) or '/' in url[len(prefix):] or '?' in url or '#' in url:raise ValueError('External image URL denied')
        self.get(url[len(prefix):])
        return {'type':'mcp','payload':{'jsonrpc':'2.0','id':request_id,'method':'tools/call','params':{'name':'self.screen.preview_image','arguments':{'url':url}}}}
