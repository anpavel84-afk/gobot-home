/* GPT-Live C: continuous WebRTC audio; GoBot owns sideband, tools and permissions. */
(() => {
 'use strict';const uuid=()=>crypto.randomUUID();
 class LiveVoice{
  constructor(){this.engine='live';this.label='GPT-Live 1';this.id=null;this.ready=false;this.pending=false;this.generation=0;this.level=0;this.playing=false;this.recording=false;this.muted=false;this.closing=null;this.commands=Promise.resolve();this.apiBase='live';this.currentTurn=null;}
  get fetcher(){return window.fetch.bind(window);}
  selected(){return document.getElementById('conversation-engine')?.value==='live';}
  status(text){for(const id of ['live-status','mic-status']){const node=document.getElementById(id);if(node)node.textContent=text;}window.goBotDevice?.status(text);}
  async api(path,body,signal){const r=await this.fetcher('/api/live/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal,keepalive:path.endsWith('/command')&&body.action==='end'});if(!r.ok){let code='live_request_failed';try{code=(await r.json()).detail||code;}catch(_){}throw Error('GPT-Live: '+code);}return r.json();}
  command(action,extra={}){if(!this.id)return Promise.resolve({closed:true});const id=this.id;const work=this.commands.then(()=>this.api('sessions/'+id+'/command',{command_id:uuid(),action,...extra}));this.commands=work.catch(()=>{});return work;}
  async start(){
   if(this.closing)await this.closing;if(this.ready)return;if(this.pending)throw Error('Live ещё подключается');
   this.pending=true;let state;try{state=await (await this.fetcher('/api/live/status')).json();}catch(e){this.pending=false;throw e;}if(!state.enabled){this.pending=false;throw Error('Live не разрешён для этого устройства в Owner Full Test');}
   this.pending=true;const generation=++this.generation;this.id=uuid();const id=this.id;this.abort=new AbortController();this.commands=Promise.resolve();this.status('Подключаю C · GPT-Live 1. Говорите после готовности.');
   try{
    await window.GoBotNativeVoice.prototype.acquire.call(this);
    this.context=new AudioContext();await this.context.resume();
    this.output=document.createElement('audio');this.output.autoplay=true;this.output.playsInline=true;this.output.volume=Number(window.GoBotClient.getSettings().volume||.8);
    const pc=this.pc=new RTCPeerConnection();this.channel=pc.createDataChannel('oai-events'); // Server allows no client commands on it.
    const audio={echoCancellation:true,noiseSuppression:document.getElementById('live-browser-ns')?.checked!==false};
    this.stream=await navigator.mediaDevices.getUserMedia({audio,video:false});
    if(generation!==this.generation){this.stream.getTracks().forEach(t=>t.stop());throw Error('Запуск отменён');}
    const track=this.stream.getAudioTracks()[0];track.enabled=false;track.onended=()=>void this.close('Микрофон отключён браузером','microphone_ended');pc.addTrack(track,this.stream);
    this.inputSource=this.context.createMediaStreamSource(this.stream);this.inputAnalyser=this.context.createAnalyser();this.inputAnalyser.fftSize=512;this.inputSource.connect(this.inputAnalyser);
    this.diagnostic({stage:'capture_settings',requested:audio,effective:track.getSettings?.()||{},supported:navigator.mediaDevices.getSupportedConstraints?.()||{}});
    if(window.GoBotRealtimeSpeaker){this.speakerMirror=new window.GoBotRealtimeSpeaker(this);await this.speakerMirror.attach(this.context,this.stream);}
    pc.ontrack=e=>{if(generation!==this.generation)return;this.output.srcObject=e.streams[0];this.analyser=this.context.createAnalyser();this.analyser.fftSize=512;this.context.createMediaStreamSource(e.streams[0]).connect(this.analyser);this.output.play().catch(()=>void this.close('Браузер запретил звук. Включите GoBot повторно.','webrtc_failed'));};
    pc.onconnectionstatechange=()=>{if(generation!==this.generation)return;if(['failed','closed'].includes(pc.connectionState))void this.close('Соединение Live потеряно','webrtc_failed');};
    await pc.setLocalDescription(await pc.createOffer());await window.GoBotNativeVoice.prototype.gather.call(this,pc,this.abort.signal);
    const settings=window.GoBotClient.getSettings();
    const answer=await this.api('sessions',{session_id:id,conversation_id:window.GoBotClient.conversationId(),sdp:pc.localDescription.sdp,consent:true,
     requested_model:'gpt-live-1',requested_voice:settings.voice||'marin',personalization_mode:document.getElementById('realtime-personalization')?.value||'guest',
     speaker_consent:document.getElementById('realtime-speaker-enabled')?.checked===true,remember:settings.remember,
     input_mode:document.getElementById('live-input-mode')?.value||'continuous',client_kind:window.GoBotHooks?.clientKind||'panel'},this.abort.signal);
    if(generation!==this.generation)throw Error('Запуск отменён');
    if(!answer.configuration_confirmed||answer.model!=='gpt-live-1'||answer.delegation!=='client')throw Error('Live не подтвердил модель или безопасную конфигурацию');
    await pc.setRemoteDescription({type:'answer',sdp:answer.sdp});
    await this.connected(pc,this.abort.signal);
    this.events=new EventSource('/api/live/sessions/'+id+'/events');this.events.onmessage=e=>{if(generation===this.generation)this.event(JSON.parse(e.data));};this.events.onerror=()=>{if(generation===this.generation)void this.close('Управляющее соединение Live потеряно','events_disconnected');};
    this.inputMode=document.getElementById('live-input-mode')?.value||'continuous';this.ready=true;this.pending=false;this.muted=this.inputMode==='hold';this.mic(!this.muted);this.status('C · GPT-Live 1 готов. '+(state.general_backend_ready===false?'Инструменты доступны; быстрый backend для обычных вопросов ещё не подключён. ':'')+(this.muted?'Удерживайте круг для микрофона.':'Можно говорить и перебивать; микрофон остаётся включён.'));this.meter(generation);
   }catch(error){await this.close(error.message,'webrtc_failed');throw error;}
  }
  async connected(pc,signal){
   const started=performance.now();
   while(pc.connectionState!=='connected'){
    if(signal.aborted||['failed','closed'].includes(pc.connectionState))throw Error('Соединение Live отменено');
    if(performance.now()-started>12000)throw Error('Не удалось установить аудиосоединение Live');
    await new Promise(resolve=>setTimeout(resolve,50));
   }
  }
  mic(enabled){this.stream?.getAudioTracks().forEach(t=>t.enabled=enabled);this.recording=enabled;if(this.speakerMirror)this.speakerMirror.active=enabled;const n=document.getElementById('device-mic');if(n)n.textContent=enabled?'● C: микрофон включён · OpenAI Live, локальный Speaker ID':'○ C: микрофон заглушён; открытая Live-сессия всё ещё оплачивается';}
  async toggleMute(){this.muted=!this.muted;this.mic(!this.muted);await this.command(this.muted?'mute':'unmute');}
  async pttStart(){if(!this.ready){this.status('Сначала включите GoBot и дождитесь готовности C.');return false;}if(this.inputMode==='hold'){this.muted=false;this.mic(true);await this.command('unmute');}return true;}
  async pttEnd(){if(this.inputMode==='hold'){this.muted=true;this.mic(false);await this.command('mute');}}
  async sendText(text){if(!text.trim())return;await this.start();await this.command('text',{text});}
  async stopSpeech(){
   if(!this.ready)return;this.output.muted=true;this.speechBlocked=true;this.inputAfterStop=false;this.stoppedInputEnd=this.lastInputEnd||0;this.stopQuietAt=0;
   this.status('Речь остановлена. Микрофон и согласованная задача продолжают работать.');await this.command('stop_speech');
  }
  visualPresented(frame,turn){if(this.ready&&turn===this.currentTurn)void this.command('visual_presented',{frame_id:frame,turn_id:turn}).catch(()=>{});}
  visualFailed(frame,turn){if(this.ready&&turn===this.currentTurn)void this.command('visual_failed',{frame_id:frame,turn_id:turn}).catch(()=>{});}
  event(event){
   if(event.session_id&&event.session_id!==this.id)return;
   const data=event.data||{};
   if(event.type==='turn_started'){this.currentTurn=event.turn_id;window.GoBotHooks?.onTurn?.({turn_id:event.turn_id,conversation_id:event.conversation_id});}
   if(event.type==='ready'){if(this.speakerMirror)this.speakerMirror.ready=false;this.diagnostic({stage:'session_ready',model:data.model,voice:data.voice});}
   if(event.type==='speaker_readiness'&&this.speakerMirror)this.speakerMirror.ready=data.ready===true;
   if(event.type==='speaker_segment')this.speakerMirror?.begin(data.segment_id);
   if(event.type==='speaker_segment_end')void this.speakerMirror?.flush();
   if(event.type==='live_input_delta'){this.lastInputEnd=data.end_ms;if(this.speechBlocked&&data.end_ms>this.stoppedInputEnd)this.inputAfterStop=true;this.diagnostic({stage:'live_input_delta',text:data.text});}
   if(event.type==='text_delta')this.diagnostic({stage:'answer_delta',text:data.text});
   if(event.type==='usage')this.diagnostic({stage:'usage',...data});
   if(event.type==='closing'){this.mic(false);if(this.output)this.output.muted=true;this.status('Разговор завершается. Микрофон выключен.');}
   if(event.type==='visual_status')document.getElementById('realtime-visual-status')?.replaceChildren(document.createTextNode(data.message||''));
   if(event.type==='closed')void this.close(data.final_usage_confirmed?'Live завершён. Микрофон выключен.':'Live закрыт локально; финальный usage ещё не подтверждён.',data.reason||'user_stop',true);
   if(event.type==='backend_status'){
    const text='Backend C · '+data.model+' · '+data.state+(data.reason?' · '+data.reason:'');
    const node=document.getElementById('live-status');if(node)node.textContent=text;
    this.diagnostic({stage:'live_backend',state:data.state,model:data.model,timings:data.timings,usage:data.usage,estimated_usd:data.estimated_usd});
   }
   window.GoBotExpertUI?.event(event);window.GoBotClient?.applyNativeEvent?.(event);
  }
  meter(generation){
   if(generation!==this.generation||!this.ready)return;
   const rms=node=>{if(!node)return 0;const a=new Float32Array(node.fftSize);node.getFloatTimeDomainData(a);return Math.sqrt(a.reduce((sum,x)=>sum+x*x,0)/a.length);};
   const signal=rms(this.analyser),input=rms(this.inputAnalyser),now=performance.now();
   if(this.speechBlocked){if(signal<.001){if(!this.stopQuietAt)this.stopQuietAt=now;if(this.inputAfterStop&&now-this.stopQuietAt>=500){this.speechBlocked=false;this.output.muted=false;}}else this.stopQuietAt=0;}
   const wasPlaying=this.playing;this.level=this.output?.muted?0:signal;if(this.level>.002)this.lastAudible=now;this.playing=this.level>.002||!!(this.lastAudible&&now-this.lastAudible<500);
   if(this.playing&&!wasPlaying)window.GoBotHooks?.onAnswerPlayback?.(this.currentTurn);
   if(now-(this.lastHeartbeat||0)>700){this.lastHeartbeat=now;void this.command('activity',{input_active:!this.muted&&input>.003,playback_active:this.playing}).catch(()=>{});this.diagnostic({stage:'level',rms:input,speech_ms:0});}
   requestAnimationFrame(()=>this.meter(generation));
  }
  diagnostic(data){window.GoBotOwnerTest?.diagnostic(data);}
  snapshot(){return {level:this.level,playing:this.playing,feedback_playing:false,state:this.context?.state||'closed'};}
  close(message='Live выключен',reason='user_stop',serverClosed=false){
   if(this.closing)return this.closing;
   const id=this.id;this.generation++;this.ready=false;this.pending=false;this.mic(false);this.abort?.abort();this.events?.close();this.events=null;
   this.stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});this.speakerMirror?.close();this.speakerMirror=null;
   if(this.output){this.output.muted=true;this.output.pause();this.output.srcObject=null;}this.pc?.close();this.pc=null;
   this.inputSource?.disconnect();this.context?.close().catch(()=>{});this.releaseLock?.();this.releaseLock=null;this.level=0;this.playing=false;
   this.status(message);this.diagnostic({stage:'closed'});window.GoBotExpertUI?.clear();
   this.closing=(async()=>{
    await Promise.resolve(); // Publish the shared close promise before a synchronous terminal path clears it.
    try{if(id&&!serverClosed)await this.api('sessions/'+id+'/command',{command_id:uuid(),action:'end',reason:['page_hidden','network_offline','webrtc_failed','microphone_ended','profile_changed','settings_changed','events_disconnected'].includes(reason)?reason:'user_stop'});}
    catch(_){this.status(message+' Подтверждение закрытия сервера не получено.');}
    finally{this.id=null;this.closing=null;window.GoBotHooks?.onNativeClosed?.({reason,message,error:!['user_stop','idle_timeout','conversation_ended','session_time_limit','settings_changed'].includes(reason)});}
   })();return this.closing;
  }
 }
 window.GoBotLiveVoice=LiveVoice;const live=window.GoBotLive=new LiveVoice();
 window.addEventListener('DOMContentLoaded',()=>{
  const select=document.getElementById('conversation-engine');if(!select)return;
  const option=document.createElement('option');option.value='live';option.textContent='C · GPT-Live 1 · API 1.1 пока не подтверждён';select.append(option);
  if(document.body.dataset.conversationEngine==='live')select.value='live';
  const section=document.createElement('details');section.id='live-controls';const summary=document.createElement('summary');summary.textContent='C · GPT-Live 1 · непрерывный разговор';section.append(summary);
  const p=document.createElement('p');p.id='live-status';p.textContent='Кандидат Live 1, не 1.1. Быстрый backend — gpt-6-luna при включении в Owner Full Test. $0.05/мин открытой сессии, backend и изображения отдельно. A/B сохранены.';section.append(p);
  const mode=document.createElement('select');mode.id='live-input-mode';for(const [value,text] of [['continuous','Непрерывный микрофон'],['hold','Микрофон только при удержании']]){const n=document.createElement('option');n.value=value;n.textContent=text;mode.append(n);}section.append(mode);
  const label=document.createElement('label'),ns=document.createElement('input');ns.type='checkbox';ns.checked=true;ns.id='live-browser-ns';label.append(ns,document.createTextNode('Browser noise suppression · отдельная проба C; эхо-защита остаётся включённой'));section.append(label);
  for(const [text,handler] of [['Заглушить / включить микрофон',()=>live.toggleMute()],['Остановить речь',()=>live.stopSpeech()],['Завершить разговор',()=>live.close()]]){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=()=>void handler().catch(e=>live.status(e.message));section.append(b);}
  (document.querySelector('.device-controls')||document.querySelector('main')).after(section);
  for(const n of [mode,ns])n.onchange=()=>void live.close('Настройки C изменены. Включите новую сессию.','settings_changed');
 });
 for(const [event,reason] of [['pagehide','page_hidden'],['offline','network_offline']])window.addEventListener(event,()=>void live.close('Live приостановлен',reason));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)void live.close('Live приостановлен','page_hidden');});
})();
