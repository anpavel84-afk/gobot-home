from typing import Protocol
class HomeAssistant(Protocol):
    async def read_state(self,entity_id:str)->dict:...
class MusicAssistant(Protocol):
    async def now_playing(self)->dict:...
class PermissionLayer:
    def authorize(self,action,*,human_confirmation=False):
        if action not in {'home.read_state','music.now_playing'}:raise PermissionError('Action denied: permission layer not provisioned')
        return True
class MockHomeAssistant:
    async def read_state(self,entity_id):return {'entity_id':entity_id,'state':'unavailable','mock':True}
class MockMusicAssistant:
    async def now_playing(self):return {'state':'idle','mock':True}
