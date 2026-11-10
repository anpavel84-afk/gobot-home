"""Bounded character images from plain answer text. No second model invocation."""
import asyncio
import re
from .presentation import frame_id
from .visual_prefetch import Entity

CHARACTER_TOPIC=re.compile(r'мульт|анимаци|персонаж',re.I)
NAME=r'[А-ЯЁA-Z][а-яёa-z]+(?:[- ][А-ЯЁA-Z][а-яёa-z]+){0,2}'
ROLE=re.compile(r'\b(динозавр|кот|кошка|мышонок|мышь|ут[её]нок|утка|кролик|человечек|персонаж)\s+('+NAME+r')')

def characters(text):
    for match in ROLE.finditer(text):
        role,name=match.groups()
        # Reviewed film association. Its representative frame depicts the character.
        if name=='Фантош' and 'Фантасмагори' in text:
            yield Entity('Фантасмагория мультфильм','Фантош — Фантасмагория',(name,))
        else:yield Entity(role+' '+name,role.capitalize()+' '+name,(name,))

class CharacterImages:
    def __init__(self,req,fetch,timeout):
        self.req=req;self.fetch=fetch;self.timeout=timeout
        self.text='';self.seen=set();self.jobs=[];self.queue=asyncio.Queue(maxsize=4)
        self.finished=False;self.active=0
    def observe(self,sentence):
        self.text=(self.text+' '+sentence)[-4000:]
        for entity in characters(self.text):
            key=entity.query.casefold()
            if key in self.seen or len(self.seen)>=3:continue
            self.seen.add(key);self.active+=1
            self.jobs.append(asyncio.create_task(self.lookup(entity)))
    async def lookup(self,entity):
        try:
            result=await self.fetch(self.req,entity.plan(),timeout=self.timeout)
            if result and result.frame.images:
                result.frame.id=frame_id(self.req.turn_id,'character-'+entity.query)
                result.frame.title=entity.label
                result.frame.metadata.facts['presentation_group']='answer_characters'
                await self.queue.put(result)
        except asyncio.CancelledError:raise
        except Exception:pass
        finally:
            self.active-=1
            if self.finished and not self.active:await self.queue.put(None)
    def finish(self):
        self.finished=True
        if not self.active:self.queue.put_nowait(None)
    def __aiter__(self):return self
    async def __anext__(self):
        item=await self.queue.get()
        if item is None:raise StopAsyncIteration
        return item
    async def aclose(self):
        for task in self.jobs:task.cancel()
        await asyncio.gather(*self.jobs,return_exceptions=True)
