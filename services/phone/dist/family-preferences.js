/* Existing family cards, authorized preferences, cached previews only. */
window.GoBotFamilyPreferences=(profile,api)=>{
  const box=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Как GoBot разговаривает со мной · голос и характер';box.append(summary);
  const status=document.createElement('p');status.className='hint';box.append(status);let revision=0,fields={},loaded=false;
  function select(key,label,choices,value){const row=document.createElement('label');row.textContent=label;const input=document.createElement('select');for(const [v,t] of choices){const o=document.createElement('option');o.value=v;o.textContent=t;input.append(o);}input.value=value??'';row.append(input);box.append(row);fields[key]=input;}
  function text(key,label,value,max,multiline=false){const row=document.createElement('label');row.textContent=label;const input=document.createElement(multiline?'textarea':'input');input.maxLength=max;input.value=value||'';if(multiline)input.rows=4;row.append(input);box.append(row);fields[key]=input;}
  function action(label,run){const b=document.createElement('button');b.type='button';b.className='text-button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await run();}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};box.append(b);}
  box.addEventListener('toggle',async()=>{
    if(!box.open||loaded)return;
    try{
      const data=await api(profile.id+'/preferences','POST',{operation:'read'}),p=data.preferences;revision=data.revision;loaded=true;
      status.textContent='PIN-профиль подтверждён для настроек. Это не подтверждение говорящего. Голос применяется в новой сессии; приватная память native-кандидата закрыта.';
      select('formality','Обращение',[['ты','На ты'],['вы','На вы']],p.formality);
      text('preferred_name','Предпочитаемое имя',p.preferred_name,60);text('address','Форма обращения, например сеньор',p.address,60);
      select('repeat_name','Обращение по имени',[['false','Иногда, естественно'],['true','Можно при каждом ответе']],String(p.repeat_name));
      select('language','Язык',[['ru','Русский'],['pt','Português'],['en','English']],p.language);
      select('personality','Характер',[['friendly','Дружелюбный'],['neutral','Нейтральный'],['business','Деловой'],['humorous','С юмором'],['calm','Спокойный'],['energetic','Энергичный'],['custom','Пользовательский']],p.personality);
      select('answer_length','Длина ответа',[['short','Кратко'],['balanced','Сбалансированно'],['detailed','Подробно']],p.answer_length);
      select('explanation_depth','Глубина объяснения',[['simple','Просто'],['ordinary','Обычный уровень'],['expert','Экспертный стиль, без запуска CLI']],p.explanation_depth);
      select('language_complexity','Сложность языка',[['simple','Простой'],['normal','Обычный'],['professional','Профессиональный']],p.language_complexity);
      text('custom_prompt','Как GoBot должен разговаривать со мной',p.custom_prompt,1500,true);
      const catalog=await api('voices');
      select('voice','Голос GoBot для меня',[['','Семейный голос по умолчанию'],...catalog.voices.map(v=>[v.id,v.label+' · встроенный'])],p.voice);
      action('Прослушать готовый пример',async()=>{
        const voice=catalog.voices.find(v=>v.id===fields.voice.value);
        if(!voice?.preview_url){status.textContent='Готового клипа этого голоса нет. API-синтез не запускался; для него нужно отдельное согласие.';return;}
        await new Audio(voice.preview_url).play();status.textContent='Готовый ранее разрешённый клип. Новый синтез не выполняется.';
      });
      action('Сохранить характер и голос',async()=>{
        const preferences=Object.fromEntries(Object.entries(fields).map(([k,n])=>[k,k==='repeat_name'?n.value==='true':k==='voice'?(n.value||null):n.value]));
        const result=await api(profile.id+'/preferences','POST',{operation:'update',expected_revision:revision,preferences});revision=result.revision;
        status.textContent='Сохранено. Версия '+revision+'. Активная старая сессия закрыта; следующие настройки применятся после нового Start.';
      });
      action('Вернуть настройки по умолчанию',async()=>{
        const result=await api(profile.id+'/preferences','POST',{operation:'reset',expected_revision:revision});revision=result.revision;
        for(const [k,n] of Object.entries(fields))n.value=result.preferences[k]===null?'':String(result.preferences[k]);status.textContent='Настройки сброшены. Голос наследуется из семейного default.';
      });
      action('Проверить мой профиль без модельного вызова',async()=>{
        const result=await api(profile.id+'/preferences','POST',{operation:'inspect'});
        status.textContent='Выбран вручную: '+profile.name+' · голос '+(result.preferences.voice||'семейный default')+' · характер '+result.preferences.personality+' · Speaker Identity: пока неизвестен. Приватная память native-кандидата закрыта. API/CLI не вызывались.';
      });
      if(profile.age==='child')status.textContent+=' Изменение детских настроек закрыто до настройки серверного родительского разрешения.';
    }catch(e){status.textContent='Сначала подтверди PIN этого профиля в разделе ниже. '+e.message;}
  });
  return box;
};
