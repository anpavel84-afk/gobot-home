/* Device interaction adapter. Speech/STT/SSE are exclusively GoBotClient/browser.js. */
(() => {
  'use strict';
  // Minimal bindings for the shared client engine, not a hidden second app or pipeline.
  const root=document.createElement('section');root.hidden=true;root.id='client-bindings';document.body.append(root);
  const selects={model:['auto','fast','reasoning','codex','google','mock'],tts:['openai','denis'],stt:['openai','whisper','mock'],'stt-mode':['file'],voice:[],'visual-source':['openverse','wikimedia','disabled']};
  const checks=new Set(['speak','paid','paid-stt','quota','remember','detailed-context','visual-contact-consent']);
  const ids=['question','send','stop','record','hold','volume','orb','answer','voice-status','mic-status','speaker-status','robot-label','result-badge','route-meta','route-statistics','context-statistics','topic-label','topic-name','rename-topic','saved-facts','memory-refresh','forget-conversation','memory-sources','history','new-conversation','refresh','services','provider-status','timer','visual-response','active-timers','visual-contact','visual-settings-save','visual-settings-status',...Object.keys(selects),...checks];
  for(const id of new Set(ids)){const node=document.createElement(id in selects?'select':checks.has(id)?'input':id==='question'?'textarea':'div');node.id=id;if(checks.has(id)){node.type='checkbox';node.checked=['speak','remember'].includes(id);}if(id in selects)for(const value of selects[id]){const option=document.createElement('option');option.value=option.textContent=value;node.append(option);}if(id==='volume')node.value='.8';root.append(node);}
  window.GoBotHooks={clientKind:'device'};
  class DeviceApp{
    constructor(){this.enabled=false;this.held=false;this.profile=null;this.turn=null;this.sent=new Set();this.generation=0;this.streamDone=true;this.releaseLock=null;this.captureAbort=null;}
    status(text){document.getElementById('device-status').textContent=text;}
    state(value,text){if(this.manager)this.manager.state=value;if(text)this.status(text);document.getElementById('device-mic').textContent=value==='listening'?'● Микрофон записывает вопрос':this.enabled?'○ Режим активен · микрофон по нажатию':'● Микрофон выключен';}
    async init(){
      const response=await fetch('/api/device/profile');if(!response.ok)throw Error('Не удалось загрузить профиль устройства');const data=await response.json();this.profile=data.profile;
      const {DeviceRenderer,SceneManager}=window.GoBotDeviceRenderer;this.manager=new SceneManager(this.profile);this.renderer=new DeviceRenderer(document.getElementById('device-screen'),this.profile);
      if(this.profile.has_screensaver)this.renderer.loadWallpaper();
      this.renderer.onImageError=()=>this.status('Изображение не загрузилось. Ответ продолжается.');
      const hooks=window.GoBotHooks;
      hooks.onStopped=()=>{if(this.enabled)this.state('idle');};
      hooks.onTurn=({turn_id})=>{this.turn=turn_id;this.manager.newTurn(turn_id);this.renderer.clearImage();this.streamDone=false;this.state('thinking','Готовлю ответ…');};
      hooks.onListening=()=>this.state('listening','Слушаю. Отпусти круг, когда закончишь.');
      hooks.onCapturePending=()=>this.status('Включаю микрофон…');
      hooks.onRecognizing=()=>this.state('recognizing','Распознаю речь…');
      hooks.onCaptureError=message=>{if(this.enabled)this.state('error',message);};
      hooks.onTranscript=async item=>{if(!this.enabled||!item.text?.trim()||this.sent.has(item.utterance_id))return;this.sent.add(item.utterance_id);if(this.sent.size>128)this.sent.delete(this.sent.values().next().value);await window.GoBotClient.send();};
      hooks.onEvent=item=>this.event(item);
      hooks.onStreamEnd=({turn_id})=>{if(turn_id===this.turn){this.streamDone=true;this.manager.finish(turn_id);}};
      const canvas=document.getElementById('device-screen');
      canvas.onpointerdown=event=>{if(this.profile.interaction_mode!=='hold')return;event.preventDefault();try{canvas.setPointerCapture(event.pointerId);}catch(_){}this.press();};
      canvas.onpointerup=event=>{if(this.profile.interaction_mode==='hold'){event.preventDefault();this.release();}};
      canvas.onpointercancel=canvas.onlostpointercapture=()=>{if(this.held)this.cancelCapture();};
      canvas.onclick=()=>{if(this.profile.interaction_mode==='toggle')window.GoBotClient.isRecording()?this.release():this.press();};
      canvas.onkeydown=event=>{if(event.repeat)return;if(event.code==='Space'||event.code==='Enter'){event.preventDefault();window.GoBotClient.isRecording()?this.release():this.press();}};
      canvas.oncontextmenu=event=>event.preventDefault();
      document.getElementById('device-enable').onclick=()=>this.enable();document.getElementById('device-disable').onclick=()=>this.pause('Микрофон выключен');
      document.getElementById('device-stop').onclick=()=>{window.GoBotClient.stop();this.state(this.enabled?'idle':'muted','Ответ остановлен');};
      document.getElementById('device-raster').onclick=()=>canvas.toBlob(blob=>{if(!blob)return;if(this.rasterURL)URL.revokeObjectURL(this.rasterURL);this.rasterURL=URL.createObjectURL(blob);const image=document.getElementById('raster-preview');image.src=this.rasterURL;image.width=canvas.width;image.height=canvas.height;image.hidden=false;},'image/png');
      document.addEventListener('visibilitychange',()=>{if(document.hidden)this.pause('Прослушивание приостановлено. Нажми «Возобновить GoBot».');});
      window.addEventListener('pagehide',()=>this.pause('Приостановлено'));window.addEventListener('offline',()=>{this.pause('Нет сети. После подключения возобнови GoBot.');this.state('offline');});
      window.addEventListener('online',()=>this.status('Сеть восстановлена. Нажми «Возобновить GoBot».'));
      try{const result=await(await fetch('/api/device/timers')).json();const timer=result.timers?.[0];if(timer){this.turn='restored-timer';this.manager.newTurn(this.turn);this.manager.frame({id:timer.id,type:'timer_widget',title:'Таймер',metadata:timer,images:[]},this.turn);this.manager.state='idle';this.manager.finish(this.turn);}}catch(_){}
      this.diagnostics={client_id:this.profile.client_id,capabilities:data.capabilities,activation:data.activation};
      document.getElementById('device-diagnostics').textContent=JSON.stringify({client_id:this.profile.client_id,capabilities:data.capabilities,activation:data.activation},null,2);
      if(this.profile.interaction_mode==='toggle')document.getElementById('device-hint').textContent='Нажми круг для начала записи, ещё раз — для завершения. Затем вопрос отправится автоматически.';
      let previous=0;const draw=now=>{if(now-previous>=(this.profile.skin.reduced_motion?150:33)){previous=now;const audio=window.GoBotClient.audioSnapshot();if(this.enabled&&['suspended','interrupted','closed'].includes(audio.state))this.pause('Аудио приостановлено браузером. Нажми «Возобновить GoBot».');if(this.enabled&&!['listening','recognizing','error','offline'].includes(this.manager.state)){this.manager.state=audio.playing&&audio.level>.003?'speaking':this.streamDone?'idle':'thinking';}this.manager.tick(audio.playing);this.renderer.draw(this.manager,audio.level,now);}requestAnimationFrame(draw);};requestAnimationFrame(draw);
    }
    event(item){
      if(item.turn_id!==this.turn)return;const data=item.data||{};
      if(item.type==='visual_response'){if(this.manager.frame(data.presentation,item.turn_id))this.renderer.load(data.presentation,item.turn_id,id=>id===this.turn);}
      if(item.type==='screen_scene')this.manager.compose(data.scene,item.turn_id);
      if(item.type==='tool_status'&&data.model){this.diagnostics.executor={provider:data.provider,model:data.model,route:data.route};document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);}
      if(item.type==='tts_status')this.status('Готовлю серверный голос…');
      if(item.type==='audio_start')this.status('Ответ готовится к воспроизведению');
      if(item.type==='tts_error')this.state('error',window.GoBotClient.explain(data.code));
      if(['error','cancelled'].includes(item.type))this.state('error','Ответ прерван. Нажми и задай вопрос снова.');
      if(item.type==='final'){this.manager.finish(item.turn_id);if(this.manager.state!=='error')this.status('Удерживай круг для следующего вопроса.');}
    }
    async acquire(){
      if(!navigator.locks)throw Error('Браузер не поддерживает безопасное владение аудио. Используй актуальный Safari/Chrome.');
      let ready;const granted=new Promise(resolve=>ready=resolve);this.lockTask=navigator.locks.request('gobot-browser-device-audio',{ifAvailable:true},async lock=>{ready(!!lock);if(lock)await new Promise(resolve=>this.releaseLock=resolve);});
      if(!await granted)throw Error('GoBot уже активен в другой вкладке. Выключи его там.');
    }
    async enable(){
      if(this.enabled||this.enabling)return;this.enabling=true;const generation=++this.generation;
      try{
        if(this.profile.interaction_mode==='wake')throw Error('Русская активация «ГоБот» ещё не настроена. Выбери удержание или нажатие в панели.');
        const settings=window.GoBotClient.getSettings();
        if(settings.stt==='openai'&&!settings.paid_stt)throw Error('В панели управления разреши OpenAI STT для своих запросов.');
        if(settings.speak&&settings.tts==='openai'&&!settings.paid)throw Error('В панели управления разреши OpenAI TTS для своих запросов.');
        const unlocked=window.GoBotClient.unlockAudio();unlocked.catch(()=>{});await this.acquire();
        if(generation!==this.generation){this.releaseLock?.();this.releaseLock=null;return;}
        const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});stream.getTracks().forEach(track=>track.stop());await unlocked;
        if(generation!==this.generation){this.releaseLock?.();this.releaseLock=null;return;}
        this.enabled=true;this.state('idle','Готов. Удерживай круг и говори.');document.getElementById('device-enable').textContent='GoBot включён';
        this.timerPoll=setInterval(()=>this.refreshTimer(),5000);
        if(this.profile.keep_screen_awake&&navigator.wakeLock){try{this.wakeLock=await navigator.wakeLock.request('screen');this.wakeLock.addEventListener('release',()=>{this.wakeLock=null;});}catch(_){this.status('Готов. Браузер не разрешил удержание экрана.');}}
      }catch(error){this.releaseLock?.();this.releaseLock=null;if(generation===this.generation)this.state('error',error.message);}finally{this.enabling=false;}
    }
    async press(){
      if(!this.enabled){this.status('Сначала нажми «Включить GoBot».');return;}
      if(this.held||window.GoBotClient.isRecording())return;
      this.held=true;this.captureAbort=new AbortController();window.GoBotClient.stop();this.manager.visual=null;this.renderer.clearImage();
      window.GoBotHooks.captureOptions={signal:this.captureAbort.signal,minDurationMs:400,minSpeechMs:180};
      await window.GoBotClient.startRecording();if(!this.held)this.cancelCapture();
    }
    release(){if(!this.held)return;this.held=false;window.GoBotClient.endRecording();}
    cancelCapture(){this.held=false;this.captureAbort?.abort();window.GoBotClient.cancelRecording();if(this.enabled)this.state('idle','Запись отменена.');}
    async refreshTimer(){if(document.hidden||!this.enabled||this.manager.visual?.type!=='timer_widget')return;const frame=this.manager.visual;try{const data=await(await fetch('/api/device/timers')).json();if(this.manager.visual!==frame)return;if(!data.timers?.some(timer=>timer.id===(frame.metadata.timer_id||frame.id))&&frame.metadata.deadline>Date.now()/1000){frame.metadata.deadline=null;frame.metadata.state='cancelled';}}catch(_){}}
    pause(text){this.generation++;this.enabled=false;clearInterval(this.timerPoll);this.cancelCapture();window.GoBotClient.stop();this.releaseLock?.();this.releaseLock=null;this.wakeLock?.release().catch(()=>{});this.wakeLock=null;this.state('muted',text);document.getElementById('device-enable').textContent='Возобновить GoBot';}
  }
  window.GoBotDeviceApp=DeviceApp;
  window.addEventListener('DOMContentLoaded',()=>{const app=new DeviceApp();window.goBotDevice=app;app.init().catch(error=>app.status(error.message));});
})();
