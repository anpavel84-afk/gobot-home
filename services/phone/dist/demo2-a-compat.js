/* Compatibility around immutable A assets. No provider/model/audio call on load. */
(() => {
  'use strict';
  const scoped=new Set(['gobot.voice-settings','gobot.cli-quota-consent','gobot.conversation']);
  try{
    const proto=Object.getPrototypeOf(localStorage),get=proto.getItem,set=proto.setItem,remove=proto.removeItem;
    const key=k=>scoped.has(String(k))?'gobot.demo2.a.'+k:String(k);
    proto.getItem=function(k){return get.call(this,this===localStorage?key(k):k);};
    proto.setItem=function(k,v){return set.call(this,this===localStorage?key(k):k,v);};
    proto.removeItem=function(k){return remove.call(this,this===localStorage?key(k):k);};
  }catch(_){} // Storage refusal never grants consent.
  window.addEventListener('DOMContentLoaded',async()=>{
    const client=window.GoBotClient;if(!client)return;
    const panel=document.createElement('details'),summary=document.createElement('summary'),status=document.createElement('p');
    summary.textContent='A · настройки и готовность';panel.append(summary,status);panel.className='legacy-readiness';panel.id='legacy-readiness';
    status.textContent='Проверяю готовность STT → CLI → TTS…';
    const anchor=document.querySelector('.device-controls')||document.querySelector('main');anchor?.after(panel);
    if(document.getElementById('device-screen')){
      for(const [id,text] of [['paid-stt','Разрешаю OpenAI STT'],['paid','Разрешаю OpenAI озвучивание'],['quota','Разрешаю CLI-квоту обычного диалога']]){
        const control=document.getElementById(id);if(!control)continue;const label=document.createElement('label');label.append(control,document.createTextNode(text));panel.append(label);
      }
    }
    const links=document.createElement('p'),back=document.createElement('a');back.href='/demo2';back.textContent='Выбор A / B';links.append(back);panel.append(links);
    try{
      const response=await fetch('/api/demo2/a/readiness',{cache:'no-store'});if(!response.ok)throw Error();const ready=await response.json();
      if(ready.manual_authorized&&ready.grant_revision&&localStorage.getItem('gobot.demo2.a.applied-grant')!==ready.grant_revision){
        let saved={};try{saved=JSON.parse(localStorage.getItem('gobot.voice-settings')||'{}');}catch(_){}
        const value={...saved,model:'auto',stt:'openai',tts:'openai',voice:saved.voice||'marin',speak:true,paid:true,paid_stt:true,quota:true};
        localStorage.setItem('gobot.voice-settings',JSON.stringify(value));localStorage.setItem('gobot.cli-quota-consent','true');client.restoreSettings();
        localStorage.setItem('gobot.demo2.a.applied-grant',ready.grant_revision);
      }
      status.textContent=ready.manual_authorized?(ready.cli_ready&&ready.openai_key_configured?'A разрешён для ручных проб: OpenAI STT → Antigravity Flash → прежний Speech Formatter → OpenAI голос. Нажмите «Включить GoBot».':'Разрешение A сохранено, но провайдер ещё не готов: '+(ready.cli_reason||'OpenAI key required')):'Для A нужны отдельные согласия STT, CLI и TTS в настройках ниже.';
      const device=window.goBotDevice;
      if(device&&typeof device.enable==='function'){
        const enable=device.enable.bind(device);
        device.enable=async()=>{
          status.textContent='Включаю A: проверяю разрешения и микрофон Safari…';panel.open=true;
          const watch=setTimeout(()=>{if(device.enabling)status.textContent='A ожидает готовность аудио или разрешение микрофона. Проверьте запрос Safari; B в другой вкладке должен быть выключен.';},8000);
          try{await enable();status.textContent=device.enabled?'A готов. Удерживайте круг, задайте вопрос и отпустите. Само включение не произносит ответ.':(document.getElementById('device-status')?.textContent||'A не включился; проверьте разрешения ниже.');}finally{clearTimeout(watch);}
        };
      }
      const hint=document.createElement('p');hint.textContent='Перед включением A выключите GoBot в другой вкладке B. Одновременно микрофон использует только один режим. Настройки и разговор A хранятся отдельно от B.';panel.append(hint);
    }catch(_){status.textContent='Готовность A проверить не удалось. Проверьте согласия STT/CLI/TTS; автоматический запуск не выполнялся.';}
  });
})();
