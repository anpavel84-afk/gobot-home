'use strict';
const $=id=>document.getElementById(id);let current=null,busy=false;
const messages={board_budget_inactive:'Срок разрешения на разговор B истёк. София остаётся включённой; платный разговор заблокирован.',realtime_policy_disabled:'Разговор пока не разрешён текущей политикой расходов.',owner_test_not_authorized:'Для этого источника нет действующего разрешения на расход.',voice_device_not_connected:'Колонка ещё не подключена к новому голосовому тракту.',mode_change_requires_idle:'Дождитесь окончания реплики или нажмите «Остановить ответ».',brain_or_gateway_unavailable:'Не удалось связаться с сервером. Повторная проверка выполняется автоматически.',narrator_budget_unavailable:'Для озвучивания ответа эксперта нет действующего допуска.',microphone_source_already_attached:'Этот микрофон уже используется разговором.'};
function human(code){return messages[code]||('Причина: '+String(code||'неизвестная ошибка').replaceAll('_',' '));}
function alertText(text){$('alert').textContent=text||'';$('alert').hidden=!text;}
function render(data){current=data;const dev=data.device||{},brain=data.brain||{},state=brain.status||{},session=(brain.sessions||[])[0],ready=!!session?.ready,allowed=!!session?.generation_allowed,muted=!!session?.muted;const phase=muted?'muted':dev.voice_phase||(dev.input_open?'listening':session?.state||'ready');let title,description;
 if(data.status==='unavailable'){title='Нет связи с сервером';description='София на колонке продолжает работать локально.';}
 else if(!dev.device_protocol_confirmed){title='Жду колонку';description='Новый разговорный тракт ещё не подтвердил подключение.';}
 else if(muted){title='Микрофон выключен';description='Включите микрофон, чтобы снова обратиться к Софии.';}
 else if(phase==='listening'){title='Слушаю';description='Говорите. Продолжение фразы не ограничено окном ожидания.';}
 else if(phase==='speaking'){title='Отвечаю';description='После полного окончания ответа можно продолжить без имени.';}
 else if(phase==='thinking'){title='Обдумываю ответ';description=session?.input_mode==='expert'?'Эксперт работает над вашей задачей. Готовые части ответа прозвучат по порядку.':'Ожидаю ответ на ваш вопрос.';}
 else if(!ready){title='Подключаю разговор';description='Готовность появится после подтверждения сервера.';}
 else{title='София на связи';description=allowed?'Скажите «София» и задайте вопрос.':'Пробуждение готово. Допуск к платному разговору пока закрыт.';}
 $('title').textContent=title;$('description').textContent=description;$('orb').className='orb '+phase;
 $('cloud').textContent=ready?'Конфигурация подтверждена':'Не подтверждено';$('admission').textContent=allowed?'Да':'Закрыт';$('voice').textContent=state.voice||dev.voice||'—';
 for(const id of ['fast','expert']){$(id).disabled=busy||!session;$(id).setAttribute('aria-pressed',String(session?.input_mode===id));}
 $('stop').disabled=busy||!session;$('mute').disabled=busy||!session;$('mute').textContent=muted?'Включить микрофон':'Выключить микрофон';$('mute').setAttribute('aria-pressed',String(muted));
 const err=dev.last_error||data.code;if(err)alertText(human(err));else if(ready&&!allowed)alertText('Текущий допуск к расходам не разрешает разговор. История расхода сохранена; автоматических платных повторов нет.');else if(!busy)alertText('');
 $('details').textContent=JSON.stringify({transport:state.transport,budget:state.budget,device:dev},null,2);$('updated').textContent='Обновлено '+new Date().toLocaleTimeString('ru-RU');
}
async function refresh(){try{const response=await fetch('/api/sophia/status',{cache:'no-store'});render(await response.json());}catch{render({status:'unavailable',code:'brain_or_gateway_unavailable'});}}
async function control(body){if(busy)return false;busy=true;try{const response=await fetch('/api/sophia/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){alertText(human(data.detail||data.code));return false;}await refresh();return true;}catch{alertText(human('brain_or_gateway_unavailable'));return false;}finally{busy=false;}}
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>control({action:'mode',mode:button.dataset.mode})));
$('stop').addEventListener('click',()=>control({action:'stop'}));$('mute').addEventListener('click',()=>control({action:'mute',muted:!current?.brain?.sessions?.[0]?.muted}));
$('source').addEventListener('change',async()=>{if($('source').value==='browser'){const sessions=current?.brain?.sessions||[];if(sessions.length&&!await control({action:'stop'})){$('source').value='spotpear';return;}location.assign('/');}});
refresh();setInterval(()=>{if(!document.hidden&&!busy)refresh();},2000);
