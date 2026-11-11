/* One owner panel over existing Brain, profiles, native voice and visual services. */
(() => {
 'use strict';const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const labels={realtime:'Realtime голос',ptt_followup_stop:'PTT, продолжение и Stop',experts:'CLI-эксперты',visuals:'Двухстадийный визуал',image_api:'OpenAI Image API',weather:'Погода',clock_timers_calendar:'Часы, дата и таймеры',family_preferences:'Семейные голоса и характеры',speaker_identity:'Локальное определение говорящего',private_memory_native:'Личная память в native Realtime',spacex_schedule:'Расписание SpaceX',esp32:'Физическая ESP32'};
 const presets=[['quiet_ptt','Тихий PTT · мягче только локальный фильтр'],['baseline','A · исходные параметры Mini'],['browser_ns_off','B · только browser noise suppression OFF'],['browser_ec_off','Только browser echo cancellation OFF'],['browser_agc_on','Только browser auto gain ON'],['browser_agc_off','Только browser auto gain OFF'],['server_noise_off','C · только server noise reduction OFF'],['server_far_field','Только server far_field'],['server_strength_half','Только server noise strength 0.5'],['vad_sensitive','D · только followup VAD 0.30']];
 class OwnerPanel{
  constructor(){this.fields={};this.log=[];this.answer='';this.input='';this.lastLevel=0;}
  async mount(){
   const r=await fetch('/api/realtime/owner-test',{cache:'no-store'});if(!r.ok)return;const state=await r.json();if(!state.authorized)return;
   this.root=el('details');this.root.id='owner-full-test';this.root.append(el('summary','GoBot Owner Full Test'));
   this.info=el('p');this.root.append(this.info);
   const label=el('label','Разговорная модель B');this.model=el('select');this.model.id='realtime-model';
   for(const value of ['gpt-realtime-2.1-mini','gpt-realtime-2.1'])this.model.append(Object.assign(el('option',value),{value}));label.append(this.model);this.root.append(label);
   this.root.append(el('p','Полная модель меняет собеседника Realtime. CLI-эксперт выполняет отдельную задачу и возвращает результат тому же собеседнику. Смена модели закрывает сессию; новый запуск — кнопкой GoBot.'));
   const audioLabel=el('label','Диагностика аудио · один параметр за раз');this.audio=el('select');this.audio.id='realtime-audio-preset';for(const [value,text] of presets)this.audio.append(Object.assign(el('option',text),{value}));audioLabel.append(this.audio);this.root.append(audioLabel);
   const budgets=el('details');budgets.append(el('summary','Бюджет и разрешённые модули'));
   for(const [key,text,min,max,step] of [['api_estimate_usd_per_day','Порог оценочных API-расходов в сутки, USD',1,500,.5],['realtime_responses_per_day','Realtime responses в сутки',10,10000,1],['expert_jobs_per_day','CLI-задачи в сутки',1,100,1],['image_attempts_per_day','Генерации изображений в сутки',1,100,1],['live_minutes_per_day','Live: минут открытой сессии в сутки',1,1440,1],['live_session_seconds','Live: максимум секунд одной сессии',30,3600,1],['live_backend_requests_per_day','C: запросов gpt-6-luna в сутки',1,10000,1]]){
    if(state.policy[key]===undefined)continue;const l=el('label',text),n=el('input');Object.assign(n,{type:'number',min,max,step,value:state.policy[key]});this.fields[key]=n;l.append(n);budgets.append(l);
   }
   for(const [key,text] of [['enabled','Owner Full Test включён'],['live_enabled','C: разрешить GPT-Live 1 ($0.05/мин; API 1.1 не подтверждён)'],['live_backend_enabled','C: быстрый backend gpt-6-luna · 2048 input / 512 output, без инструментов'],['experts_enabled','Разрешить экспертов с подтверждением задачи'],['images_enabled','Image API после неудачи Wikimedia'],['device_settings_enabled','Разрешённые серверные настройки устройства']]){if(state.policy[key]===undefined)continue;const l=el('label',text),n=el('input');n.type='checkbox';n.checked=state.policy[key];this.fields[key]=n;l.append(n);budgets.append(l);}
   const save=el('button','Сохранить бюджет и разрешения');save.type='button';save.onclick=()=>this.save(true);budgets.append(save);this.root.append(budgets);
   this.root.append(el('p','Порог расходов — серверная оценка с резервом, не абсолютный предел счёта OpenAI: usage приходит с задержкой. Неизвестные исходы сохраняют резерв. Транскрипция оплачивается отдельно; CLI расходует подписочную квоту. Открытие панели само не запускает платные операции.'));
   this.readiness=el('ul');this.root.append(this.readiness);
   const diag=el('details');diag.append(el('summary','Сигнал, отправка и понимание речи'));this.level=el('p','Микрофон закрыт');this.transcript=el('p');this.spoken=el('p');this.trace=el('pre');diag.append(this.level,this.transcript,this.spoken,this.trace);this.root.append(diag);
   const refresh=el('button','Обновить готовность и расход');refresh.type='button';refresh.onclick=()=>this.refresh();this.root.append(refresh);
   (document.querySelector('.device-controls')||document.querySelector('main')).after(this.root);
   this.model.value=state.policy.realtime_model;this.audio.value=state.policy.audio_preset;this.model.onchange=()=>this.save(false);this.audio.onchange=()=>this.save(false);this.apply(state);
  }
  apply(state){
   this.state=state;this.info.textContent=(state.enabled?'Owner Full Test включён. ':'Owner Full Test выключен. ')+'Оценка за сегодня с резервами: $'+state.estimated_usd_including_pending_reserves+' · вызовы '+JSON.stringify(state.attempts_today);
   this.readiness.replaceChildren();for(const [name,value] of Object.entries(state.readiness||{}))this.readiness.append(el('li',(labels[name]||name)+': '+(value.configured?'настроено':value.implemented?'нужна настройка/приёмка':'пока не готово')+' · '+value.acceptance));
   if(state.skill_catalogue){const s=state.skill_catalogue;this.readiness.append(el('li','Каталог сценариев: '+s.scenarios+' · локальные маршруты '+(s.readiness.local_path||0)+' · с условиями '+(s.readiness.conditional_path||0)+' · требуют интеграции/прав '+(s.readiness.not_connected_or_restricted||0)+'. Это не заявление о 400 готовых сервисах.'));}
   const consent=document.getElementById('realtime-expert-consent');if(consent&&state.enabled){consent.checked=state.policy.experts_enabled;consent.disabled=true;}
   if(state.enabled){const c=document.getElementById('realtime-consent');if(c)c.checked=true;}
  }
  async refresh(){try{const r=await fetch('/api/realtime/owner-test',{cache:'no-store'});if(r.ok)this.apply(await r.json());}catch(_){this.info.textContent='Не удалось обновить статус; платный повтор не запускался.';}}
  async save(all){
   const patch={realtime_model:this.model.value,audio_preset:this.audio.value};if(all)for(const [key,n] of Object.entries(this.fields))patch[key]=n.type==='checkbox'?n.checked:Number(n.value);
   try{if(window.GoBotRealtime?.id)await window.GoBotRealtime.close('Настройки B изменены. Включите GoBot для новой сессии.','settings_changed');if(all&&patch.enabled===false)await window.GoBotLive?.close('Owner Full Test выключен');const r=await fetch('/api/realtime/owner-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});if(!r.ok)throw Error();await this.refresh();await window.GoBotExpertUI?.refresh();}catch(_){this.info.textContent='Настройки не применены. Платный запуск не выполнялся.';}
  }
  diagnostic(data){
   if(!this.trace)return;
   if(data.stage==='closed'||data.stage==='ptt_capture_started'){this.answer='';this.input='';this.transcript.textContent='';this.spoken.textContent='';}
   if(data.stage==='ptt_sent')this.released=performance.now();
   if(data.stage==='first_client_audio'&&this.released)data={...data,release_to_audio_signal_ms:Math.round(performance.now()-this.released)};
   if(data.stage==='level'){if(performance.now()-this.lastLevel<150)return;this.lastLevel=performance.now();this.level.textContent='RMS '+data.rms.toFixed(5)+' · активность '+Math.round(data.speech_ms)+' мс';return;}
   if(data.stage==='gpt_transcribe'){this.input=data.text;this.transcript.textContent='GPT Transcribe: '+this.input;return;}
   if(data.stage==='live_input_delta'){this.input=(this.input+data.text).slice(-600);this.transcript.textContent='Нативный транскрипт Live: '+this.input;return;}
   if(data.stage==='answer_delta'){this.answer=(this.answer+data.text).slice(0,600);this.spoken.textContent='Начало фактического ответа Realtime: '+this.answer;return;}
   if(data.stage==='capture_settings'){
    const keys=['echoCancellation','noiseSuppression','autoGainControl','sampleRate','channelCount','latency'];const pick=o=>Object.fromEntries(keys.filter(k=>k in o).map(k=>[k,o[k]]));data={stage:data.stage,requested:pick(data.requested),effective:pick(data.effective),supported:pick(data.supported)};
   }
   this.log.push(data);this.log=this.log.slice(-10);this.trace.textContent=JSON.stringify(this.log,null,2);
  }
 }
 const panel=window.GoBotOwnerTest=new OwnerPanel();window.addEventListener('DOMContentLoaded',()=>panel.mount().catch(()=>{}));
})();
