/* Device interaction adapter. Speech/STT/SSE are exclusively GoBotClient/browser.js. */
(() => {
  'use strict';
  const activeVoice=()=>window.GoBotLive?.selected()?window.GoBotLive:window.GoBotRealtime;
  // Minimal bindings for the shared client engine, not a hidden second app or pipeline.
  const root=document.createElement('section');root.hidden=true;root.id='client-bindings';document.body.append(root);
  const selects={model:['auto','fast','reasoning','codex','google','mock'],tts:['openai','denis'],stt:['openai','whisper','mock'],'stt-mode':['file'],voice:[],'visual-source':['openverse','wikimedia','disabled']};
  const checks=new Set(['speak','paid','paid-stt','quota','remember','detailed-context','visual-contact-consent']);
  const ids=['question','send','stop','record','hold','volume','orb','answer','voice-status','mic-status','speaker-status','robot-label','result-badge','route-meta','route-statistics','context-statistics','topic-label','topic-name','rename-topic','saved-facts','memory-refresh','forget-conversation','memory-sources','history','new-conversation','refresh','services','provider-status','timer','visual-response','active-timers','visual-contact','visual-settings-save','visual-settings-status',...Object.keys(selects),...checks];
  for(const id of new Set(ids)){const node=document.createElement(id in selects?'select':checks.has(id)?'input':id==='question'?'textarea':'div');node.id=id;if(checks.has(id)){node.type='checkbox';node.checked=['speak','remember'].includes(id);}if(id in selects)for(const value of selects[id]){const option=document.createElement('option');option.value=option.textContent=value;node.append(option);}if(id==='volume')node.value='.8';root.append(node);}
  window.GoBotHooks={clientKind:'device'};
  class DeviceApp{
    constructor(){this.enabled=false;this.held=false;this.profile=null;this.turn=null;this.sent=new Set();this.generation=0;this.streamDone=true;this.releaseLock=null;this.captureAbort=null;this.sessionActive=false;this.serverAudioEnded=false;this.followupPending=false;this.sessionEpoch=0;}
    status(text){document.getElementById('device-status').textContent=text;}
    state(value,text){this.conversationState={idle:'STANDBY',muted:'STANDBY',listening:'LISTENING',recognizing:'PROCESSING',thinking:'PROCESSING',speaking:'SPEAKING',error:'ERROR',offline:'OFFLINE'}[value]||'STANDBY';if(this.manager)this.manager.state=value;if(text)this.status(text);const voice=activeVoice();document.getElementById('device-mic').textContent=voice?.engine==='live'&&voice.ready?(voice.recording?'● C: микрофон включён · непрерывный разговор':'○ C: микрофон заглушён · сессия оплачивается'):value==='listening'?'● Микрофон записывает вопрос':this.enabled?'○ Режим активен · микрофон по нажатию':'● Микрофон выключен';}
    async init(){
      const response=await fetch('/api/device/profile');if(!response.ok)throw Error('Не удалось загрузить профиль устройства');const data=await response.json();this.profile=data.profile;
      const {DeviceRenderer,SceneManager}=window.GoBotDeviceRenderer;this.manager=new SceneManager(this.profile);this.renderer=new DeviceRenderer(document.getElementById('device-screen'),this.profile);
      if(this.profile.has_screensaver)this.renderer.loadWallpaper();
      this.manager.onVisualChanged=(frame,turn)=>this.renderer.load(frame,turn,id=>id===this.turn);
      this.renderer.onImageError=(id,turn)=>{if(turn!==this.turn)return;this.status('Изображение не загрузилось. Ответ продолжается.');activeVoice()?.visualFailed?.(id,turn);};
      this.renderer.onImageReady=(_,turn)=>{if(turn===this.turn&&this.enabled)window.GoBotClient.trace?.()?.mark('visual_decoded');};
      this.renderer.onImagePresented=(id,turn)=>{if(turn===this.turn&&this.enabled&&!document.hidden){const trace=window.GoBotClient.trace?.();trace?.mark('visual_presented');trace?.flush();activeVoice()?.visualPresented?.(id,turn);}};
      const hooks=window.GoBotHooks;
      hooks.onNativeClosed=({reason,message,error})=>{
        this.cancelTapGuard();
        this.generation++;this.enabled=false;this.held=false;this.endConversation();this.streamDone=true;
        clearInterval(this.timerPoll);this.releaseLock?.();this.releaseLock=null;
        this.wakeLock?.release().catch(()=>{});this.wakeLock=null;
        this.lastNativeClosure=message;
        this.diagnostics||={};this.diagnostics.native_close={reason,error};document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);
        this.state(error?'error':'muted',message);document.getElementById('device-enable').textContent='Возобновить GoBot';
      };
      hooks.onSettingsApplied=profile=>{this.profile=profile;this.manager.profile=profile;this.renderer.setProfile(profile);if(!profile.conversation.followup_enabled)this.endConversation();};
      hooks.onScopeChanged=()=>{this.manager.visual=null;this.manager.scene=null;this.renderer.clearImage();this.renderer.wallpaper=null;this.pause('Разговор или профиль изменён. Возобнови GoBot.');};
      hooks.onStopped=()=>{this.endConversation();if(this.enabled)this.state('idle');};
      hooks.onTurn=({turn_id,continuation})=>{const previous=continuation?this.manager.visual:null;this.conversationEnded=false;this.turn=turn_id;this.manager.newTurn(turn_id);this.renderer.clearImage();this.preservedVisual=!!previous;if(previous){this.manager.visual=previous;this.renderer.load(previous,turn_id,id=>id===this.turn);}this.streamDone=false;this.sessionActive=true;this.serverAudioEnded=false;this.answerPlaybackStarted=false;this.audioStreamId=null;this.state('thinking','Готовлю ответ…');};
      hooks.onAnswerPlayback=turn=>{if(turn===this.turn)this.answerPlaybackStarted=true;};
      hooks.onLivePlayback=({playing,pending})=>{
        if(!this.enabled||activeVoice()?.engine!=='live')return;
        this.streamDone=!playing&&!pending;
        if(playing){this.manager.completed=false;this.manager.returnAt=null;this.state('speaking','Отвечаю. Можно перебить голосом.');}
        else if(pending)this.state('thinking','Задача ещё выполняется. Микрофон остаётся включён.');
        else{this.manager.finish(this.turn);this.state('idle','Можно продолжать разговор.');}
      };
      hooks.onListening=()=>{
        if(this.followupPending&&!this.held){
          this.state('listening','Жду продолжение разговора · '+this.profile.conversation.followup_seconds+' секунд');
          this.conversationState='FOLLOWUP_LISTENING';
          document.getElementById('device-mic').textContent='● Микрофон включён · локальное ожидание речи';
        }else this.state('listening','Слушаю. Отпусти круг, когда закончишь.');
      };
      hooks.onCapturePending=()=>this.status('Включаю микрофон…');
      hooks.onInputClosed=()=>this.state('thinking','Вопрос записан. Обрабатываю…');
      hooks.onRecognizing=()=>this.state('recognizing','Распознаю речь…');
      hooks.onCaptureError=message=>{this.endConversation();if(this.enabled)this.state('error',message);};
      hooks.onTranscript=async item=>{if(!this.enabled||!item.text?.trim()||this.sent.has(item.utterance_id))return;this.sent.add(item.utterance_id);if(this.sent.size>128)this.sent.delete(this.sent.values().next().value);await window.GoBotClient.send({continuation:this.followupPending});};
      hooks.onFollowupSilence=()=>{this.endConversation();this.state('idle','Окно продолжения закрыто. Удерживай круг для нового вопроса.');};
      hooks.onFollowupVoice=()=>this.state('listening','Слушаю продолжение. Отправлю после паузы.');
      hooks.onEvent=item=>this.event(item);
      hooks.onTrace=trace=>{this.diagnostics.timing=trace;document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);};
      hooks.onStreamEnd=({turn_id})=>{if(turn_id===this.turn){this.streamDone=true;this.manager.finish(turn_id);}};
      const canvas=document.getElementById('device-screen');
      canvas.onpointerdown=event=>{if(this.profile.interaction_mode!=='hold')return;event.preventDefault();try{canvas.setPointerCapture(event.pointerId);}catch(_){}this.press();};
      canvas.onpointerup=event=>{if(this.profile.interaction_mode==='hold'){event.preventDefault();this.release();}};
      canvas.onpointercancel=canvas.onlostpointercapture=()=>{if(this.held)this.cancelCapture();};
      canvas.onclick=()=>{if(this.profile.interaction_mode==='toggle')window.GoBotClient.isRecording()?this.release():this.press();};
      canvas.onkeydown=event=>{if(event.repeat)return;if(event.code==='Space'||event.code==='Enter'){event.preventDefault();window.GoBotClient.isRecording()?this.release():this.press();}};
      canvas.oncontextmenu=event=>event.preventDefault();
      document.getElementById('device-enable').onclick=()=>this.enable();document.getElementById('device-disable').onclick=()=>activeVoice()?.engine==='live'?void activeVoice().toggleMute():this.pause('Микрофон выключен');
      document.getElementById('device-stop').onclick=()=>{if(activeVoice()?.engine==='live'){void activeVoice().stopSpeech();return;}this.cancelCapture();window.GoBotClient.stop();this.state(this.enabled?'idle':'muted','Ответ остановлен');};
      document.getElementById('device-raster').onclick=()=>canvas.toBlob(blob=>{if(!blob)return;if(this.rasterURL)URL.revokeObjectURL(this.rasterURL);this.rasterURL=URL.createObjectURL(blob);const image=document.getElementById('raster-preview');image.src=this.rasterURL;image.width=canvas.width;image.height=canvas.height;image.hidden=false;},'image/png');
      document.addEventListener('visibilitychange',()=>{if(document.hidden)this.pause('Прослушивание приостановлено. Нажми «Возобновить GoBot».');});
      window.addEventListener('pagehide',()=>this.pause('Приостановлено'));window.addEventListener('offline',()=>{this.pause('Нет сети. После подключения возобнови GoBot.');this.state('offline');});
      window.addEventListener('online',()=>this.status('Сеть восстановлена. Нажми «Возобновить GoBot».'));
      window.GoBotUnified?.bindHooks();
      try{const result=await(await fetch('/api/device/timers')).json();const timer=result.timers?.[0];if(timer){this.turn='restored-timer';this.manager.newTurn(this.turn);this.manager.frame({id:timer.id,type:'timer_widget',title:'Таймер',metadata:timer,images:[]},this.turn);this.manager.state='idle';this.manager.finish(this.turn);}}catch(_){}
      this.diagnostics={client_id:this.profile.client_id,capabilities:data.capabilities,activation:data.activation};
      document.getElementById('device-diagnostics').textContent=JSON.stringify({client_id:this.profile.client_id,capabilities:data.capabilities,activation:data.activation},null,2);
      if(this.profile.interaction_mode==='toggle')document.getElementById('device-hint').textContent='Нажми круг для начала записи, ещё раз — для завершения. Затем вопрос отправится автоматически.';
      let previous=0;const draw=now=>{if(now-previous>=(this.profile.skin.reduced_motion?150:33)){previous=now;const audio=window.GoBotClient.audioSnapshot();if(this.enabled&&['suspended','interrupted','closed'].includes(audio.state))this.pause('Аудио приостановлено браузером. Нажми «Возобновить GoBot».');if(this.enabled&&!['listening','recognizing','error','offline'].includes(this.manager.state)){this.manager.state=(audio.playing||audio.feedback_playing)&&audio.level>.003?'speaking':this.streamDone?'idle':'thinking';}this.checkFollowup(audio);this.manager.tick(audio.playing);this.renderer.draw(this.manager,audio.level,now);}requestAnimationFrame(draw);};requestAnimationFrame(draw);
    }
    event(item){
      if(activeVoice()?.selected()&&['closed','error','warning'].includes(item.type))return;
      if(item.turn_id!==this.turn)return;const data=item.data||{};
      if(item.type==='meaning_mismatch'){
        this.manager.visual=null;this.manager.scene=null;this.manager.gallery=[];this.manager.galleryAt=null;this.renderer.clearImage();
        this.diagnostics.subject_alignment='needs_user_confirmation';
        document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);
      }
      if(item.type==='visual_response'){if(this.manager.frame(data.presentation,item.turn_id))this.renderer.load(data.presentation,item.turn_id,id=>id===this.turn);}
      if(item.type==='screen_scene')this.manager.compose(data.scene,item.turn_id);
      if(item.type==='tool_status'&&this.preservedVisual&&data.topic?.outcome==='new_topic'){
        this.preservedVisual=false;this.manager.visual=null;this.renderer.clearImage();
      }
      if(item.type==='tool_status'&&data.model){this.diagnostics.executor={provider:data.provider,model:data.model,route:data.route};document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);}
      if(item.type==='tool_status'&&['conversation_ended','output_stopped'].includes(data.status)){
        this.conversationEnded=true;this.endConversation();this.captureAbort?.abort();this.streamDone=true;
        this.manager.visual=null;this.manager.scene=null;this.renderer.clearImage();this.state('idle','Хорошо. Жду нового обращения.');
      }
      if(item.type==='tts_status')this.status('Готовлю серверный голос…');
      if(item.type==='audio_start'){this.audioStreamId=data.audio_id;this.status('Ответ готовится к воспроизведению');}
      if(item.type==='audio_stop'){
        if(data.audio_id!==this.audioStreamId)return;
        if(data.reason==='finished'&&data.chunks>0)this.serverAudioEnded=true;
        else this.endConversation();
      }
      if(item.type==='tts_error'){this.endConversation();}
      if(item.type==='tts_error')this.state('error',window.GoBotClient.explain(data.code));
      if(['error','cancelled'].includes(item.type)){this.endConversation();}
      if(['error','cancelled'].includes(item.type))this.state('error','Ответ прерван. Нажми и задай вопрос снова.');
      if(item.type==='final'){this.diagnostics.visual=data.trace?.find(entry=>entry.visual_decision)?.visual_decision||null;document.getElementById('device-diagnostics').textContent=JSON.stringify(this.diagnostics,null,2);this.manager.finish(item.turn_id);if(this.manager.state!=='error'&&!this.conversationEnded)this.status('Удерживай круг для следующего вопроса.');}
    }
    endConversation(){
      this.sessionEpoch++;this.sessionActive=false;this.serverAudioEnded=false;this.followupPending=false;
      clearTimeout(this.followupTimer);
    }
    checkFollowup(audio){
      if(activeVoice()?.selected())return;
      const policy=window.GoBotUnified?.enabled&&window.GoBotUnified.mode==='legacy'?{...this.profile.conversation,followup_enabled:true,followup_seconds:10}:this.profile.conversation;
      if(!this.enabled||!policy?.followup_enabled||!this.sessionActive||!this.serverAudioEnded||!this.answerPlaybackStarted||audio.playing||audio.feedback_playing||this.followupPending)return;
      this.followupPending=true;const epoch=this.sessionEpoch,turn=this.turn;
      this.followupTimer=setTimeout(async()=>{
        if(!this.enabled||!this.sessionActive||epoch!==this.sessionEpoch||turn!==this.turn||document.hidden)return;
        const snapshot=window.GoBotClient.audioSnapshot();if(snapshot.playing||snapshot.feedback_playing){this.followupPending=false;return;}
        this.captureAbort=new AbortController();
        window.GoBotHooks.captureOptions={signal:this.captureAbort.signal,minDurationMs:400,minSpeechMs:policy.min_speech_ms,
          vad:{windowMs:policy.followup_seconds*1000,silenceMs:policy.silence_ms,minSpeechMs:policy.min_speech_ms}};
        this.serverAudioEnded=false;
        this.state('listening','Жду продолжение разговора · '+policy.followup_seconds+' секунд');this.conversationState='FOLLOWUP_LISTENING';
        window.GoBotClient.trace?.()?.mark('followup_opened');
        const result=await window.GoBotClient.startRecording({followup:true});
        if(result===false)this.endConversation();
      },policy.echo_guard_ms);
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
        if(activeVoice()?.selected()){
          await activeVoice().start();this.enabled=true;this.state('idle',activeVoice().engine==='live'?'C · GPT-Live 1 готов. Можно говорить.':'Realtime готов. Удерживай круг и говори.');document.getElementById('device-enable').textContent='GoBot включён';return;
        }
        const settings=window.GoBotClient.getSettings();
        if(settings.stt==='openai'&&!settings.paid_stt)throw Error('В панели управления разреши OpenAI STT для своих запросов.');
        if(settings.speak&&settings.tts==='openai'&&!settings.paid)throw Error('В панели управления разреши OpenAI TTS для своих запросов.');
        const unlocked=window.GoBotClient.unlockAudio();unlocked.catch(()=>{});await this.acquire();
        if(generation!==this.generation){this.releaseLock?.();this.releaseLock=null;return;}
        const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});stream.getTracks().forEach(track=>track.stop());await unlocked;
        if(generation!==this.generation){this.releaseLock?.();this.releaseLock=null;return;}
        await window.GoBotClient.prepareFeedback?.();
        window.GoBotClient.feedback?.configure({...this.profile.feedback,enabled:this.profile.feedback?.enabled!==false&&settings.speak});
        if(generation!==this.generation)return;
        this.enabled=true;this.state('idle','Готов. Удерживай круг и говори.');document.getElementById('device-enable').textContent='GoBot включён';
        this.timerPoll=setInterval(()=>this.refreshTimer(),5000);
        if(this.profile.keep_screen_awake&&navigator.wakeLock){try{this.wakeLock=await navigator.wakeLock.request('screen');this.wakeLock.addEventListener('release',()=>{this.wakeLock=null;});}catch(_){this.status('Готов. Браузер не разрешил удержание экрана.');}}
      }catch(error){this.releaseLock?.();this.releaseLock=null;if(generation===this.generation)this.state('error',error.message);}finally{this.enabling=false;}
    }
    async press(){
      if(!this.enabled){this.status(this.lastNativeClosure||'Сначала нажми «Включить GoBot».');return;}
      if(this.held)return;
      const audio=window.GoBotClient.audioSnapshot();
      if(audio.playing||audio.feedback_playing){
        if(this.profile.interaction_mode==='toggle'){
          this.status('Ответ продолжается. Для нового вопроса сначала нажми «Остановить ответ».');return;
        }
        // Do not mute, cancel provider audio or capture a microphone for a short accidental tap.
        this.held=true;const generation=this.generation;
        const guard={};this.tapGuard=guard;
        const confirmed=await new Promise(resolve=>{guard.resolve=resolve;guard.timer=setTimeout(()=>resolve(true),500);});
        if(!confirmed||this.tapGuard!==guard||!this.held||!this.enabled||generation!==this.generation)return;
        this.tapGuard=null;this.held=false;
      }
      return this.beginPress();
    }
    async beginPress(){
      if(activeVoice()?.selected()){if(this.held)return;this.held=true;const started=await activeVoice().pttStart();if(!started)this.held=false;return;}
      if(this.followupPending||window.GoBotClient.isRecording()&&!this.held){this.cancelCapture();}
      if(this.held||window.GoBotClient.isRecording())return;
      this.held=true;this.captureAbort=new AbortController();
      try{
        window.GoBotClient.stop();this.sessionActive=true;this.manager.visual=null;this.renderer.clearImage();
        window.GoBotHooks.captureOptions={signal:this.captureAbort.signal,minDurationMs:400,minSpeechMs:180};
        const started=await window.GoBotClient.startRecording();
        if(started===false){this.held=false;this.captureAbort.abort();return;}
        if(!this.held)this.cancelCapture();
      }catch(_){this.held=false;this.captureAbort.abort();this.state('error','Не удалось начать запись. Обнови страницу и попробуй снова.');}
    }
    cancelTapGuard(){const guard=this.tapGuard;if(!guard)return false;this.tapGuard=null;this.held=false;clearTimeout(guard.timer);guard.resolve(false);return true;}
    release(){if(this.cancelTapGuard())return;if(!this.held)return;this.held=false;window.GoBotClient.endRecording();}
    cancelCapture(){if(this.cancelTapGuard())return;this.held=false;this.captureAbort?.abort();window.GoBotClient.cancelRecording();if(this.enabled)this.state('idle','Запись отменена.');}
    async refreshTimer(){if(document.hidden||!this.enabled||this.manager.visual?.type!=='timer_widget')return;const frame=this.manager.visual;try{const data=await(await fetch('/api/device/timers')).json();if(this.manager.visual!==frame)return;if(!data.timers?.some(timer=>timer.id===(frame.metadata.timer_id||frame.id))&&frame.metadata.deadline>Date.now()/1000){frame.metadata.deadline=null;frame.metadata.state='cancelled';}}catch(_){}}
    pause(text){this.generation++;this.enabled=false;clearInterval(this.timerPoll);this.cancelCapture();window.GoBotClient.stop();this.releaseLock?.();this.releaseLock=null;this.wakeLock?.release().catch(()=>{});this.wakeLock=null;this.state('muted',text);document.getElementById('device-enable').textContent='Возобновить GoBot';}
  }
  window.GoBotDeviceApp=DeviceApp;
  window.addEventListener('DOMContentLoaded',()=>{const app=new DeviceApp();window.goBotDevice=app;app.init().catch(error=>app.status(error.message));});
})();
