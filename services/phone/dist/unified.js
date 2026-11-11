/* One product shell over the existing C and A clients. No provider calls on load. */
(() => {
 'use strict';
 if(document.body.dataset.unified!=='true')return;
 const $=id=>document.getElementById(id);
 class UnifiedConversation {
  constructor(){this.enabled=true;this.id=null;this.mode='live';this.switching=false;this.ending=false;this.epoch=0;}
  status(text){if($('unified-status'))$('unified-status').textContent=text;window.goBotDevice?.status(text);}
  select(mode){this.mode=mode;document.body.dataset.conversationEngine=mode;if($('conversation-engine'))$('conversation-engine').value=mode;
   if($('unified-mode'))$('unified-mode').textContent=mode==='legacy'?'Экспертный режим · A':'Живой разговор · C';}
  requestFields(){return this.mode==='legacy'&&this.id?{mode_conversation_id:this.id,remember:false}:{};}
  async command(action,extra={}){
   if(!this.id)throw Error('Сначала начните разговор.');
   const response=await fetch('/api/live/modes/'+this.id+'/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra}),keepalive:action==='end'});
   const result=await response.json();if(!response.ok)throw Error(result.detail||'Переключение не подтверждено сервером.');return result;
  }
  async init(){
   this.select('live');
   const section=document.createElement('section');section.className='reply';section.id='unified-controls';
   const label=document.createElement('strong');label.id='unified-mode';section.append(label);
   const status=document.createElement('p');status.id='unified-status';section.append(status);
   const actions=[['Экспертный режим',()=>this.change('legacy')],['Живой разговор',()=>this.change('live')],['Закончить разговор',()=>this.end()]];
   if(!window.goBotDevice)actions.unshift(['Начать разговор',()=>window.GoBotLive.start()]);
   for(const [text,action] of actions){
    const button=document.createElement('button');button.type='button';button.textContent=text;button.onclick=()=>void action().catch(e=>this.status(e.message));section.append(button);
   }
   (document.querySelector('.device-controls')||document.querySelector('header')).after(section);this.select('live');
   this.status('Начало — C. «Экспертный режим» — A. После 10 секунд тишины или «стоп» разговор заканчивается.');
   const wake=$('device-wake');if(wake)wake.textContent='Локальное «ГоБот» ещё не настроено. Сейчас запуск кнопкой; в ожидании аудио в OpenAI не отправляется.';
   if($('device-stop')){$('device-stop').textContent='Стоп · закончить разговор';$('device-stop').onclick=()=>void this.end();}
   if($('stop'))$('stop').onclick=()=>void this.end();
   if($('device-disable')){$('device-disable').textContent='Закончить разговор';$('device-disable').onclick=()=>void this.end();}
   if($('conversation-engine'))$('conversation-engine').closest('label')?.setAttribute('hidden','');
   // Existing finite owner grant bootstraps speech consent once, with later revocation preserved.
   try{
    const ready=await(await fetch('/api/demo2/a/readiness',{cache:'no-store'})).json();
    if(ready.manual_authorized&&ready.grant_revision&&localStorage.getItem('gobot.unified.applied-grant')!==ready.grant_revision){
     for(const id of ['paid','paid-stt','quota','speak'])if($(id))$(id).checked=true;
     if($('stt'))$('stt').value='openai';if($('tts'))$('tts').value='openai';
     window.GoBotClient.saveSettings();localStorage.setItem('gobot.unified.applied-grant',ready.grant_revision);
    }
   }catch(_){} // An unavailable grant never creates consent.
   this.bindHooks();
   this.heartbeat=setInterval(()=>void this.tick(),700);
   for(const name of ['pagehide','offline'])window.addEventListener(name,()=>void this.end(name==='pagehide'?'page_hidden':'network_offline'));
   document.addEventListener('visibilitychange',()=>{if(document.hidden)void this.end('page_hidden');});
  }
  bindHooks(){
   if(window.GoBotHooks.clientKind==='device'&&!window.goBotDevice?.manager)return;
   const hooks=window.GoBotHooks;if(hooks.unifiedBound)return;hooks.unifiedBound=true;
   if($('device-stop')){$('device-stop').textContent='Стоп · закончить разговор';$('device-stop').onclick=()=>void this.end();}
   if($('device-disable')){$('device-disable').textContent='Закончить разговор';$('device-disable').onclick=()=>void this.end();}
   const silence=hooks.onFollowupSilence;hooks.onFollowupSilence=()=>{silence?.();if(this.mode==='legacy')void this.end('idle_timeout');};
   const transcript=hooks.onTranscript;hooks.onTranscript=async item=>{
    if(window.GoBotHooks.clientKind==='device')return transcript?.(item);
    if(this.mode==='legacy')await window.GoBotClient.send();
   };
   const streamEnd=hooks.onStreamEnd;hooks.onStreamEnd=item=>{streamEnd?.(item);if(!window.goBotDevice&&this.mode==='legacy')this.legacyFollowup=true;};
   const event=hooks.onEvent;hooks.onEvent=item=>{event?.(item);if(item.type==='tool_status'&&item.data?.status==='conversation_mode'){
    const state=item.data.mode;setTimeout(()=>void (state.active?this.apply(state):this.end(state.reason)),0);
   }};
  }
  async liveClosed(state,confirmed,reason){
   if(this.ending)return;
   if(reason==='mode_switch'&&state?.active&&state.mode==='legacy'&&confirmed){
    this.id=state.mode_conversation_id;await this.apply(state);return;
   }
   if(reason==='mode_switch'&&!confirmed)this.status('Live ещё не подтвердил закрытие. A не запущен.');
   this.id=null;this.select('live');
  }
  async change(mode){
   if(this.switching||this.ending)return;
   if(!this.id){this.status('Начните разговор кнопкой «Включить GoBot». Он начнётся в C.');return;}
   if(mode===this.mode)return;
   try{const state=await this.command(mode);if(state.provider_closed)await this.apply(state);}
   catch(e){this.status(e.message);}
  }
  async apply(state){
   if(this.switching||this.ending||!state.active)return;
   if(state.mode===this.mode)return;
   if(!state.provider_closed){this.status('Ожидаю подтверждения закрытия Live.');return;}
   this.switching=true;const epoch=++this.epoch;
   try{
    this.id=state.mode_conversation_id;
    const app=window.goBotDevice;
    // No simultaneous microphone owners, pending legacy capture or old audio queue.
    if(app)app.pause('Переключаю режим…');else{window.GoBotClient.cancelRecording();window.GoBotClient.stop();}
    this.select(state.mode);
    if(state.mode==='legacy'){
     if($('model'))$('model').value='auto';if($('remember'))$('remember').checked=false;
     await window.GoBotClient.unlockAudio();
     if(app){
      app.profile.conversation={...app.profile.conversation,followup_enabled:true,followup_seconds:10};
      await app.enable();if(!app.enabled)throw Error($('device-status')?.textContent||'Не удалось включить A');
      if(epoch!==this.epoch)return;
      app.sessionActive=true;app.serverAudioEnded=true;app.answerPlaybackStarted=true;app.checkFollowup(window.GoBotClient.audioSnapshot());
     }else await this.listenLegacy();
     this.status('Экспертный режим A. Говорите; окно продолжения — 10 секунд.');
    }else{
     if(app)await app.enable();else await window.GoBotLive.start();
     this.status('Живой разговор C. Можно говорить.');
    }
   }catch(e){await this.end();this.status(e.message);}
   finally{this.switching=false;}
  }
  async tick(){
   if(this.mode!=='legacy'||!this.id||this.switching||this.ending||this.ticking)return;
   this.ticking=true;try{
    const audio=window.GoBotClient.audioSnapshot();
    if(!window.goBotDevice&&this.legacyFollowup&&!audio.playing&&!audio.feedback_playing&&!window.GoBotClient.isRecording()){
     this.legacyFollowup=false;await this.listenLegacy();
    }
    const state=await this.command('activity',{input_active:window.GoBotClient.isRecording(),playback_active:audio.playing||audio.feedback_playing});
    if(!state.active)await this.end(state.reason||'idle_timeout');
   }catch(e){await this.end();this.status(e.message);}finally{this.ticking=false;}
  }
  async listenLegacy(){
   if(this.mode!=='legacy'||!this.id||this.ending)return;
   window.GoBotHooks.captureOptions={minDurationMs:400,minSpeechMs:300,vad:{windowMs:10000,silenceMs:900,minSpeechMs:300}};
   const started=await window.GoBotClient.startRecording({followup:true});
   if(started===false)throw Error('Не удалось включить микрофон A. Проверьте разрешение распознавания.');
  }
  async end(reason='conversation_ended'){
   if(this.ending)return;this.ending=true;this.epoch++;const id=this.id;
   let failure=null;try{
    window.goBotDevice?.pause('Разговор завершён.');window.GoBotClient.cancelRecording();
    if(window.GoBotLive.id)await window.GoBotLive.close('Разговор завершён.','user_stop');
    if(id)await this.command('end');
   }catch(_){failure='Звук остановлен. Подтверждение закрытия сервера не получено.';}
   finally{this.id=null;this.select('live');this.ending=false;this.status(failure||(reason==='idle_timeout'?'Разговор завершён после 10 секунд тишины. Следующий запуск — C.':'Разговор завершён. Следующий запуск — C.'));}
  }
 }
 const unified=window.GoBotUnified=new UnifiedConversation();
 window.addEventListener('DOMContentLoaded',()=>void unified.init());
})();
