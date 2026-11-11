"""Shared GoBot voice presentation: one Composer/TwoStageVisual for B and C."""
import asyncio,re

class VoiceVisualSession:
    def ensure_visual(self,turn):
        from .conversation_modes import mode_intent
        if mode_intent(turn.query):return None
        if not turn.visual_task and (turn.query or not self.policy.input_transcription):turn.visual_task=self.spawn(self.visual(turn))
        return turn.visual_task

    async def check_alignment(self,turn,final=False):
        if turn.alignment_pending or turn.alignment_state!='unknown' or not turn.query:return
        turn.alignment_pending=True
        checked_length=len(turn.answer);was_final=final or turn.generation_done
        try:
            from .response_alignment import alignment
            stable=turn.answer if was_final else re.sub(r'[\w-]+$','',turn.answer)
            result=await asyncio.to_thread(alignment,turn.query,stable)
            if not result or self.closed or turn is not self.current or turn.cancelled:return
            turn.alignment_state=result
            self.alignment_counts[result]=self.alignment_counts.get(result,0)+1
            if result=='suspected_mismatch':
                self.emit('meaning_mismatch',code='possible_subject_frame_disagreement',automatic_retry=False)
                if turn.photo:await turn.photo.close()
        finally:
            turn.alignment_pending=False
            if not self.closed and turn is self.current and not turn.cancelled and turn.alignment_state=='unknown' and (len(turn.answer)>checked_length or turn.generation_done and not was_final):
                self.spawn(self.check_alignment(turn,final=turn.generation_done))

    async def visual(self,turn):
        from .visual_prefetch import planned_entity,TwoStageVisual
        try:
            if turn.visual_started:return
            if not turn.query and self.policy.input_transcription:return
            turn.visual_started=True
            req=turn.req or self.request('Расскажи подробнее',turn.id)
            from .quick_intents import resolve_quick
            if resolve_quick(req.text,{}) is not None:return # Tools own their factual widget.
            context=await asyncio.to_thread(self.manager.brain.memory.context,req)
            if self.closed or turn is not self.current or turn.cancelled:return
            plan=self.manager.brain.composer.plan(req,context=context)
            if plan.reason=='answer_map':return
            scene=self.manager.brain.composer.compose(req,context=context,plan=plan) if hasattr(self.manager.brain.composer,'compose') else None
            entity=await asyncio.to_thread(planned_entity,req.text,plan,context)
            if self.closed or turn is not self.current or turn.cancelled:return
            eligible=self.manager.brain.composer.answer_visual_eligible(req,context=context,plan=plan)
            if scene and turn is self.current and self.profile.screen.visual_strategy!='answer_only':
                scene.source_metadata.update(visual_stage='provisional',subject_confirmation='question_only')
                self.emit('screen_scene',scene=scene.model_dump());self.mark_turn(turn,'visual_provisional_scene_sent')
            if not (plan.visual_needed or eligible) or plan.visual_strategy=='render_local' and not eligible:return
            async def publish(result,stage,revision):
                if self.closed or turn is not self.current or turn.cancelled or turn.alignment_state=='suspected_mismatch':return False
                if not result.frame.images:
                    from .visual import VisualService
                    result=VisualService.describe_missing(req,plan,result,generation_reason='image_generation_policy_denied' if not self.policy.image_generation_allowed else None)
                self.last_scene=result.frame
                if result.frame.images:self.mark_turn(turn,'visual_provisional_candidate_ready' if stage==1 else 'visual_refined_candidate_ready')
                self.emit('visual_response',presentation=result.frame.model_dump())
                self.mark_turn(turn,'visual_provisional_sent' if stage==1 else 'visual_refined_sent')
                turn.trace.append({'presentation':result.frame.model_dump()})
                turn.visual_outcome={'executed':True,'status':'asset_delivered' if result.frame.images else 'fallback',
                    'asset_delivered':bool(result.frame.images),'presented':False,'frame_id':result.frame.id,
                    'source_failure_reason':result.frame.metadata.reason if not result.frame.images else None,
                    'generation_blocked_reason':result.frame.metadata.facts.get('generation_fallback_reason'),
                    'generated':bool(result.frame.metadata.generation_provider),'message':result.frame.text}
                turn.visual_ready.set()
                if not result.frame.images:self.emit('visual_status',status='fallback',message=result.frame.text,reason=result.frame.metadata.reason,generation_reason=turn.visual_outcome['generation_blocked_reason'])
                return True
            def mismatch():
                if turn is self.current and turn.alignment_state!='suspected_mismatch':
                    turn.alignment_state='suspected_mismatch'
                    self.alignment_counts['suspected_mismatch']=self.alignment_counts.get('suspected_mismatch',0)+1
                    self.emit('meaning_mismatch',code='possible_subject_frame_disagreement',automatic_retry=False)
            if plan.origin=='explicit' and plan.visual_strategy=='retrieve' and not entity:
                from .visual_prefetch import PRIVATE
                from .visual_subject import PRIVATE_QUERY
                reason='private_image_not_available' if PRIVATE.search(req.text) or PRIVATE_QUERY.search(req.text) else 'image_query_required'
                await publish(self.manager.brain.visual.fallback(req,'Изображение',reason),1,0);return
            def status(event):
                if not self.closed and turn is self.current and not turn.cancelled and event['status']!='fallback':self.emit('visual_status',**event)
            turn.photo=TwoStageVisual(req,entity,plan,self.manager.brain.visual.attachment,publish,on_mismatch=mismatch,on_status=status)
            if turn.answer:turn.photo.observe(turn.answer,final=turn.generation_done)
            if turn.generation_done:turn.photo.finish()
            await turn.photo.task
            turn.trace.append({'visual_decision':dict(turn.photo.diagnostics)})
            if turn.stored and turn.req and not turn.truncated and not turn.cancelled and not self.closed:
                await asyncio.to_thread(self.manager.brain.memory.finish,turn.req,'completed',turn.answer,'openai:'+self.policy.model,turn.trace)
        except Exception:
            if turn is self.current:self.emit('visual_status',status='unavailable')
        finally:
            if not turn.visual_outcome:turn.visual_outcome={'executed':False,'status':'unavailable','asset_delivered':False,'presented':False,'reason':'visual_subject_or_permission_required'}
            turn.visual_ready.set()
