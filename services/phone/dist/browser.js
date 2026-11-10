'use strict';
const $ = id => document.getElementById(id);
const uuid = () => crypto.randomUUID();
let conversation = localStorage.getItem('gobot.conversation') || uuid();
localStorage.setItem('gobot.conversation', conversation);
let active = null, audio = null, gain = null, nextAt = 0, epoch = 0, recording = null, micPending = false;
let lastSpeakerJob=null,transcriptPending=false;
let outputAnalyser=null,transcriptionAbort=null;
let requestTrace=null,feedbackBuffer=null,earconBuffer=null,feedbackGain=null;const feedbackSources=new Set();
const sources = new Set(), seen = new Set(), audioSequences=new Map(),playedSegments=new Map();
const visuals=window.GoBotVisual?new window.GoBotVisual.BrowserVisualRenderer($('visual-response'),$('active-timers')):null;
let currentTurn=null,currentTopic=null;
if(visuals&&window.GoBotHooks?.clientKind!=='device')visuals.onImageReady=(id,img)=>{
  const trace=requestTrace,turn=currentTurn,expectedEpoch=epoch;
  if(!img.naturalWidth||!trace||!turn)return;
  trace.mark('visual_decoded');
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    if(turn===currentTurn&&expectedEpoch===epoch&&visuals.frames.has(id)&&img.isConnected&&!document.hidden){
      trace.mark('visual_presented');trace.flush();
    }
  }));
};
const errors = {
  no_real_executor_available: 'Реальный исполнитель недоступен. Проверь квоту, авторизацию и состояние ниже. Mock можно выбрать отдельно.',
  openai_stt_consent_required: 'Для OpenAI STT нужно разрешить отправку аудио и платный API-запрос. Локальный Whisper выбирается отдельно.',
  openai_stt_unavailable: 'OpenAI STT недоступен. Проверь API-баланс и доступ к модели. Whisper автоматически не включался.',
  openai_stt_key_missing: 'Ключ OpenAI не задан.',
  openai_stt_auth_failed: 'OpenAI отклонил API-ключ. Обнови его в настройках ключа.',
  openai_stt_access_denied: 'OpenAI отказал в доступе к распознаванию для этого API-проекта.',
  openai_stt_model_unavailable: 'Модель распознавания недоступна этому API-проекту.',
  openai_stt_rate_or_balance_limited: 'OpenAI сообщил о лимите запросов или API-баланса. Whisper автоматически не включался.',
  quota_consent_required: 'Нужно разрешить расход квоты CLI для запроса.',
  agent_policy_or_consent_required: 'Запуск CLI заблокирован политикой или отсутствием согласия на расход квоты.',
  agent_model_unavailable: 'Выбранная в CLI модель недоступна этой авторизации. Нужна настройка модели адаптера.',
  agent_arguments_rejected: 'Установленный CLI отклонил параметры запуска. Нужна проверка совместимости.',
  agent_quota_exceeded: 'CLI сообщил об исчерпании квоты или ограничении частоты.',
  agent_access_denied: 'Провайдер отказал в доступе выбранному CLI.',
  agent_auth_required: 'CLI требует обновить официальную авторизацию.',
  agent_policy_denied: 'Вызов остановлен политикой безопасности CLI.',
  agent_network_failed: 'CLI не смог связаться с сервером провайдера.',
  gemini_google_project_required: 'Google требует Cloud Project для этого аккаунта. Автоматически создавать платный проект GoBot не будет.',
  gemini_account_ineligible: 'Google отклонил доступ аккаунта к Gemini CLI (IneligibleTierError). Вход выполнен; доступ к сервису пока не предоставлен. Выбери Codex.',
  oauth_login_required: 'Требуется официальная авторизация CLI на компьютере.',
  isolation_not_verified: 'Изоляция CLI требует повторной проверки после изменения программы.',
  openai_tts_consent_required: 'Текст получен. Для OpenAI голоса разреши платный API синтез.',
  openai_tts_key_missing: 'Ключ OpenAI ещё не сохранён.',
  openai_tts_unavailable: 'OpenAI голос недоступен. Проверь API-баланс и доступ к модели. Другой голос не включался.',
  openai_tts_configuration_rejected: 'OpenAI отклонил настройки голоса. Нужна проверка совместимости API.',
  openai_tts_incomplete: 'OpenAI не завершил озвучивание. Другой голос не включался.',
  openai_tts_timeout: 'OpenAI не успел подготовить голос. Текст сохранён; другой голос не включался.',
  timeout: 'Превышено время ответа.', brain_unavailable: 'Основной сервер недоступен.',
};
function renderTiming(bundle){
  if(!bundle)return;const current=window.GoBotClient?.trace();if(current&&bundle.client?.trace_id===current.id)bundle.client=current.snapshot();
  const node=$('latency-trace');if(node)node.textContent=JSON.stringify(bundle,null,2);
  const summary=$('latency-summary');if(summary){const events=bundle.client?.events||[];const value=name=>{const found=events.find(e=>e.name===name);return found?Math.round(found.ms)+' мс':'не измерено / выключено';};summary.textContent='От конца ввода: локальный сигнал '+value('earcon_started')+'; текст '+value('first_text')+'; первый ненулевой звук ответа '+value('first_answer_playback')+'. Playback — оценка AudioContext, не акустический замер.';}
}
function explain(code) { return errors[code] || 'Запрос не завершён: ' + code; }
function renderDisplay(text){
  const root=$('answer');root.replaceChildren();let code=false,block=null;
  for(const line of text.split('\n')){
    if(line.startsWith('```')){code=!code;block=null;continue;}
    if(code){if(!block){block=document.createElement('pre');root.append(block);}block.textContent+=(block.textContent?'\n':'')+line;continue;}
    const row=document.createElement('p');
    const plain=line.replace(/^#{1,6}\s+/,'').replace(/^\s*[-*+]\s+/,'• ');
    // Build DOM nodes, never interpret model output as HTML.
    const pattern=/(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;let cursor=0;
    for(const match of plain.matchAll(pattern)){
      const span=document.createElement('span');span.textContent=plain.slice(cursor,match.index);row.append(span);
      const node=document.createElement(match[2]?'strong':match[3]?'code':'a');node.textContent=match[2]||match[3]||match[4];
      if(match[5]){node.href=match[5];node.rel='noopener noreferrer';node.target='_blank';}
      row.append(node);cursor=match.index+match[0].length;
    }
    const tail=document.createElement('span');tail.textContent=plain.slice(cursor);row.append(tail);root.append(row);
  }
}
async function unlockAudio() {
  if (!audio||audio.state==='closed') { audio = new (window.AudioContext || window.webkitAudioContext)(); gain = audio.createGain();
    if(audio.createAnalyser){outputAnalyser=audio.createAnalyser();outputAnalyser.fftSize=256;gain.connect(outputAnalyser);outputAnalyser.connect(audio.destination);}else gain.connect(audio.destination); }
  gain.gain.value = Number($('volume').value);
  await audio.resume();
  if(audio.state&&audio.state!=='running')throw Error('audio_context_paused');
}
async function prepareFeedback(){
  await unlockAudio();
  feedbackGain?.disconnect();feedbackGain=audio.createGain();
  earconBuffer=audio.createBuffer(1,Math.round(audio.sampleRate*.08),audio.sampleRate);const tone=earconBuffer.getChannelData(0);for(let i=0;i<tone.length;i++)tone[i]=Math.sin(2*Math.PI*740*i/audio.sampleRate)*.3*Math.sin(Math.PI*i/tone.length);feedbackGain.gain.value=.22;feedbackGain.connect(gain);
  try{const response=await fetch('/feedback-wait.wav');if(!response.ok)throw Error();feedbackBuffer=await audio.decodeAudioData(await response.arrayBuffer());}catch(_){feedbackBuffer=null;}
}
function stopFeedback(fade,trace){
  if(!feedbackSources.size)return;
  if(fade){if([...feedbackSources].some(s=>s.gobotAudioRole==='filler'))trace?.mark('filler_preempted');feedbackGain.gain.cancelScheduledValues(audio.currentTime);feedbackGain.gain.setValueAtTime(feedbackGain.gain.value,audio.currentTime);feedbackGain.gain.linearRampToValueAtTime(0,audio.currentTime+.04);}
  for(const source of feedbackSources){try{source.stop(audio.currentTime+(fade?.04:0));}catch(_){}}feedbackSources.clear();
}
function playFeedback(role,trace){
  if(!audio||audio.state!=='running'||!feedbackGain||!$('speak').checked||Number($('volume').value)<=0)return;
  const buffer=role==='earcon'?earconBuffer:feedbackBuffer;
  if(!buffer)return;
  feedbackGain.gain.cancelScheduledValues(audio.currentTime);feedbackGain.gain.setValueAtTime(feedback?.config.volume??.22,audio.currentTime);
  const source=audio.createBufferSource();source.buffer=buffer;source.connect(feedbackGain);source.gobotAudioRole=role;feedbackSources.add(source);source.onended=()=>feedbackSources.delete(source);source.start();
  trace?.mark(role==='earcon'?'earcon_started':'filler_started');
}
const feedback=window.GoBotTiming?new window.GoBotTiming.FeedbackController({play:playFeedback,stop:stopFeedback}):null;
function inputClosed(info={}){
  requestTrace?.inputClosed(info.input_closed_at);if(requestTrace){requestTrace.audioSeconds=info.audio_seconds??null;requestTrace.sttMode=$('stt-mode').value||'file';}requestTrace?.mark('encoding_start');
  window.GoBotHooks?.onInputClosed?.();
  const trace=requestTrace;requestAnimationFrame(()=>trace?.mark('feedback_rendered'));
  if(window.GoBotHooks?.clientKind==='device'&&trace){feedback?.begin(trace);}
}
function clearAudio() {
  epoch++; for (const source of sources) { try { source.stop(); } catch (_) {} } sources.clear(); seen.clear(); audioSequences.clear();playedSegments.clear(); nextAt = 0;
}
async function play(data, runEpoch) {
  const key = data.audio_id + ':' + data.seq;
  if (runEpoch !== epoch || seen.has(key)) return;
  requestTrace?.mark('first_audio_received');
  const expected=audioSequences.get(data.audio_id)||0;
  if(data.seq!==expected)throw new Error('audio_sequence_gap');
  audioSequences.set(data.audio_id,expected+1);
  if (data.format !== 'pcm_s16le' || ![22050, 24000].includes(data.sample_rate)) throw new Error('unsupported_pcm');
  while (nextAt > audio.currentTime + 4) {
    await new Promise(resolve => setTimeout(resolve, 40));
    if (runEpoch !== epoch) return;
  }
  seen.add(key);
  const raw = atob(data.pcm), bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  if (bytes.length % 2) throw new Error('pcm_alignment');
  let firstNonzero=null;
  const pcm = new DataView(bytes.buffer), buffer = audio.createBuffer(1, bytes.length / 2, data.sample_rate), channel = buffer.getChannelData(0);
  for (let i = 0; i < channel.length; i++) {channel[i] = pcm.getInt16(i * 2, true) / 32768;if(firstNonzero===null&&Math.abs(channel[i])>.001)firstNonzero=i;}
  requestTrace?.mark('decode_complete');if(firstNonzero!==null)feedback?.answerReady();
  const source = audio.createBufferSource(); source.buffer = buffer; source.connect(gain);
  nextAt = Math.max(nextAt, audio.currentTime + .04); sources.add(source);
  const turn=currentTurn;
  source.onended = () => {sources.delete(source);if(runEpoch===epoch&&!sources.size){requestTrace?.playbackFinished?.(active===null);renderTiming(window.gobotLastTrace);}if(runEpoch===epoch&&data.segment_id){const milliseconds=(playedSegments.get(data.segment_id)||0)+buffer.duration*1000;playedSegments.set(data.segment_id,milliseconds);fetch('/api/audio/playback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({turn_id:turn,segment_id:data.segment_id,milliseconds})}).catch(()=>{});}}; source.start(nextAt);requestTrace?.mark('scheduled');
  const trace=requestTrace,startAt=nextAt+(firstNonzero||0)/data.sample_rate;
  const acknowledge=()=>{if(runEpoch!==epoch||audio.state!=='running')return;if(audio.currentTime<startAt){setTimeout(acknowledge,10);return;}trace?.mark('first_answer_playback');trace?.flush();if(trace&&window.gobotLastTrace){window.gobotLastTrace.client=trace.snapshot();renderTiming(window.gobotLastTrace);window.GoBotHooks?.onTrace?.(window.gobotLastTrace);}};if(firstNonzero!==null&&trace&&!trace.playbackPending){trace.playbackPending=true;setTimeout(acknowledge,Math.max(0,(startAt-audio.currentTime)*1000));}
  nextAt += buffer.duration;
}
function stop(preserveWaiting=false) {
  if(preserveWaiting!==true){feedback?.cancel();if(requestTrace&&!requestTrace.complete){requestTrace.mark("cancelled");requestTrace.flush();}}
  if (active) active.abort(); active = null; clearAudio();
  transcriptionAbort?.abort();transcriptionAbort=null;window.GoBotHooks?.onStopped?.();
  visuals?.interrupt();
  $('send').disabled = false; $('orb').classList.remove('busy'); $('result-badge').textContent = 'Остановлено';
}
async function send() {
  if(transcriptPending)return;
  const text = $('question').value.trim(); if (!text) return;
  stop(true);if(!requestTrace||requestTrace.complete){requestTrace=window.GoBotTiming?new window.GoBotTiming.TurnTrace(uuid()).inputClosed():null;}requestTrace?.mark("chat_submit");visuals?.begin();$('timer').hidden=true; const runEpoch = epoch;
  const controller = new AbortController(); active = controller;
  $('send').disabled = true; $('answer').textContent = ''; $('voice-status').textContent = '';
  $('orb').classList.add('busy'); $('result-badge').textContent = 'Получаем ответ';
  let canSpeak=$('speak').checked;
  if(canSpeak){try{await unlockAudio();}catch(_){canSpeak=false;$('voice-status').textContent='Не удалось включить воспроизведение. Этот ответ придёт текстом; API синтеза не вызывается.';}}
  let answer = '', terminal = false;const dispatchAt=performance.now();let firstDeltaAt=null;currentTurn=uuid();const utterance=lastUtterance;lastUtterance=null;
  window.GoBotHooks?.onTurn?.({turn_id:currentTurn,conversation_id:conversation});
  const sendTurn=currentTurn;
  try {
    const response = await fetch('/api/chat/stream', {method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
      body: JSON.stringify({text, mode: $('model').value, conversation_id: conversation, turn_id: currentTurn, request_id:currentTurn,utterance_id:utterance,remember:$('remember').checked,context_detail:$('detailed-context').checked?'detailed':'standard', correlation_id: uuid(),
        trace_id:requestTrace?.id, usage_consent: $('quota').checked, speak: canSpeak, tts_provider: $('tts').value, tts_voice: $('voice').value || 'marin', paid_tts_consent: $('paid').checked,speaker_job_id:lastSpeakerJob,client_kind:window.GoBotHooks?.clientKind||'panel'})});
    if (!response.ok) throw new Error('http_' + response.status);
    const reader = response.body.getReader(), decoder = new TextDecoder(); let pending = '';
    while (true) {
      const part = await reader.read(); pending += decoder.decode(part.value || new Uint8Array(), {stream: !part.done});
      if (pending.length > 2000000) throw new Error('event_limit');
      let end;
      while ((end = pending.indexOf('\n\n')) >= 0) {
        const frame = pending.slice(0, end); pending = pending.slice(end + 2);
        const line = frame.split('\n').find(value => value.startsWith('data: ')); if (!line) continue;
        const item = JSON.parse(line.slice(6)), data = item.data || {};
        if (runEpoch !== epoch) return;
        window.GoBotHooks?.onEvent?.(item);
        if (item.type === 'text_delta') { if(firstDeltaAt===null)firstDeltaAt=performance.now()-dispatchAt;requestTrace?.mark('first_text');answer += data.text;renderDisplay(answer);visuals?.syncDisplay(answer); }
        else if (item.type === 'tool_status') {
          if(data.status==='loading_visual')visuals?.loading();
          if(data.status==='preparing_visual_attachment')visuals?.loading();
          if(data.presentation_plan)$('route-statistics').textContent='Визуальный план: '+data.presentation_plan.visual_strategy+' · '+data.presentation_plan.visual_priority+' · '+data.presentation_plan.reason;
          if(data.topic){currentTopic=data.topic.topic_id;$('topic-label').textContent='Тема: '+(data.topic.label||'новая')+' · '+data.topic.outcome;if(document.activeElement!==$('topic-name'))$('topic-name').value=data.topic.label||'';}
          if(data.context)$('context-statistics').textContent=JSON.stringify(data.context,null,2);
          if(data.provider)$('robot-label').textContent = data.provider;
          if(data.model||data.provider==='local')$('route-meta').textContent='Отвечает: '+(data.provider==='bridge:antigravity'?'Antigravity':data.provider==='bridge:codex'?'Codex':'GoBot локально')+' · '+(data.model||(String(data.reason||'').startsWith('server_driven_visual_')?'визуальный ответ':'серверный инструмент'))+' · '+(data.route||'');
          if(data.status==='guest_context'){conversation=data.conversation_id;localStorage.setItem('gobot.conversation',conversation);$('speaker-status').textContent='Личность не подтверждена: используем гостевой контекст, личная история закрыта.';}
        }
        else if(item.type==='visual_response'){visuals?.render(data.presentation);visuals?.syncDisplay(answer);}
        else if(item.type==='screen_scene'&&data.phase==='answer_complete'&&!data.scene?.preserve_visual&&['icon','info_card'].includes(data.scene?.scene_type)){
          const payload=data.scene.visual_payload||{};
          visuals?.render({namespace:'gobot.ui',version:2,id:'scene-'+currentTurn,type:'info_card',title:payload.title||data.scene.visual_subject,
            text:data.scene.scene_type==='info_card'?payload.text||'':'',images:[],metadata:{state:payload.data_status==='unverified'?'unavailable':'ready',icon:payload.icon}});visuals?.syncDisplay(answer);
        }
        else if(item.type==='tts_status')$('voice-status').textContent='Готовлю серверный голос…';
        else if (item.type === 'audio_start') $('voice-status').textContent = 'Серверный ИИ-голос: ' + data.provider + ' · ' + data.voice;
        else if (item.type === 'audio_chunk') await play(data, runEpoch);
        else if (item.type === 'tts_error') {feedback?.cancel();requestTrace?.mark('error');$('voice-status').textContent = explain(data.code);}
        else if (item.type === 'widget_command') {if(!visuals?.hasTimer(data.command?.payload?.timer_id)){$('timer').hidden = false;const seconds=Math.ceil((data.command?.payload?.duration_ms||300000)/1000);$('timer').textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0')+' · таймер';} }
        else if (item.type === 'final') {
          terminal = true; if(requestTrace){window.gobotLastTrace={client:requestTrace.snapshot(),stt:requestTrace.stt,gateway_stt:requestTrace.gatewayStt,brain:data.telemetry,bridge:data.bridge_telemetry};requestTrace.flush();renderTiming(window.gobotLastTrace);window.GoBotHooks?.onTrace?.(window.gobotLastTrace);} $('result-badge').textContent = data.mock ? 'Mock · диагностика' : 'Ответ · ' + data.provider;
          const usage=data.usage?Object.entries(data.usage).map(([key,value])=>key+': '+value).join(', '):'Исполнитель не сообщил счётчики токенов';
          $('route-statistics').textContent='Модель: '+(data.model||'локально / диагностика')+' · первый текст после отправки в Brain: '+Math.round(firstDeltaAt||0)+' мс · маршрутизация: '+(data.router_ms==null?'—':data.router_ms.toFixed(2)+' мс')+' · '+(data.billing_kind==='cli_subscription'?'Квота CLI-подписки, без пересчёта в доллары':data.billing_kind==='api_tokens'?'Оплачиваемые API-токены':'Локальная обработка')+' · '+usage;
          if(data.quality)$('route-statistics').textContent+=' · Проверка: '+data.quality.method+' · обязательна: '+(data.quality.verification_required?'да':'нет')+' · сложность / фактическая неопределённость / последствия: '+data.quality.complexity+' / '+data.quality.factual_uncertainty+' / '+data.quality.consequence_risk+' (внутренние уровни, не вероятности)';
          if(data.presentation_plan?.visual_needed)$('route-statistics').textContent+=' · Визуал: '+data.presentation_plan.visual_strategy+' / '+data.presentation_plan.visual_priority+' · '+data.presentation_plan.reason;
          if(data.speech_metrics?.first_audio_server!=null)$('route-statistics').textContent+=' · Первый аудиочанк сервера: '+Math.round(data.speech_metrics.first_audio_server)+' мс';
        }
        else if (['error', 'cancelled'].includes(item.type)) { terminal = true; feedback?.cancel();requestTrace?.mark('error');clearAudio(); $('result-badge').textContent = 'Не завершено'; $('voice-status').textContent = explain(data.code || 'cancelled'); }
      }
      if (part.done) break;
    }
    if (!terminal) throw new Error('stream_disconnected');
  } catch (error) {
    if (error.name !== 'AbortError') { feedback?.cancel();requestTrace?.mark('error');clearAudio(); $('voice-status').textContent = explain(error.message); $('result-badge').textContent = 'Ошибка'; }
  } finally {
    if(requestTrace)requestTrace.complete=true;
    if (active === controller) { active = null; $('send').disabled = false; $('orb').classList.remove('busy'); await loadHistory();await refreshMemory(); }
    window.GoBotHooks?.onStreamEnd?.({turn_id:sendTurn});
  }
}
let liveSocket=null,recordStoppedAt=null,lastUtterance=null;
async function showSpeaker(job,initial){
  let state=initial||{state:'unknown'};
  for(let i=0;i<30;i++){
    $('speaker-status').textContent=state.state==='recognized' ? 'Говорящий: '+state.name+' · для личной истории нужен PIN профиля' :
      state.state==='ambiguous' ? 'Говорящий: похожие голоса, уточни профиль' : state.state==='insufficient_audio' ? 'Слишком мало качественной речи для определения голоса' : 'Неизвестный голос · гостевой контекст';
    if(!job||state.reason!=='identity_pending')return;
    await new Promise(resolve=>setTimeout(resolve,300));
    try{state=await(await fetch('/api/speaker/'+job)).json();}catch(_){return;}
  }
}
async function startRecording() {
  if (recording || micPending) return; micPending = true;
  window.GoBotHooks?.onCapturePending?.();
  $('record').textContent='Запрашиваем микрофон…';$('mic-status').textContent='Запрашиваем доступ к микрофону…';
  try {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error('Микрофон требует доверенного HTTPS. Открой адрес Tailscale.');
    // File dictation must not wait for playback AudioContext/autoplay permission on iOS.
    // Request the microphone within the original user gesture.
    if($('stt-mode').value==='live')await unlockAudio();
    stop();
    const captureEpoch=epoch;
    lastSpeakerJob=null;lastUtterance=uuid();requestTrace=window.GoBotTiming?new window.GoBotTiming.TurnTrace(lastUtterance):null;$('question').value='';
    const provider=$('stt').value,consent=$('paid-stt').checked,live=$('stt-mode').value==='live';
    if(provider==='openai'&&!consent){$('paid-stt').scrollIntoView?.({block:'center',behavior:'smooth'});$('paid-stt').focus();throw new Error(explain('openai_stt_consent_required'));}
    if(live&&provider!=='openai')throw new Error('Потоковый режим доступен у OpenAI. Для Whisper/Mock выбери готовую фразу.');
    transcriptPending=true;$('send').disabled=true;
    if(live){
      const socket=new WebSocket('wss://'+location.host+'/api/audio/live');liveSocket=socket;let partial='';
      await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=()=>reject(new Error('WSS недоступен'));});
      const ready=new Promise((resolve,reject)=>{
        socket.onmessage=e=>{const item=JSON.parse(e.data),data=item.data||{};
          if(item.type==='stt_ready')resolve();
          if(item.type==='stt_partial'){partial+=data.text;$('question').value=partial;$('mic-status').textContent='Распознаю речь · промежуточный текст';}
          if(item.type==='stt_final'){requestTrace?.mark('stt_final_received');if(requestTrace)requestTrace.stt=data.telemetry;transcriptPending=false;$('send').disabled=false;lastSpeakerJob=data.speaker_job_id;$('question').value=data.text;$('mic-status').textContent='Финальный текст готов. Проверь и отправь. До первого текста: '+Math.round(data.first_interim_ms||0)+' мс · после окончания речи: '+Math.round(data.speech_end_to_final_ms)+' мс';showSpeaker(data.speaker_job_id,data.speaker);socket.close();}
          if(item.type==='error'){transcriptPending=false;$('send').disabled=false;$('question').value='';const error=new Error(explain(data.code));reject(error);$('mic-status').textContent=error.message;recording?.cancel();recording=null;socket.close();}
        };
        socket.onclose=()=>{if(recording){recording.cancel();recording=null;} $('record').textContent='Начать запись';if(transcriptPending){transcriptPending=false;$('send').disabled=false;$('question').value='';$('mic-status').textContent='Распознавание прервано до финального текста.';}};
      });
      socket.send(JSON.stringify({provider:'openai',paid_consent:consent,trace_id:requestTrace?.id||lastUtterance,visual_prefetch:$('model').value!=='mock'&&$('quota').checked}));
      await Promise.race([ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error('OpenAI STT не подтвердил готовность')),10000))]);
      recording=await GoBotCapture.start({context:audio,onInputClosed:inputClosed,onChunk:chunk=>{
        if(socket.bufferedAmount>512000){recording?.cancel();socket.close();$('mic-status').textContent='Аудиосеть перегружена. Запись остановлена.';return;}
        if(socket.readyState===WebSocket.OPEN)socket.send(chunk);
      },onStop:()=>{recording=null;recordStoppedAt=performance.now();$('record').textContent='Начать запись';$('mic-status').textContent='Распознаю речь · ждём финальный текст';if(socket.readyState===WebSocket.OPEN)socket.send('end');}});
    }else{
      recording=await GoBotCapture.start({context:audio,...(window.GoBotHooks?.captureOptions||{}),onInputClosed:inputClosed,onStop:async(blob,info={})=>{
        requestTrace?.inputClosed(info.input_closed_at);requestTrace?.mark('encoding_end');
        if(captureEpoch!==epoch)return;
        window.GoBotHooks?.onRecognizing?.();
        recording=null;recordStoppedAt=performance.now();$('record').textContent='Начать запись';$('mic-status').textContent='Распознаю речь…';
        try{const query=new URLSearchParams({provider,paid_consent:String(consent),trace_id:requestTrace?.id||lastUtterance,visual_prefetch:String($('model').value!=='mock'&&$('quota').checked)});
          transcriptionAbort=new AbortController();
          requestTrace?.mark('upload_start');
          const response=await fetch('/api/audio/transcribe?'+query,{method:'POST',headers:{'Content-Type':blob.type},body:blob,signal:transcriptionAbort.signal});
          const result=await response.json();if(!response.ok)throw new Error(explain(result.detail||'stt_unavailable'));
          if(captureEpoch!==epoch)return;
          requestTrace?.mark('stt_final_received');if(requestTrace){requestTrace.stt=result.telemetry;requestTrace.gatewayStt=result.gateway_telemetry;}
          lastSpeakerJob=result.speaker_job_id;$('question').value=result.text;$('mic-status').textContent='Распознано. Исправь текст и отправь. '+result.provider+' · '+Math.round(result.stt_ms)+' мс';showSpeaker(result.speaker_job_id,result.speaker);
          transcriptPending=false;$('send').disabled=false;
          await window.GoBotHooks?.onTranscript?.({text:result.text,utterance_id:lastUtterance});
        }catch(error){if(captureEpoch===epoch){feedback?.cancel();requestTrace?.mark('error');requestTrace?.flush();$('mic-status').textContent=error.message;$('question').value='';window.GoBotHooks?.onCaptureError?.(error.message);}}
        finally{if(captureEpoch===epoch){transcriptPending=false;$('send').disabled=false;}}
      },onError:error=>{$('mic-status').textContent=error.message;recording=null;transcriptPending=false;$('send').disabled=false;window.GoBotHooks?.onCaptureError?.(error.message);}});
    }
    $('record').textContent = '■ Закончить диктовку';$('record').setAttribute('aria-pressed','true');$('record').classList.add('recording'); $('mic-status').textContent = 'Слушаю. Нажми ещё раз, когда закончишь.';
    window.GoBotHooks?.onListening?.();
    return true;
  } catch (error) {
    feedback?.cancel();transcriptPending=false;$('send').disabled=false;
    const message=error.name==='NotAllowedError'?'Доступ к микрофону не разрешён. В Safari открой настройки этого сайта и разреши микрофон. Если ссылка открыта внутри другого приложения, открой её в Safari.':error.name==='NotFoundError'?'Браузер не обнаружил микрофон.':error.name==='NotReadableError'?'Микрофон занят другим приложением. Закрой запись в нём и попробуй снова.':error.message;
    $('mic-status').textContent=message;$('record').textContent='🎙 Начать диктовку';$('record').setAttribute('aria-pressed','false');$('record').classList.remove('recording');
    window.GoBotHooks?.onCaptureError?.(message);
    if(liveSocket){liveSocket.close();liveSocket=null;}
    return false;
  }
  finally { micPending = false; }
}
function endRecording() { recording?.stop();$('record').setAttribute('aria-pressed','false');$('record').classList.remove('recording'); }
let held = false;
$('hold').onpointerdown = async event => { event.preventDefault(); held = true;try{$('hold').setPointerCapture?.(event.pointerId);}catch(_){} await startRecording(); if (!held) endRecording(); };
$('hold').onpointerup = $('hold').onpointercancel = event => { event.preventDefault(); held = false; endRecording(); };
$('hold').oncontextmenu = event => event.preventDefault();
$('record').onclick = () => recording ? endRecording() : startRecording();
$('send').onclick = send; $('stop').onclick = stop;
$('volume').oninput = () => { if (gain) gain.gain.value = Number($('volume').value); };
$('speak').onchange = () => { if (!$('speak').checked) stop(); };
$('tts').onchange = () => { $('voice').disabled = $('tts').value !== 'openai'; };
let historyVersion=0;
async function loadHistory() {
  const version=++historyVersion,requested=conversation;
  if(window.GoBotHooks?.clientKind==='device')return;
  try { const response = await fetch('/api/history/' + encodeURIComponent(requested),{cache:'no-store'}); const data = await response.json();
    if(version!==historyVersion||requested!==conversation)return;
    $('history').replaceChildren();
    for (const message of data.messages || []) {
      const p = document.createElement('p'); p.textContent = (message.role === 'user' ? 'Ты: ' : 'GoBot (' + message.provider + '): ') + message.content; $('history').append(p);
      if(message.role==='assistant' && message.presentation && window.GoBotVisual){
        const root=document.createElement('div');
        new window.GoBotVisual.BrowserVisualRenderer(root).render(message.presentation);
        $('history').append(root);
      }
    }
  } catch (_) { /* Status remains available separately. */ }
}
async function refresh() {
  try {
    const response = await fetch('/api/status', {cache: 'no-store'}); if (!response.ok) throw new Error(); const data = await response.json();
    $('services').replaceChildren(); for (const service of data.services) { const row = document.createElement('div'); row.className = 'service'; row.textContent = service.name + ': ' + (service.ok ? 'на связи' : 'недоступен'); $('services').append(row); }
    const backend = data.backend || {}, voice = backend.voice?.tts;
    if (voice && !$('voice').options.length) {for (const name of voice.voices) { const option = document.createElement('option'); option.value = option.textContent = name; $('voice').append(option); }window.GoBotClient?.restoreSettings();}
    $('provider-status').replaceChildren();
    for(const [name,state] of Object.entries(backend.agents||{})){
      if(name==='gemini')continue;
      const row=document.createElement('p');
      const label=name==='antigravity'?'Google Antigravity':name==='codex'?'Codex':name;
      let detail=state.reason ? explain(state.reason) : 'готов к запросу';
      if(state.reason==='quota_consent_required')detail=$('quota').checked?'Готов к твоему запросу':'Для запроса отметь согласие на расход квоты выше';
      if(state.reason==='isolation_not_verified')detail='Проверка безопасного запуска ещё не завершена';
      row.textContent=label+': '+(state.oauth_cached?'✓ Вход выполнен. ':'Вход не выполнен. ')+detail;
      $('provider-status').append(row);
    }
    const key=document.createElement('p');key.textContent='OpenAI ключ: '+(data.openai_key_configured?'сохранён':'не задан');$('provider-status').append(key);
  } catch (_) { $('services').textContent = 'Сервер недоступен.'; }
}
$('refresh').onclick = refresh;
$('quota').checked=localStorage.getItem('gobot.cli-quota-consent')==='true';
$('quota').onchange=()=>{localStorage.setItem('gobot.cli-quota-consent',String($('quota').checked));refresh();};
$('new-conversation').onclick = () => { stop(); conversation = uuid();currentTopic=null;lastUtterance=null; localStorage.setItem('gobot.conversation', conversation); loadHistory();refreshMemory(); };
$('question').oninput=()=>{lastUtterance=null;};
$('remember').onchange=()=>{$('new-conversation').onclick();$('context-statistics').textContent=$('remember').checked?'Архив включён.':'Не запоминать: только оперативная память, до часа.';};
async function loadVisualSettings(){try{const response=await fetch('/api/settings/visual');if(!response.ok)return;const state=await response.json();$('visual-source').value=state.provider||'openverse';$('visual-contact').value=state.contact||'';$('visual-settings-status').textContent=state.provider==='openverse'?'Openverse: без ключа и регистрации, с локальным кэшем.':state.configured?'Wikimedia: контакт настроен; доступ проверяется при загрузке.':'Внешние изображения отключены. Локальные виджеты работают.';}catch(_){}}
$('visual-settings-save').onclick=async()=>{try{const response=await fetch('/api/settings/visual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:$('visual-source').value,contact:$('visual-contact').value,public_contact_consent:$('visual-contact-consent').checked})});if(!response.ok)throw Error();await loadVisualSettings();}catch(_){$('visual-settings-status').textContent='Для прямой Wikimedia нужен корректный публичный email/HTTPS-адрес и согласие на отправку контакта.';}};
async function refreshMemory(){
  try{const response=await fetch('/api/memory?'+new URLSearchParams({conversation_id:conversation}));if(!response.ok)return;const data=await response.json();
    currentTopic=data.topic?.id||null;$('topic-label').textContent=data.topic?'Тема: '+data.topic.label:'Новая тема';$('topic-name').value=data.topic?.label||'';
    $('saved-facts').replaceChildren();
    for(const fact of data.facts||[]){const row=document.createElement('p'),label=document.createElement('span');label.textContent=fact.content+' · '+fact.scope;row.append(label);
      const edit=document.createElement('button');edit.type='button';edit.textContent='Исправить';edit.onclick=async()=>{const content=window.prompt('Исправленный факт',fact.content);if(content?.trim())await changeMemory('revise_fact',String(fact.id),content);};row.append(edit);
      const remove=document.createElement('button');remove.type='button';remove.textContent='Удалить';remove.onclick=()=>changeMemory('delete_fact',String(fact.id));row.append(remove);$('saved-facts').append(row);}
    $('memory-sources').replaceChildren();
    if(data.context){const metadata=JSON.parse(data.context.metadata);$('context-statistics').textContent=JSON.stringify({...metadata,provider_session:data.context.session_id,provider_mode:data.context.mode,provider_usage:data.context.usage||'недоступно',auxiliary_model_tokens:data.auxiliary_model_tokens},null,2);
      for(const id of metadata.source_message_ids||[]){if(!Number.isInteger(id)||id<=0)continue;const link=document.createElement('a');link.href='/api/memory/source/'+id;link.textContent='Исходное сообщение '+id+' ';link.target='_blank';link.rel='noopener';$('memory-sources').append(link);}}
  }catch(_){}
}
async function changeMemory(action,id,content=''){
  const response=await fetch('/api/memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,id,content})});
  if(!response.ok){$('topic-label').textContent='Изменение памяти не выполнено: проверь владельца и PIN профиля.';return;}
  if(action==='forget_conversation'){$('new-conversation').onclick();}else await refreshMemory();
}
$('memory-refresh').onclick=refreshMemory;
$('rename-topic').onclick=()=>{if(currentTopic&&$('topic-name').value.trim())changeMemory('rename_topic',currentTopic,$('topic-name').value.trim());};
$('forget-conversation').onclick=()=>{if(window.confirm('Удалить сообщения и производные данные этого разговора из рабочей базы GoBot?'))changeMemory('forget_conversation',conversation);};
window.addEventListener('storage', event=>{if(event.key==='gobot.conversation'){stop();recording?.cancel();recording=null;liveSocket?.close();$('answer').textContent='';$('history').replaceChildren();conversation=localStorage.getItem('gobot.conversation')||uuid();window.GoBotHooks?.onScopeChanged?.();}});
window.addEventListener('pagehide', () => { stop(); recording?.cancel();liveSocket?.close(); });
window.GoBotClient={prepareFeedback,feedback,trace:()=>requestTrace,send,stop,unlockAudio,startRecording,endRecording,explain,
  cancelRecording(){recording?.cancel();recording=null;liveSocket?.close();transcriptPending=false;stop();},
  isRecording:()=>!!recording||micPending,
  audioSnapshot(){let level=0;if(outputAnalyser){const data=new Uint8Array(outputAnalyser.fftSize);outputAnalyser.getByteTimeDomainData(data);level=Math.sqrt(data.reduce((sum,value)=>sum+((value-128)/128)**2,0)/data.length);}return {level,playing:sources.size>0&&(!audio.state||audio.state==='running'),state:audio?.state||'closed'};},
  getSettings:()=>({model:$('model').value,tts:$('tts').value,voice:$('voice').value||'marin',stt:$('stt').value,speak:$('speak').checked,paid:$('paid').checked,paid_stt:$('paid-stt').checked,quota:$('quota').checked,remember:$('remember').checked,volume:$('volume').value}),
  saveSettings(){localStorage.setItem('gobot.voice-settings',JSON.stringify(this.getSettings()));},
  restoreSettings(){try{const value=JSON.parse(localStorage.getItem('gobot.voice-settings')||'{}');for(const key of ['model','tts','stt','volume'])if(value[key]!=null)$(key).value=value[key];for(const key of ['speak','paid','quota','remember'])if(typeof value[key]==='boolean')$(key).checked=value[key];if(typeof value.paid_stt==='boolean')$('paid-stt').checked=value.paid_stt;if(value.voice&&$('voice').options.length)$('voice').value=value.voice;}catch(_){}}
};
window.GoBotClient.restoreSettings();
for(const key of ['model','tts','voice','stt','speak','paid','paid-stt','quota','volume','remember'])$(key).addEventListener?.('change',()=>window.GoBotClient.saveSettings());
refresh(); loadHistory();refreshMemory();loadVisualSettings();
