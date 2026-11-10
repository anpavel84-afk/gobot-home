'use strict';
const field = document.getElementById('api-key'), status = document.getElementById('key-status'), save = document.getElementById('save-key');
fetch('/api/settings/openai', {cache:'no-store'}).then(r=>r.json()).then(s=>{
  status.textContent = s.configured ? 'Ключ уже сохранён. Здесь можно заменить его новым.' : 'Ключ пока не задан.';
}).catch(()=>{status.textContent='Не удалось проверить настройки.';});
document.getElementById('key-form').addEventListener('submit', async event => {
  event.preventDefault(); save.disabled=true;
  let key = field.value.trim();
  field.value='';
  try {
    const response = await fetch('/api/settings/openai', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
    key='';
    status.textContent=response.ok ? 'Ключ сохранён на компьютере. Платный запрос не выполнялся.' : 'Ключ не сохранён. Проверь формат и попробуй снова.';
  } catch(error) { status.textContent='Не удалось связаться с компьютером. Ключ не подтверждён как сохранённый.'; }
  finally {key='';save.disabled=false;}
});
