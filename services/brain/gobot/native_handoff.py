"""Actual B -> existing A handover. No CLI job, model call or budget creation.

Native close ACK and legacy admission are separate from a spoken promise.
"""
import asyncio,re,time
from uuid import uuid4
from .conversation_modes import mode_intent

def acknowledgment(text):
    return bool(re.fullmatch(r'(?:да|да спасибо|окей|ок|хорошо|ладно|понятно|спасибо)[.!?, ]*',text.casefold().strip()))

class NativeHandoff:
    def __init__(self,manager,modes,*,executor_status=None):
        self.manager=manager;self.modes=modes;self.operations={};self.offers={};self.executor_status=executor_status
    def propose(self,s,turn):
        reason=self.admission(s)
        if reason:return {'available':False,'reason':reason,'confirmed':False}
        self.offers[s.id]={'turn_count':len(s.turns),'expires':time.monotonic()+120}
        proposal={'available':True,'target':'legacy','engine_label':'A','confirmed':False,'background_job':False}
        s.emit('conversation_mode_offer',**proposal)
        return proposal
    def admission(self,s):
        binding=s.offer.owner_test_binding or s.offer.client_id
        if not self.modes.legacy_allowed(binding):return 'hardware_cli_not_authorized'
        if s.offer.personalization_mode!='guest' or s.offer.remember or s.access.private_access:return 'native_handoff_guest_scope_required'
        if s.offer.profile_epoch or s.offer.confirmed_profile_epoch:return 'native_handoff_guest_scope_required'
        if s.experts.active():return 'expert_job_already_running'
        if self.executor_status:
            state=self.executor_status()
            if not state.get('available'):return state.get('reason') or 'a_executor_unavailable'
        return None
    async def request(self,s,turn,text):
        offered=self.offers.pop(s.id,None)
        confirmed=bool(offered and time.monotonic()<offered['expires'] and len(s.turns)==offered['turn_count']+1
            and re.fullmatch(r'(?:да|да давай|да переводи|подтверждаю)[.!?, ]*',text.casefold().strip()))
        if mode_intent(text)!='legacy' and not confirmed:return False
        if s.id in self.operations:return True
        if len(self.operations)>=32:
            s.emit('conversation_mode_blocked',target='legacy',reason='handoff_capacity',confirmed=False);return False
        reason=self.admission(s)
        if reason:
            s.emit('conversation_mode_blocked',target='legacy',reason=reason,confirmed=False)
            await s.send({'type':'conversation.item.create','item':{'type':'message','role':'user','content':[{'type':'input_text','text':'Серверное состояние перехода A: '+reason+'. Переключение не выполнено.'}]}})
            return False
        question=''
        messages=[]
        for previous in s.turns:
            if previous is turn:break
            if previous.query and not mode_intent(previous.query) and not acknowledgment(previous.query):question=previous.query
            if previous.query:messages.append({'role':'user','content':previous.query})
            if previous.stored and not previous.cancelled and previous.answer:messages.append({'role':'assistant','content':previous.answer})
        operation={'operation_id':str(uuid4()),'state':'closing_native','flow':None,'question':question,'error':None}
        self.operations[s.id]=operation;turn.local_control=True
        s.emit('conversation_mode_switching',target='legacy',confirmed=False)
        # Existing native cancellation closes audible output; no farewell model call.
        await s.interrupt()
        operation['task']=asyncio.create_task(self.complete(s,operation,messages))
        return True
    async def complete(self,s,op,messages):
        try:
            result=await self.manager.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'mode_switch')
            if not result.get('hangup_confirmed'):raise PermissionError('native_close_unconfirmed')
            flow=self.modes.from_native(s.offer,messages,op['question'],op['operation_id'])
            op.update(state='ready',flow=flow.public())
        except Exception as error:
            op.update(state='blocked',error=str(error) if isinstance(error,PermissionError) else 'native_handoff_failed_no_retry')
        finally:messages.clear()
    async def result(self,s):
        op=self.operations.get(s.id)
        if not op:return None
        await asyncio.wait_for(asyncio.shield(op['task']),12)
        return {k:op[k] for k in ('operation_id','state','flow','question','error')}
