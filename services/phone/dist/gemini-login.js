'use strict';
const $=id=>document.getElementById(id);
let timer=null;
const labels={idle:'Вход ещё не начат.',starting:'Запускается официальный OAuth…',waiting_for_code:'Открой ссылку Google, выполни вход и вставь выданный код ниже.',validating:'Google проверяет код…',authenticated:'Официальный вход выполнен. Можно вернуться к GoBot.',login_failed:'Вход не завершён. Можно начать заново.',cancelled:'Вход отменён.'};
async function status(){
  try{const r=await fetch('/api/settings/gemini');const d=await r.json();$('status').textContent=labels[d.state]||d.state;
    $('authorize').hidden=!d.authorization_url;if(d.authorization_url)$('authorize').href=d.authorization_url;
    $('code-form').hidden=d.state!=='waiting_for_code';$('login').disabled=['starting','waiting_for_code','validating'].includes(d.state);
    if(!['starting','waiting_for_code','validating'].includes(d.state)){clearInterval(timer);timer=null;}
  }catch(_){$('status').textContent='Сервер недоступен.';}
}
$('login').onclick=async()=>{await fetch('/api/settings/gemini/start',{method:'POST'});if(!timer)timer=setInterval(status,1000);await status();};
$('code-form').onsubmit=async e=>{e.preventDefault();const value=$('code').value;$('code').value='';const r=await fetch('/api/settings/gemini/code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:value})});if(!r.ok)$('status').textContent='Код не принят. Попробуй начать вход заново.';else await status();};
$('cancel').onclick=async()=>{await fetch('/api/settings/gemini/cancel',{method:'POST'});await status();};
status();
