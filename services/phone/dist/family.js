'use strict';
const $=id=>document.getElementById(id);let capture=null,context=null;
async function api(action='',method='GET',body=null){
  const response=await fetch('/api/family/'+action,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||data.error||'Запрос не выполнен');return data;
}
function button(text,run){const b=document.createElement('button');b.type='button';b.className='text-button';b.textContent=text;b.onclick=async()=>{try{await run();await refresh();}catch(e){$('status').textContent=e.message;}};return b;}
async function refresh(){
  try{const data=await api();$('profiles').replaceChildren();const selected=$('sample-profile').value;
    for(const id of ['sample-profile','login-profile'])$(id).replaceChildren();
    for(const profile of data.profiles){
      for(const id of ['sample-profile','login-profile']){const option=document.createElement('option');option.value=profile.id;option.textContent=profile.name;$(id).append(option);}
      const card=document.createElement('div'),label=document.createElement('p');label.textContent=(profile.avatar||'')+' '+profile.name+' · '+(profile.age==='child'?'ребёнок':'взрослый')+' · '+profile.segments+' эталонов / '+Math.round(profile.seconds)+' с';card.append(label);
      card.append(button(profile.enabled?'Выключить распознавание':'Включить распознавание',()=>api(profile.id+'/enable','POST',{enabled:!profile.enabled})));
      card.append(button('Удалить голосовые шаблоны',async()=>{if(confirm('Удалить голосовые шаблоны '+profile.name+'? История останется.'))await api(profile.id+'/voice','DELETE');}));
      card.append(button('Удалить профиль и его историю',async()=>{if(confirm('Удалить профиль '+profile.name+', биометрию и персональную историю?'))await api(profile.id,'DELETE');}));
      $('profiles').append(card);
    }
    if([...$('sample-profile').options].some(o=>o.value===selected))$('sample-profile').value=selected;
    $('calibration').textContent=data.calibration?'Порог выведен из проверочных записей. Это similarity score, не вероятность. Точность на новых условиях не подтверждена.':'Распознавание unknown до калибровки. Нужны эталоны, новые проверочные фразы и неизвестный голос.';
  }catch(e){$('status').textContent=e.message;}
}
$('create').onsubmit=async e=>{e.preventDefault();try{
  await api('','POST',{name:$('name').value,avatar:$('avatar').value,age:$('age').value,pin:$('pin').value,consent:$('bio-consent').checked,parent_consent:$('parent-consent').checked});
  $('pin').value='';$('status').textContent='Профиль создан. Голосовые данные пока отсутствуют.';await refresh();
}catch(error){$('status').textContent=error.message;}};
$('record').onclick=async()=>{
  try{if(!$('sample-consent').checked)throw new Error('Сначала подтверди добровольное согласие на образец.');
    const ident=$('sample-profile').value||'00000000-0000-0000-0000-000000000000',kind=$('sample-kind').value;
    capture=await GoBotCapture.start({context,onStop:async blob=>{
      capture=null;$('record').disabled=false;$('record-stop').disabled=true;$('record-status').textContent='Формируем локальный шаблон…';
      try{const query=new URLSearchParams({kind,sample_consent:'true'});const response=await fetch('/api/family/'+ident+'/sample?'+query,{method:'POST',headers:{'Content-Type':blob.type},body:blob});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Ошибка шаблона');$('record-status').textContent='Шаблон сохранён локально. Исходное аудио не сохранено.';await refresh();}catch(e){$('record-status').textContent=e.message;}
    },onError:e=>{$('record-status').textContent=e.message;capture=null;}});
    $('record').disabled=true;$('record-stop').disabled=false;$('record-status').textContent='Слушаю. Запиши 10–20 секунд естественной речи.';
  }catch(e){$('record-status').textContent=e.message;}
};
$('record-stop').onclick=()=>capture?.stop();
$('calibrate').onclick=async()=>{try{await api('calibrate','POST');await refresh();}catch(e){$('calibration').textContent='Калибровка не выполнена: '+e.message;}};
$('delete-unknown').onclick=async()=>{if(confirm('Удалить шаблоны неизвестных голосов и сбросить калибровку?')){await api('unknown','DELETE');await refresh();}};
function freshConversation(){localStorage.removeItem('gobot.conversation');}
$('login').onclick=async()=>{try{const data=await api('login','POST',{profile_id:$('login-profile').value,pin:$('login-pin').value});$('login-pin').value='';freshConversation();$('status').textContent='Подтверждён профиль '+data.name+'. Вернись к GoBot.';}catch(e){$('status').textContent=e.message;}};
$('logout').onclick=async()=>{await api('logout','POST');freshConversation();$('status').textContent='Гостевой контекст. Персональная память недоступна.';};
$('save-fact').onclick=async()=>{try{await api('fact','POST',{scope:$('fact-scope').value,text:$('fact').value,consent:$('fact-consent').checked});$('fact').value='';$('fact-consent').checked=false;$('status').textContent='Сведение сохранено в выбранной памяти.';}catch(e){$('status').textContent=e.message;}};
window.addEventListener('pagehide',()=>capture?.cancel());refresh();
