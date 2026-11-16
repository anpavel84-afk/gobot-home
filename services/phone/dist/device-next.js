/* Additive owner preview. No provider session on page load or deterministic route. */
(() => {
  'use strict';const $=id=>document.getElementById(id);
  const state={conversation:null,ready:false,epoch:0,muted:false,recording:false,last:null,story:null,library:[],providerCalls:0};
  const status=text=>$('next-status').textContent=text;
  async function api(path,body={},signal,binary=false){
    const response=await fetch('/api/next/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
    if(!response.ok){let data;try{data=await response.json();}catch(_){}throw Error(data?.detail||'Функция временно недоступна. Код '+response.status);}
    return binary?response.arrayBuffer():response.json();
  }
  const guarded=fn=>(...args)=>Promise.resolve(fn(...args)).catch(error=>{if(error.name!=='AbortError'){if(manager)manager.state=navigator.onLine?'idle':'offline';status(error.message);}});
  let manager,renderer,renderProfile,native,answerAbort;
  const player=new window.GoBotStoryPlayer({
    command:(job,action)=>api('stories/'+job.id+'/command',{action}),
    ack:(job,ack)=>api('stories/'+job.id+'/ack',{ack}),
    onState:value=>{if(manager)manager.state=value==='playing'?'speaking':'idle';$('story-position').textContent='Проигрыватель: '+value;},
    onSegment:item=>$('story-segment').textContent=item.text,
    fetchAudio:async(job,item,signal)=>{
      try{return await api('stories/'+job.id+'/audio/'+item.id,{},signal,true);}
      catch(error){
        if(job.fixture||!$('next-tts-consent').checked)throw error;
        return api('speech',{conversation_id:state.conversation,story_id:job.id,segment_id:Number(item.id),paid_consent:true},signal,true);
      }
    }
  });
  window.GoBotClient={getSettings:()=>({volume:.8,voice:'marin',remember:false,speak:true}),conversationId:()=>state.conversation,
    cancelRecording:()=>window.GoBotCapture.active?.cancel()};
  window.GoBotHooks={clientKind:'device',onNativeClosed:({message})=>status(message||'Домашние функции доступны.')};
  function applyNative(item){
    const data=item.data||{};
    if(item.type==='turn_started'){manager.newTurn(item.turn_id);$('next-answer').textContent='';}
    if(item.type==='text_delta')$('next-answer').textContent+=data.text;
    if(item.type==='visual_response')manager.frame(data.presentation,item.turn_id);
    if(item.type==='turn_complete')status('Ответ закончен. Включаю микрофон…');
  }
  native=new window.GoBotNativeVoice({emit:applyNative,automaticDialogue:true});
  async function timers(){
    if(!state.ready)return;
    const data=await api('timers');const active=new Set(data.timers.map(t=>t.id));
    for(const id of manager.timers.keys())if(!active.has(id))manager.timers.delete(id);
    $('next-timers').replaceChildren();
    for(const timer of data.timers){
      const frame={id:'timer-'+timer.id,type:'timer_widget',title:'Таймер',metadata:{timer_id:timer.id,deadline:timer.deadline,state:timer.deadline<=Date.now()/1000?'expired':'running'}};
      const old=manager.timers.get(timer.id);if(old?.dismissed)frame.dismissed=true;manager.timers.set(timer.id,frame);
      const button=document.createElement('button');button.dataset.deadline=timer.deadline;button.dataset.timerId=timer.id;
      button.onclick=()=>{frame.dismissed=true;status('Сигнал таймера отмечен.');};$('next-timers').append(button);
    }
  }
  async function submit(text,truncated=false){
    if(!state.ready||!text.trim())return;
    const epoch=++state.epoch;state.inputAbort?.abort();
    await window.GoBotCapture.active?.cancel();
    if(native.ready){await native.sendText(text);return;} // Never add another STT path to an active B.
    if(state.story&&['playing','loading'].includes(player.state))await player.pause();
    answerAbort?.abort();answerAbort=new AbortController();status('Проверяю задачу…');manager.state='thinking';
    const {operation_id}=await api('operation',{conversation_id:state.conversation},answerAbort.signal);
    const result=await api('dispatch',{input:{conversation_id:state.conversation,operation_id,text,mode:$('next-mode').value,truncated}},answerAbort.signal);
    if(epoch!==state.epoch)return;
    state.last=result;manager.newTurn(result.turn_id);manager.state='idle';
    if(result.answer.display_data.frame)manager.frame(result.answer.display_data.frame,result.turn_id);
    manager.finish(result.turn_id);
    if(Number.isFinite(result.answer.display_data.volume)){await player.unlock();player.gain.gain.value=result.answer.display_data.volume;if(native.output)native.output.volume=result.answer.display_data.volume;}
    $('next-answer').textContent=result.answer.speech_text;$('next-source').textContent=result.answer.source;
    $('next-diagnostics').textContent=JSON.stringify({route:result.route_type,reason:result.reason,approved:result.approved,
      replay:result.replay,results:result.results.map(r=>({status:r.status,action_id:r.action_id})),timings:result.timings_ms,runtime:state.runtime},null,2);
    $('next-handover').hidden=!result.handover||!state.b?.ready;$('story-generate').hidden=result.route_type!=='START_STORYTELLER';
    if(result.answer.display_data.media_command){
      const command=result.answer.display_data.media_command;
      if(command==='stop')await player.stop();else if(command==='pause')await player.pause();else if(['resume','repeat'].includes(command))void guarded(()=>command==='repeat'?player.play(state.story,player.index,0):player.resume())();
    }
    await timers();status(result.route_type==='CLARIFY_SLOT'?'Жду уточнение.':'Готов к следующему вопросу.');
    if($('next-tts-consent').checked&&result.answer.speech_text&&result.route_type!=='MEDIA_CONTROL'){
      const raw=await api('speech',{conversation_id:state.conversation,operation_id,paid_consent:true},answerAbort.signal,true);
      if(epoch===state.epoch&&!state.muted)await player.playOne(raw);
    }
  }
  async function stop(){
    state.epoch++;answerAbort?.abort();state.inputAbort?.abort();window.GoBotCapture.active?.cancel();state.recording=false;clearTimeout(state.recordingLimit);
    if(native.ready||native.pending)await native.close('Остановлено','user_stop');
    await player.stop();if(manager)manager.state='idle';status('Остановлено. Таймеры продолжают работать.');$('device-mic').textContent='Микрофон закрыт';
  }
  async function listen(){
    if(state.muted)throw Error('Микрофон заглушён. Сначала включите его.');
    if(state.recording){
      clearTimeout(state.recordingLimit);state.recording=false;
      if(native.ready&&native.recording)await native.pttEnd();else window.GoBotCapture.active?.stop();return;
    }
    if($('next-mode').value==='c')throw Error('C остаётся отдельным режимом: переход по тексту не принят, старый расход неизвестен.');
    if($('next-mode').value==='b'||native.ready){
      await player.pause();await native.beginDialogue();return;
    }
    if(!$('next-stt-consent').checked)throw Error('Для распознавания отметьте согласие на STT API. Текстовый ввод работает без него.');
    await player.pause();await player.unlock();state.recording=true;manager.state='listening';let began=performance.now();
    const captureEpoch=++state.epoch;state.inputAbort=new AbortController();
    $('device-mic').textContent='Микрофон записывает · коснитесь, чтобы закончить';status('Слушаю. Максимум 15 секунд.');
    await window.GoBotCapture.start({context:player.context,maxMs:15000,minSpeechMs:0,minDurationMs:0,
      vad:{windowMs:5000,silenceMs:900,minSpeechMs:180},
      onSilence:()=>{state.recording=false;manager.state='idle';status('Речь не обнаружена. Микрофон закрыт.');},
      onError:error=>{state.recording=false;status(error.message);},
      onStop:guarded(async blob=>{
        if(captureEpoch!==state.epoch||state.muted)return;
        state.recording=false;$('device-mic').textContent='Микрофон закрыт';
        if(performance.now()-began>=14800){status('Запись достигла предела. Уточните или повторите вопрос; действие не выполнялось.');return;}
        const response=await fetch('/api/next/transcribe?paid_consent=true',{method:'POST',headers:{'Content-Type':blob.type},body:blob,signal:state.inputAbort.signal});
        const data=await response.json();if(!response.ok)throw Error(data.detail||'Распознавание недоступно.');
        if(captureEpoch!==state.epoch||state.muted)return;
        $('next-text').value=data.text||'';if(data.text?.trim())await submit(data.text);else status('Не удалось разобрать фразу.');
      })});began=performance.now();
  }
  async function loadStory(fixture){
    await native.close('Переход к рассказчику','settings_changed');await player.stop();
    state.story=await api('stories',{conversation_id:state.conversation,fixture,text:fixture?'':$('story-text').value,title:fixture?'':'Ваш текст'});
    state.story.client_id=state.clientId;$('story-title').textContent=state.story.title;$('story-segment').textContent=state.story.segments[0].text;
    status(fixture?'Открыт тестовый рассказ. Звук — синтетические сигналы.':'Текст открыт. Для озвучивания нужен ручной TTS-допуск.');
  }
  async function init(){
    const response=await fetch('/api/next/status');const config=await response.json();if(!response.ok)throw Error(config.detail||'Preview доступен только устройству владельца.');
    state.runtime=config.runtime_sha;state.clientId=config.client_id;state.b=config.b;renderProfile=config.profile;
    if(!config.speech.manual_paid_authorized){for(const id of ['next-stt-consent','next-tts-consent','realtime-consent'])$(id).disabled=true;}
    manager=new window.GoBotDeviceRenderer.SceneManager(renderProfile);renderer=new window.GoBotDeviceRenderer.DeviceRenderer($('device-screen'),renderProfile);
    window.goBotDevice={profile:renderProfile,status,manager};
    state.conversation=(await api('open')).conversation_id;state.ready=true;$('fixture-badge').hidden=!config.fixture_mode;
    await timers();status('Готов к следующему вопросу. Текстовые домашние команды не открывают B/C.');
    function draw(t){
      const playback=native.ready?native.snapshot():player.snapshot();if(native.ready)manager.state=native.listening||native.recording?'listening':playback.playing?'speaking':native.thinking?'thinking':'idle';manager.tick(playback.playing);renderer.draw(manager,playback.level,t/1000);
      for(const el of $('next-timers').children){const remaining=Math.max(0,Math.ceil(Number(el.dataset.deadline)-Date.now()/1000));el.textContent=remaining?'Таймер · '+Math.floor(remaining/60)+':'+String(remaining%60).padStart(2,'0'):'Время вышло · услышал';}
      $('story-position').textContent='Проигрыватель: '+player.state+' · фрагмент '+(player.index+1)+' · '+player.snapshot().position.toFixed(1)+' с';
      requestAnimationFrame(draw);
    }requestAnimationFrame(draw);
    state.poll=setInterval(()=>guarded(timers)(),5000);
    window.dispatchEvent(new CustomEvent('gobot-next-ready'));
  }
  $('next-form').onsubmit=e=>{e.preventDefault();void guarded(()=>submit($('next-text').value))();};
  $('next-listen').onclick=guarded(listen);$('device-screen').onclick=guarded(()=>player.state==='playing'?player.pause():listen());
  $('device-screen').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('device-screen').click();}};
  $('next-stop').onclick=guarded(stop);$('next-mute').onclick=guarded(async()=>{state.muted=!state.muted;await stop();$('next-mute').textContent=state.muted?'Включить микрофон':'Заглушить микрофон';});
  $('next-mode').onchange=guarded(async()=>{state.epoch++;state.inputAbort?.abort();window.GoBotCapture.active?.cancel();state.recording=false;await native.close('Режим изменён','settings_changed');});
  $('next-handover').onclick=guarded(async()=>{state.epoch++;state.inputAbort?.abort();window.GoBotCapture.active?.cancel();state.recording=false;await player.pause();if(!state.last?.handover)throw Error('Нет актуального вопроса для B.');await native.sendText(state.last.handover.query);});
  $('story-fixture').onclick=guarded(()=>loadStory(true));$('story-custom').onclick=guarded(()=>loadStory(false));
  $('story-play').onclick=guarded(async()=>{if(!state.story)throw Error('Сначала выберите рассказ.');await native.close('Переход к рассказчику','settings_changed');return player.job?.id===state.story.id?player.resume():player.play(state.story);});
  $('story-pause').onclick=guarded(()=>player.pause());$('story-stop').onclick=guarded(()=>player.stop());
  $('story-generate').onclick=guarded(async()=>{
    state.story=await api('stories/generate',{conversation_id:state.conversation,operation_id:state.last.operation_id,paid_consent:true});
    state.story.client_id=state.clientId;$('story-title').textContent=state.story.title;$('story-segment').textContent=state.story.segments[0].text;});
  $('library-load').onclick=guarded(async()=>{const inventory=await api('library');state.library=inventory.entries;$('library-status').textContent=inventory.ready+' из '+inventory.total+' клипов проверены. Runtime-синтез не запускался.';
    $('library-select').replaceChildren();for(const clip of inventory.entries.filter(c=>c.status==='ready')){const option=document.createElement('option');option.value=clip.id;option.textContent=clip.text;$('library-select').append(option);}});
  $('library-play').onclick=guarded(async()=>{const clip=state.library.find(c=>c.id===$('library-select').value);if(!clip)throw Error('Нет готового клипа.');await native.close('Прослушивание клипа','settings_changed');const response=await fetch(clip.url);if(!response.ok)throw Error('Клип недоступен.');await player.playOne(await response.arrayBuffer());});
  for(const event of ['pagehide','offline'])window.addEventListener(event,()=>{clearInterval(state.poll);void guarded(stop)();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){window.GoBotCapture.active?.cancel();state.recording=false;void guarded(()=>player.pause())();void native.close('Вкладка скрыта','page_hidden');}});
  window.GoBotNext={state,player,submit,stop,get manager(){return manager;},get renderer(){return renderer;}};
  void guarded(init)();
})();
