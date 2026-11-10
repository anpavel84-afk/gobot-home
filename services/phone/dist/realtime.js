/* Audio-only WebRTC client. GoBot owns all control; no provider data channel/key. */
(() => {
  'use strict';
  const uuid=()=>crypto.randomUUID();
  class NativeVoice {
    constructor({fetcher=window.fetch.bind(window),Peer=window.RTCPeerConnection,media=navigator.mediaDevices,emit=()=>{}}={}){
      this.fetcher=fetcher;this.Peer=Peer;this.media=media;this.emit=emit;this.generation=0;this.id=null;this.ready=false;this.recording=false;this.pending=false;this.level=0;this.playing=false;this.events=null;this.closing=null;this.commands=Promise.resolve();this.response=null;this.drained=false;this.heard=false;this.followupTimer=null;this.held=false;this.sentPlayback=new Set();
    }
    status(text){document.getElementById('realtime-status')?.replaceChildren(document.createTextNode(text));document.getElementById('mic-status')?.replaceChildren(document.createTextNode(text));window.goBotDevice?.status(text);}
    async api(path,body,signal){
      const r=await this.fetcher('/api/realtime/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal,keepalive:path.endsWith('/command')&&body.action==='close'});
      if(!r.ok)throw Error('Realtime: '+(r.status===403?'нужно отдельное разрешение и серверный лимит':r.status===409?'сессия занята или команда уже неактуальна':'соединение недоступно'));
      return r.json();
    }
    selected(){return document.getElementById('conversation-engine')?.value==='realtime';}
    async acquire(){
      if(!navigator.locks)throw Error('Безопасное владение микрофоном недоступно в этом браузере.');
      let ready;const granted=new Promise(r=>ready=r);
      this.lockTask=navigator.locks.request('gobot-browser-device-audio',{ifAvailable:true},async lock=>{ready(!!lock);if(lock)await new Promise(r=>this.releaseLock=r);});
      if(!await granted)throw Error('Аудиосессия GoBot уже открыта в другой вкладке.');
    }
    async start({microphone=true}={}){
      if(this.ready)return;
      if(this.closing)await this.closing;
      if(this.id)throw Error('Предыдущая сессия ещё не закрыта. Нажми «Остановить ответ».');
      if(this.pending)throw Error('Соединение ещё подготавливается.');
      if(!document.getElementById('realtime-consent')?.checked)throw Error('Сначала разреши Realtime API в панели управления.');
      this.pending=true;const epoch=++this.generation;this.id=uuid();const id=this.id;
      this.abort=new AbortController();this.commands=Promise.resolve();
      this.status('Подключаю Realtime. Говори после сигнала готовности.');
      try{
        const admission=await (await this.fetcher('/api/realtime/status')).json();
        if(!admission.budget?.enabled)throw Error('Для Realtime ещё не задан отдельный серверный лимит.');
        await this.acquire();if(epoch!==this.generation)throw Error('Запуск отменён');
        this.context=new AudioContext();await this.context.resume();
        this.output=document.createElement('audio');this.output.autoplay=true;this.output.playsInline=true;
        this.output.volume=Number(window.GoBotClient.getSettings().volume||.8);
        const pc=this.pc=new this.Peer();
        this.sender=pc.addTransceiver('audio',{direction:'sendrecv'}).sender;
        if(microphone)await this.ensureMicrophone(epoch);
        pc.ontrack=e=>{
          if(epoch!==this.generation)return;
          this.output.srcObject=e.streams[0];this.analyser=this.context.createAnalyser();this.analyser.fftSize=256;
          this.context.createMediaStreamSource(e.streams[0]).connect(this.analyser);
          this.output.play().catch(()=>{if(epoch===this.generation)void this.close('Нажми «Включить GoBot», чтобы разрешить звук.');});
        };
        pc.onconnectionstatechange=()=>{
          if(epoch!==this.generation)return;
          clearTimeout(this.disconnectTimer);
          if(pc.connectionState==='failed'||pc.connectionState==='closed')void this.close('Соединение потеряно. Возобнови GoBot.');
          else if(pc.connectionState==='disconnected')this.disconnectTimer=setTimeout(()=>void this.close('Соединение потеряно'),5000);
        };
        // Intentionally no createDataChannel(). SDP policy also rejects a modified client.
        await pc.setLocalDescription(await pc.createOffer());
        await this.gather(pc,this.abort.signal);
        const config=window.GoBotClient.getSettings();
        const answer=await this.api('sessions',{session_id:id,sdp:pc.localDescription.sdp,conversation_id:window.GoBotClient.conversationId(),consent:true,requested_voice:config.voice||'marin',expert_quota_consent:config.quota===true,speaker_consent:document.getElementById('realtime-speaker-enabled')?.checked===true,personalization_mode:document.getElementById('realtime-personalization')?.value||'guest',remember:config.remember,speak:config.speak,client_kind:window.GoBotHooks?.clientKind||'panel'},this.abort.signal);
        if(epoch!==this.generation)throw Error('Запуск отменён');
        if(!answer.configuration_confirmed||answer.model!=='gpt-realtime-2.1-mini')throw Error('Сервер не подтвердил выбранную модель');
        await pc.setRemoteDescription({type:'answer',sdp:answer.sdp});if(this.speakerMirror)this.speakerMirror.ready=answer.speaker_readiness?.ready===true;
        this.events=new EventSource('/api/realtime/sessions/'+id+'/events');
        this.events.onmessage=e=>{if(epoch===this.generation)this.event(JSON.parse(e.data));};
        this.events.onerror=()=>{if(epoch===this.generation)void this.close('Управляющее соединение потеряно');};
        this.ready=true;this.pending=false;this.status('Realtime готов. Удерживай круг и говори.');this.meter(epoch);
      }catch(e){if(epoch===this.generation){this.pending=false;await this.close(e.message);}throw e;}
    }
    async ensureMicrophone(epoch=this.generation){
      if(this.stream?.active)return;
      const stream=await this.media.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
      if(epoch!==this.generation){stream.getTracks().forEach(t=>t.stop());throw Error('Запуск отменён');}
      this.stream=stream;
      const track=stream.getAudioTracks()[0];track.enabled=false;
      track.onended=()=>{if(epoch===this.generation)void this.close('Микрофон отключён браузером').catch(()=>{});};
      await this.sender.replaceTrack(track);
      if(epoch!==this.generation){stream.getTracks().forEach(t=>t.stop());throw Error('Запуск отменён');}
      this.inputAnalyser=this.context.createAnalyser();this.inputAnalyser.fftSize=512;this.inputSource=this.context.createMediaStreamSource(stream);this.inputSource.connect(this.inputAnalyser);
      if(window.GoBotRealtimeSpeaker){this.speakerMirror?.close();const mirror=new window.GoBotRealtimeSpeaker(this);this.speakerMirror=mirror;await mirror.attach(this.context,stream);if(epoch!==this.generation){mirror.close();throw Error('Запуск отменён');}}
    }
    gather(pc,signal){
      if(pc.iceGatheringState==='complete')return Promise.resolve();
      return new Promise((resolve,reject)=>{
        const done=error=>{clearTimeout(timer);pc.removeEventListener('icegatheringstatechange',changed);signal.removeEventListener('abort',aborted);error?reject(error):resolve();};
        const changed=()=>{if(pc.iceGatheringState==='complete')done();};const aborted=()=>done(Error('Запуск отменён'));
        const timer=setTimeout(()=>done(Error('Не удалось подготовить аудиосоединение')),8000);
        pc.addEventListener('icegatheringstatechange',changed);signal.addEventListener('abort',aborted,{once:true});
      });
    }
    command(action,extra={}){
      const id=this.id;if(!id)return Promise.reject(Error('Realtime не включён'));
      const body={command_id:uuid(),action,...extra};
      const result=this.commands.then(()=>this.api('sessions/'+id+'/command',body));
      this.commands=result.catch(()=>{});return result;
    }
    mic(enabled){this.stream?.getAudioTracks().forEach(t=>t.enabled=enabled);if(this.speakerMirror){this.speakerMirror.active=enabled;if(!enabled)this.speakerMirror.ring=[];}document.getElementById('device-mic')?.replaceChildren(document.createTextNode(enabled?'● Микрофон включён · аудио в OpenAI, локальный Speaker ID':'○ Микрофон закрыт'));}
    async pttStart(){
      if(this.recording||this.held)return false;
      const capture={};this.captureToken=capture;this.held=true;clearTimeout(this.followupTimer);this.mic(false);
      if(this.output)this.output.muted=true;
      try{
        await this.start();if(!this.held||this.captureToken!==capture)return false;
        await this.ensureMicrophone();if(!this.held||this.captureToken!==capture)return false;
        const reply=await this.command('ptt_start');if(!this.held||this.captureToken!==capture)return false;
        this.speakerMirror?.begin(reply.speaker_segment_id);
        this.startedAt=performance.now();this.meterAt=this.startedAt;this.speechMs=0;this.recording=true;this.mic(true);
        this.status('Слушаю. Отпусти, когда закончишь.');window.GoBotHooks?.onListening?.();return true;
      }catch(e){if(this.captureToken===capture){this.held=false;this.status(e.message);}return false;}
    }
    async pttEnd(){
      void this.speakerMirror?.flush();
      this.held=false;this.captureToken=null;this.mic(false);
      if(this.pending&&!this.ready){await this.close('Нажатие завершилось до готовности соединения');return;}
      if(!this.recording)return;
      this.recording=false;
      if(performance.now()-this.startedAt<350||this.speechMs<180){await this.command('ptt_cancel');this.status('Слишком короткое или тихое нажатие.');return;}
      await this.command('ptt_end');this.status('Готовлю ответ…');
    }
    async sendText(text){
      if(!text.trim())return;
      await this.start({microphone:false});this.mic(false);await this.command('text',{text});
    }
    event(item){
      if(item.session_id&&item.session_id!==this.id)return;
      if(item.type==='speaker_readiness'){
        if(this.speakerMirror)this.speakerMirror.ready=item.data.ready===true;
        if(!item.data.ready)this.speakerStatus('Локальный Speaker ID: '+(item.data.reason==='no_enrolled_consenting_profiles'?'нужны профили и образцы в разделе «Семья»':item.data.reason==='calibration_required'?'нужна калибровка':item.data.reason||'не готов'));
      }
      if(item.type==='speaker_segment')this.speakerMirror?.begin(item.data.segment_id);
      if(item.type==='speaker_segment_end')void this.speakerMirror?.flush();
      if(item.type==='speaker_identity')this.speakerStatus(item.data.state==='recognized'?'Предположительное совпадение голоса · личная память не разрешена':'Говорящий неизвестен · гостевой контекст');
      if(item.type==='turn_started'){this.mic(false);this.heard=false;this.drained=false;this.response=null;window.GoBotHooks?.onTurn?.({turn_id:item.turn_id,conversation_id:item.conversation_id});}
      if(item.type==='playback_buffer_started'){
        this.response=item.data.response_id;this.drained=false;this.heard=false;this.playing=true;this.mic(false);
        if(this.output)this.output.muted=false;
      }
      if(item.type==='playback_buffer_stopped'){if(this.response===item.data.response_id){this.drained=true;this.quietAt=performance.now();}}
      if(item.type==='playback_cleared'||item.type==='interrupted'){this.playing=false;this.level=0;this.heard=false;}
      if(item.type==='listening'){this.status('Слушаю…');}
      if(item.type==='turn_complete'){void this.followup();}
      if(item.type==='closed'){void this.close('Разговор завершён. Нажми для нового обращения.');}
      if(item.type==='error'){void this.close('Realtime остановлен. Старый режим можно выбрать в панели.');}
      this.emit(item);
    }
    speakerStatus(text){document.getElementById('speaker-status')?.replaceChildren(document.createTextNode(text));document.getElementById('realtime-speaker-status')?.replaceChildren(document.createTextNode(text));}
    async followup(){
      const profile=window.goBotDevice?.profile;
      if(!profile?.conversation?.followup_enabled||!this.ready||document.hidden)return;
      clearTimeout(this.followupTimer);
      this.followupTimer=setTimeout(async()=>{
        if(!this.ready||document.hidden||this.held)return;
        try{await this.command('followup');if(!this.ready)return;this.mic(true);this.status('Жду продолжение · '+profile.conversation.followup_seconds+' секунд');}
        catch(_){this.mic(false);}
      },profile.conversation.echo_guard_ms);
    }
    meter(epoch){
      if(epoch!==this.generation||!this.ready)return;
      let level=0;
      if(this.analyser){const a=new Uint8Array(this.analyser.fftSize);this.analyser.getByteTimeDomainData(a);level=Math.sqrt(a.reduce((s,x)=>s+((x-128)/128)**2,0)/a.length);}
      this.level=this.output?.muted?0:level;
      if(this.recording&&this.inputAnalyser){const input=new Uint8Array(this.inputAnalyser.fftSize);this.inputAnalyser.getByteTimeDomainData(input);const rms=Math.sqrt(input.reduce((n,x)=>n+((x-128)/128)**2,0)/input.length);const now=performance.now();if(rms>.012)this.speechMs+=Math.min(100,now-this.meterAt);this.meterAt=now;}
      if(this.playing&&this.level>.004){
        this.quietAt=performance.now();
        if(!this.heard&&this.response){this.heard=true;void this.command('playback_started',{response_id:this.response});window.GoBotHooks?.onAnswerPlayback?.(window.goBotDevice?.turn);}
      }
      if(this.playing&&this.drained&&this.heard&&performance.now()-this.quietAt>300){
        this.playing=false;void this.command('playback_stopped',{response_id:this.response});
      }
      if(['interrupted','suspended','closed'].includes(this.context?.state)){void this.close('Аудио приостановлено. Возобнови GoBot.');return;}
      requestAnimationFrame(()=>this.meter(epoch));
    }
    snapshot(){return {level:this.level,playing:this.playing,feedback_playing:false,state:this.context?.state||'closed'};}
    async close(message='GoBot выключен'){
      if(this.closing)return this.closing;
      const id=this.id;this.generation++;this.ready=false;this.pending=false;this.held=false;this.captureToken=null;this.recording=false;
      this.abort?.abort();clearTimeout(this.followupTimer);clearTimeout(this.disconnectTimer);this.mic(false);
      this.stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});this.events?.close();this.events=null;
      this.speakerMirror?.close();this.speakerMirror=null;
      this.inputSource?.disconnect();this.inputSource=null;this.inputAnalyser=null;
      if(this.pc){this.pc.onconnectionstatechange=null;this.pc.close();this.pc=null;}
      if(this.output){this.output.pause();this.output.srcObject=null;this.output=null;}
      await this.context?.close().catch(()=>{});this.context=null;this.playing=false;this.level=0;
      this.releaseLock?.();this.releaseLock=null;this.status(message);
      if(!id)return;
      this.closing=this.api('sessions/'+id+'/command',{command_id:uuid(),action:'close'}).then(result=>{
        if(!result.hangup_confirmed&&result.hangup_confirmed!==undefined)throw Error('Сервер ещё закрывает аудиосессию');
        this.id=null;
      }).catch(e=>{this.status(e.message+' · повтори «Остановить ответ»');throw e;}).finally(()=>this.closing=null);
      return this.closing;
    }
  }
  window.GoBotNativeVoice=NativeVoice;
  const client=new NativeVoice({emit:item=>window.GoBotClient?.applyNativeEvent?.(item)});window.GoBotRealtime=client;
  for(const event of ['pagehide','offline'])window.addEventListener(event,()=>void client.close('Прослушивание приостановлено').catch(()=>{}));
  document.addEventListener('visibilitychange',()=>{if(document.hidden)void client.close('Возобнови GoBot после возвращения').catch(()=>{});});
  window.addEventListener('DOMContentLoaded',()=>{
    let select=document.getElementById('conversation-engine');
    if(!select){
      const section=document.createElement('section');section.className='reply';
      const label=document.createElement('label');label.textContent='Разговорный движок';select=document.createElement('select');select.id='conversation-engine';
      for(const [value,text] of [['legacy','Legacy · STT → CLI → TTS'],['realtime','Realtime Mini · кандидат']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option);}label.append(select);section.append(label);
      const consentLabel=document.createElement('label');consentLabel.className='check';const consent=document.createElement('input');consent.type='checkbox';consent.id='realtime-consent';consentLabel.append(consent,document.createTextNode('Разрешаю Realtime API в пределах отдельного серверного лимита'));section.append(consentLabel);
      const speakerLabel=document.createElement('label');speakerLabel.className='check';const speakerCheck=document.createElement('input');speakerCheck.type='checkbox';speakerCheck.id='realtime-speaker-enabled';speakerCheck.checked=true;speakerLabel.append(speakerCheck,document.createTextNode('Локально определять говорящего через ECAPA · без внешнего STT'));section.append(speakerLabel);
      const modeLabel=document.createElement('label');modeLabel.textContent='Характер и голос';const mode=document.createElement('select');mode.id='realtime-personalization';for(const [v,t] of [['guest','Нейтральный гостевой'],['confirmed_profile','Мой PIN-профиль · только голос и стиль']]){const o=document.createElement('option');o.value=v;o.textContent=t;mode.append(o);}modeLabel.append(mode);section.append(modeLabel);const speakerStatus=document.createElement('p');speakerStatus.id='realtime-speaker-status';speakerStatus.className='hint';section.append(speakerStatus);
      const p=document.createElement('p');p.id='realtime-status';p.className='hint';p.textContent='Тестовый кандидат. Запуск доступен только с отдельным серверным лимитом; страница сама сессию не запускает.';section.append(p);
      const anchor=document.getElementById('device-appearance')||document.querySelector('footer');
      if(anchor)anchor.before(section);else (document.querySelector('main details')||document.querySelector('main'))?.append(section);
    }
    select.value=document.body.dataset.conversationEngine||'legacy';
    fetch('/api/device/profile').then(r=>r.json()).then(data=>{select.value=document.body.dataset.conversationEngine||data.profile?.voice?.engine||'legacy';document.getElementById('realtime-consent').checked=data.profile?.voice?.realtime_consent===true;document.getElementById('realtime-speaker-enabled').checked=data.profile?.voice?.speaker_identity_enabled!==false;document.getElementById('realtime-personalization').value=data.profile?.voice?.personalization_mode||'guest';}).catch(()=>{});
    document.getElementById('realtime-consent')?.addEventListener('change',async e=>{
      if(!e.target.checked)await client.close().catch(()=>{});
      await fetch('/api/device/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:{realtime_consent:e.target.checked}})});
    });
    for(const [id,key] of [['realtime-speaker-enabled','speaker_identity_enabled'],['realtime-personalization','personalization_mode']])document.getElementById(id)?.addEventListener('change',async e=>{await client.close().catch(()=>{});await fetch('/api/device/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:{[key]:e.target.type==='checkbox'?e.target.checked:e.target.value}})});});
    select.addEventListener('change',async()=>{
      window.GoBotClient?.cancelRecording();await client.close().catch(()=>{});
      await fetch('/api/device/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:{engine:select.value}})});
    });
  });
})();
