(() => {
  'use strict';
  const data = window.SOPHIA_ADMIN;
  const $ = (id) => document.getElementById(id);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const paths = {
    grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    spark:'m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z M20 2v4 M18 4h4',
    wave:'M3 10v4 M7 6v12 M12 3v18 M17 7v10 M21 10v4',
    home:'m3 10 9-7 9 7 M5 9v11h14V9 M9 20v-7h6v7',
    server:'M4 3h16v7H4z M4 14h16v7H4z M7 6.5h.01 M7 17.5h.01 M15 7h3 M15 18h3',
    speaker:'M7 2h10v20H7z M10 6h4 M12 11a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7',
    users:'M9 3a3 3 0 1 0 0 6 3 3 0 0 0 0-6 M2 21v-3a6 6 0 0 1 12 0v3 M16 4a3 3 0 0 1 0 6 M17 14a5 5 0 0 1 5 5v2',
    wallet:'M20 8V4H5a2 2 0 0 0 0 4h16v13H5a2 2 0 0 1-2-2V6 M21 12h-6v5h6 M17 14.5h.01',
    pulse:'M3 12h4l3-8 4 16 3-8h4',
    history:'M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2',
    weather:'M7 14a5 5 0 0 1 9-3 4 4 0 1 1 2 8H7a2.5 2.5 0 1 1 0-5 M6 3v2 M1 8h2 M2.5 3.5 1.5 2.5 M6 8a3 3 0 0 1 5 0',
    clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
    timer:'M12 7a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M9 2h6 M12 2v5 M18 5l2 2 M12 10v4l2 1',
    calculator:'M5 2h14v20H5z M8 6h8 M8 11h1 M15 11h1 M8 15h1 M15 15h1 M8 19h1 M15 19h1',
    globe:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M3 12h18 M12 3c-5 5-5 13 0 18 M12 3c5 5 5 13 0 18',
    image:'M3 3h18v18H3z M3 16l5-6 5 5 3-3 5 6 M16 7h.01',
    palette:'M12 3a9 9 0 0 0 0 18h1a2 2 0 0 0 1-4 1.5 1.5 0 0 1 0-3h3a4 4 0 0 0 4-4c0-4-4-7-9-7 M7 9h.01 M11 6h.01 M16 7h.01 M6 14h.01',
    music:'M9 17V5l11-2v12 M9 17a3 2.5 0 1 1-3-2.5 3 2.5 0 0 1 3 2.5 M20 15a3 2.5 0 1 1-3-2.5 3 2.5 0 0 1 3 2.5',
    bulb:'M9 18h6 M10 22h4 M8 15a6 6 0 1 1 8 0l-1 3H9z',
    bell:'M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 21h4 M12 2v2',
    calendar:'M3 5h18v16H3z M7 2v6 M17 2v6 M3 10h18 M7 14h2 M14 14h2 M7 18h2',
    list:'M4 5h2 M10 5h10 M4 12h2 M10 12h10 M4 19h2 M10 19h10',
    memory:'M8 3h8v4h4v10h-4v4H8v-4H4V7h4z M9 9h6v6H9z',
    language:'M3 4h12 M9 2v2 M5 4c0 7 7 11 7 11 M13 4c-1 5-4 9-10 12 M13 21l4-11 4 11 M15 17h4',
    message:'M3 3h18v14H9l-6 4z M7 7h10 M7 11h7',
    hand:'M9 11V4a2 2 0 0 1 4 0v7 M13 7a2 2 0 0 1 4 0v5 M17 9a2 2 0 0 1 4 0v6c0 4-3 7-7 7-3 0-5-2-7-4l-4-5a2 2 0 0 1 3-2l3 3',
    search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
    settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z',
    check:'m5 12 4 4L19 6', cross:'M6 6l12 12 M18 6 6 18',
    chevron:'m9 5 7 7-7 7', menu:'M4 6h16 M4 12h16 M4 18h16',
    info:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7h.01 M12 11v6',
    pin:'M19 9c0 5-7 12-7 12S5 14 5 9a7 7 0 1 1 14 0 M12 6a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
    lock:'M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0v4 M12 14v3',
    link:'M10 14l4-4 M8 16l-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0 M16 8l2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0',
    monitor:'M3 3h18v13H3z M9 16v5 M15 16v5 M6 21h12',
    mic:'M9 4a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0z M5 10v1a7 7 0 0 0 14 0v-1 M12 18v4 M8 22h8',
    shield:'m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6',
    moon:'M20 14A8 8 0 0 1 10 4a9 9 0 1 0 10 10',
    volume:'m11 3-6 5H2v8h3l6 5z M15 8a6 6 0 0 1 0 8 M18 4a12 12 0 0 1 0 16',
    file:'M6 2h8l5 5v15H6z M14 2v6h5 M9 12h7 M9 16h7',
    upload:'M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6',
    download:'M12 3v13 M7 11l5 5 5-5 M4 17v4h16v-4',
    minus:'M5 12h14',terminal:'M3 4h18v16H3z M7 8l3 4-3 4 M13 16h4'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.settings}"></path></svg>`;
  const storageKey = 'gobot:sophia-admin-design:v1';
  let storageHealthy = true;
  let saved = clone(data.defaults), history = [];
  const validValue = (key, val) => {
    const f = data.fields[key]; if (!f || f.type === 'fixed') return false;
    if (f.type === 'toggle') return typeof val === 'boolean';
    if (f.type === 'select') return f.options.some(o => o[0] === val && !o[2]);
    if (f.type === 'city') return val === 'configured' || data.cities.some(c => c.id === val);
    if (f.type === 'range') return Number.isFinite(Number(val)) && Number(val) >= f.min && Number(val) <= f.max;
    return typeof val === 'string' && val.length <= 80;
  };
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || 'null');
    if (stored?.version === 1) {
      for (const [k,v] of Object.entries(stored.settings || {})) if (validValue(k,v)) saved[k] = v;
      history = (Array.isArray(stored.history) ? stored.history : []).filter(h => h && typeof h.id === 'string' && Number.isFinite(Date.parse(h.at)) && Array.isArray(h.changes)).slice(0,20).map(h => ({id:h.id.slice(0,80),at:h.at,changes:h.changes.filter(c => c && validValue(c.key,c.before) && validValue(c.key,c.after))}));
    }
  } catch { storageHealthy = false; }
  let draft = clone(saved), page = 'skills', category = 'Все умения', filterStatus = '', searchText = '';
  let fieldSequence = 0, openedSkill = null, skillTab = 'settings', selectedCity = null, toastTimer = null;
  const changes = () => Object.keys(draft).filter(k => draft[k] !== saved[k]).map(key => ({key,before:saved[key],after:draft[key]}));
  const dateTime = value => new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Sao_Paulo'}).format(new Date(value))+' BRT';
  const badge = status => { const s=data.statuses[status]; return `<span class="chip ${s.className}" title="${esc(s.help)}">${icon(status==='configured'?'check':status==='check'?'info':status==='restricted'?'lock':status==='available'?'link':'minus')}${esc(s.label)}</span>`; };
  const chip = (label, tone='gray') => `<span class="chip ${tone}">${esc(label)}</span>`;
  const button = (label, action, extra='', cls='') => `<button class="button ${cls}" data-action="${action}" ${extra}>${esc(label)}</button>`;
  const heading = (title, description, label='НАСТРОЙКИ СОФИИ', action='') => `<section class="page-heading"><div><div class="eyebrow">${esc(label)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${action}</section>`;
  const panel = (title, description, content, extra='') => `<section class="panel ${extra}"><div class="panel-head"><div><h2>${esc(title)}</h2>${description?`<p>${esc(description)}</p>`:''}</div></div><div class="panel-body">${content}</div></section>`;
  const row = (label, value) => `<div class="readonly-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
  const note = text => `<p class="note">${text}</p>`;
  const metric = (label,value,subtitle,i,words=false) => `<div class="metric"><div class="metric-top"><span>${esc(label)}</span>${icon(i)}</div><strong class="metric-value ${words?'words':''}">${esc(value)}</strong><span class="metric-note">${esc(subtitle)}</span></div>`;
  const callout = (title,text,action='',tone='',i='weather') => `<section class="callout ${tone}"><div class="callout-icon">${icon(i)}</div><div class="callout-content"><h2>${esc(title)}</h2><p>${text}</p></div>${action}</section>`;
  function displayValue(key, value) {
    const f=data.fields[key];
    if (typeof value==='boolean') return value?'Включено':'Выключено';
    if (f?.type==='city') return value==='configured'?'Город сохранён на PLAN':data.cities.find(c=>c.id===value)?.name||'Не выбран';
    if (f?.type==='range') return value+'%';
    return f?.options?.find(o=>o[0]===value)?.[1] || String(value);
  }
  function field(key) {
    const f=data.fields[key], id='field-'+(++fieldSequence), val=draft[key];
    if (!f) return '';
    const kind=f.kind==='proposal'?'<span class="field-kind">Проект настройки</span>':f.kind==='fixed'?'<span class="field-kind">Правило системы</span>':'';
    const hint=f.description?`<span class="field-hint" id="${id}-hint">${esc(f.description)}</span>`:'';
    const described=f.description?`aria-describedby="${id}-hint"`:'';
    if(f.type==='fixed') return `<div class="field"><div class="field-label">${esc(f.label)} ${kind}</div><strong>${esc(f.value)}</strong>${hint}</div>`;
    if(f.type==='toggle') return `<div class="toggle-field"><div><label class="field-label" for="${id}">${esc(f.label)} ${kind}</label>${hint}</div><label class="switch"><input type="checkbox" id="${id}" data-field="${key}" ${val?'checked':''} ${described}><span class="switch-track"></span></label></div>`;
    let control='';
    if(f.type==='select') control=`<select id="${id}" data-field="${key}" ${described}>${f.options.map(o=>`<option value="${esc(o[0])}" ${o[0]===val?'selected':''} ${o[2]?'disabled':''}>${esc(o[1])}</option>`).join('')}</select>`;
    if(f.type==='text') control=`<input id="${id}" type="text" maxlength="80" data-field="${key}" value="${esc(val)}" ${described}>`;
    if(f.type==='range') control=`<div class="range-row"><input id="${id}" type="range" min="${f.min}" max="${f.max}" value="${esc(val)}" data-field="${key}" ${described}><output for="${id}">${esc(val)}%</output></div>`;
    if(f.type==='city') control=`<div class="city-current">${icon('pin')}<div><strong>${esc(displayValue(key,val))}</strong><p>${val==='configured'?'Фактическое место скрыто в дизайн-прототипе':'Выбранный пример · не применён на колонке'}</p></div></div>${button('Выбрать другой город','choose-city','','small')}`;
    return `<div class="field"><label class="field-label" ${f.type!=='city'?`for="${id}"`:''}>${esc(f.label)} ${kind}</label>${control}${hint}</div>`;
  }
  const fields = keys => keys.map(field).join('');
  function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,4500); }
  function updateSave() { const n=changes().length; $('reviewButton').disabled=!n; $('reviewButton').textContent=n?`Проверить изменения · ${n}`:'Нет изменений'; }
  function navigate(route) { location.hash='#/'+route; }
  function renderNavigation() {
    $('navigation').innerHTML=data.navigation.map(g=>`<div class="nav-group"><div class="nav-label">${g.group}</div>${g.items.map(([id,label,i])=>`<a class="nav-link" href="#/${id}" ${id===page?'aria-current="page"':''}>${icon(i)}${esc(label)}</a>`).join('')}</div>`).join('');
    $('breadcrumb').textContent=data.navigation.flatMap(g=>g.items).find(x=>x[0]===page)?.[1]||'Умения';
    $('menuButton').innerHTML=icon('menu');
  }
  function skillRows() {
    const q=searchText.toLocaleLowerCase('ru').trim();
    const list=data.skills.filter(s=>(category==='Все умения'||s.category===category)&&(!filterStatus||s.status===filterStatus)&&(!q||[s.name,s.description,s.service,s.settings,s.example,s.category].join(' ').toLocaleLowerCase('ru').includes(q)));
    if(!list.length) return `<div class="empty-state">${icon('search')}<h2>Таких умений не найдено</h2><p>Попробуйте другое название, сервис или снимите фильтр. Будущие интеграции тоже есть в каталоге.</p>${button('Сбросить фильтры','reset-filters')}</div>`;
    return `<div class="table-wrap"><table><caption class="sr-only">Умения выбранной колонки, состояние и настройки</caption><thead><tr><th scope="col">Умение</th><th scope="col">Состояние</th><th scope="col">Сервис и режим</th><th scope="col" class="th-settings">Главная настройка</th><th scope="col"><span class="sr-only">Действие</span></th></tr></thead><tbody>${list.map(s=>`<tr><td><div class="skill-name"><div class="skill-symbol">${icon(s.icon)}</div><div><strong>${esc(s.name)}</strong><small>${esc(s.description)}</small></div></div></td><td class="td-status">${badge(s.status)}</td><td class="td-service"><span class="service-name">${esc(s.service)}</span><span class="secondary">${esc(s.mode)}</span></td><td class="table-setting">${esc(s.settings)}</td><td class="td-action"><button class="row-action" data-action="skill" data-id="${s.id}" aria-label="Настройки: ${esc(s.name)}">${icon('settings')}Настроить</button></td></tr>`).join('')}</tbody></table></div><div class="table-footer"><span>Показано ${list.length} из ${data.skills.length} умений · выбранная колонка Spotpear</span><button class="text-button" data-action="legend">Что означают состояния</button></div>`;
  }
  function renderSkills() {
    return heading('Умения Софии','Всё, что София умеет, что ей нужно для работы и что можно настроить.','ВОЗМОЖНОСТИ И ПОДКЛЮЧЕНИЯ')+
      callout('Погода: источник отвечает, голосовой запрос нужно проверить','Домашний город уже сохранён. Open-Meteo ответил успешно; причина неверного голосового ответа исследуется.',button('Разобраться с погодой','go','data-page="home"'),'','weather')+
      `<div class="metrics">${metric('В каталоге',data.skills.length,'Реализованные и будущие умения','grid')}${metric('Нужна проверка',data.skills.filter(s=>s.status==='check').length,'Есть конкретные вопросы к работе','pulse')}${metric('Не подключено',data.skills.filter(s=>s.status==='missing').length,'Нужны реальные интеграции','link')}${metric('Тестовый терминал','Постоянно','Без проектного срока отключения','clock',true)}</div>`+
      `<section class="panel" aria-label="Каталог умений"><div class="toolbar"><label class="search">${icon('search')}<input id="skillSearch" type="search" placeholder="Найти умение, настройку или сервис" aria-label="Поиск по умениям" value="${esc(searchText)}"></label><div class="toolbar-right"><select id="statusFilter" aria-label="Фильтр по состоянию"><option value="">Все состояния</option>${Object.entries(data.statuses).map(([k,v])=>`<option value="${k}" ${filterStatus===k?'selected':''}>${v.label}</option>`).join('')}</select><button class="text-button" data-action="legend">О состояниях</button></div></div><div class="tabs" role="group" aria-label="Категории умений">${data.categories.map(c=>`<button class="tab" data-action="category" data-category="${c}" aria-pressed="${category===c}">${c}</button>`).join('')}</div><div id="skillResults">${skillRows()}</div><div class="sr-only" id="filterResultStatus" role="status" aria-live="polite"></div></section>`;
  }
  function renderOverview() {
    return heading('София под контролем','Один обзор для колонки, разговорных сервисов и важных настроек.','МОЙ GOBOT',button('Все умения','go','data-page="skills"'))+
    `<div class="metrics">${metric('Колонка','Готова','По снимку 20 ноября, 13:44 BRT','speaker',true)}${metric('Режим','Быстрый разговор','Голос marin · OpenAI Realtime','wave',true)}${metric('Погода','Источник отвечает','887 мс · отдельная проверка сервиса','weather',true)}${metric('Доступность','Без срока','Учёт расходов продолжается','clock',true)}</div>`+
    callout('С чего начать','Погода уже настроена. В голосовом обработчике найден случай, когда обращение «София» мешает распознать погодную команду. Нужен разбор пути команды, а не новый ключ сервиса.',button('Открыть диагностику','go','data-page="diagnostics"'))+
    `<div class="two-col"><div class="stack">${panel('Ваше устройство','Снимок состояния, без постоянного подключения из макета',`<div class="hero-device"><div class="large-face" aria-hidden="true"><i></i><i></i></div><div><h2>София</h2><p>Spotpear · установленная основа V4</p>${chip('Готова в момент проверки','green')}</div></div><div class="section-actions">${button('Настройки устройства','go','data-page="devices"')}${button('Разговор и голос','go','data-page="voice"')}</div>`)}${panel('Внимание к возможностям','Интерфейс отличает реализацию от фактической готовности',`<ul class="service-list"><li><div>Погода<small>Настроена, ответ источника подтверждён</small></div>${badge('check')}</li><li><div>Свежие сведения<small>Нужен проверенный источник веб-данных</small></div>${badge('missing')}</li><li><div>Прерывание ответа<small>Обновление установлено, нужна живая проверка</small></div>${badge('check')}</li></ul>`)}</div><div class="stack">${panel('Как устроена связь','Каждый участок имеет собственное состояние',`<ul class="check-list"><li>${icon('speaker')}<div><strong>Колонка Spotpear</strong><br>Просыпается, передаёт вопрос, воспроизводит ответ</div></li><li>${icon('server')}<div><strong>Домашний сервер PLAN</strong><br>Соединяет устройство, инструменты и голос</div></li><li>${icon('wave')}<div><strong>Голосовые сервисы</strong><br>OpenAI для разговора и marin для диктора</div></li><li>${icon('spark')}<div><strong>Эксперт Antigravity</strong><br>Выбран для сложных задач</div></li></ul><div class="section-actions">${button('Серверы и сервисы','go','data-page="connections"')}</div>`)}${panel('Тестируйте в удобное время','Постоянный терминал',`<p>Проектного двухчасового окна и общего денежного лимита нет. Действия и расход учитываются; квоты внешних провайдеров видны отдельно.</p><div class="section-actions">${button('Открыть расходы','go','data-page="costs"')}</div>`)}</div></div>`;
  }
  function renderHome() {
    return heading('Дом и погода','Одно домашнее место для погоды, понятные единицы и часовой пояс.','НАСТРОЙКИ ДОМА')+
    callout('Новый погодный сервис сейчас не требуется','Open-Meteo уже настроен и ответил с PLAN. Проверка источника не заменяет проверку вопроса, произнесённого на колонке.',button('Результат проверки','weather-proof'),'success','check')+
    `<div class="two-col"><div class="stack">${panel('Домашнее место','Используется, когда в вопросе не назван другой город',fields(['home.city'])+`<div class="form-section"><h3>Время дома</h3>${fields(['home.timezone','home.clockFormat'])}</div>`)}${panel('Погодный сервис','Источник выбирается явно и проверяется перед применением',fields(['weather.enabled','weather.provider'])+`<div class="form-section"><h3>Как сообщать погоду</h3><div class="field-grid">${fields(['weather.temperature','weather.wind'])}</div></div>`+note('Поля с меткой «Проект настройки» можно оценить в макете. Для их постоянного применения ещё нужно расширить настройки сервера.'))}</div><div class="stack">${panel('Что уже проверено','20 ноября 2026, 13:45 BRT',`<div class="weather-picture">${icon('weather')}<div><strong>Open-Meteo отвечает</strong><p>Показываем состояние источника, без выдуманного прогноза.</p></div></div><div class="source-proof"><strong>Получение погоды прошло успешно</strong>${draft['home.city']!=='configured'||!draft['weather.enabled']?'<p><strong>Это проверка сохранённого места на PLAN. Изменённый пример в макете не проверялся и не применялся.</strong></p>':''}<p>887 мс на запрос. Возраст данных при проверке — 42 секунды. Часовой пояс присутствует.</p><div class="proof-meta">Проверено с домашнего сервера PLAN</div></div><ul class="check-list"><li>${icon('check')}<span>Адаптер установлен</span></li><li>${icon('check')}<span>Место сохранено, координаты корректны</span></li><li>${icon('check')}<span>Источник вернул проверенные данные</span></li><li class="pending">${icon('info')}<span>Ответ на голосовой вопрос ещё нужно проверить</span></li></ul><div class="section-actions">${button('Почему не ответила голосом','go','data-page="diagnostics"')}</div>`)}${panel('Что поддерживает погода','Возможности текущего адаптера',`<dl>${row('Сейчас','Температура, осадки, ветер')}${row('Прогноз','Дневной, до 16 дней')}${row('Уточнения','«А завтра?» · «А ветер?»')}${row('Обновление','По вашему запросу')}${row('Почасовой прогноз',chip('Пока не реализован'))}${row('Weather.com',chip('Нужна интеграция'))}</dl>`+note('Уточнение о другом городе не должно менять домашнее место. Новый дом сохраняется только после явного выбора и подтверждения.'))}</div></div>`;
  }
  function renderVoice() {
    return heading('Разговор и голос','Обычная беседа и работа эксперта — с одним голосом и понятным переходом.','ГОЛОСОВОЕ ОБЩЕНИЕ')+
    `<div class="stack"><section class="panel"><div class="panel-head"><div><h2>Два режима разговора</h2><p>Действующий режим в снимке — быстрый. Макет не переключает колонку.</p></div></div><div class="panel-body"><div class="mode-grid"><article class="mode-card selected">${icon('wave')}<h3>Быстрый разговор</h3><p>Короткий вопрос, ответ и уточнение без повторного обращения по имени.</p><div class="mode-meta">OpenAI Realtime · gpt-realtime-2.1-mini</div>${chip('Выбран в снимке','green')}</article><article class="mode-card">${icon('spark')}<h3>Эксперт</h3><p>Аналитический вопрос передаётся Antigravity, готовый ответ озвучивает marin.</p><div class="mode-meta">Antigravity CLI · Gemini · ARGON_DEEP</div>${chip('Настроен · живая цепочка на проверке','blue')}</article></div><div class="flow" aria-label="Цепочка экспертного ответа"><span>Ваш вопрос</span>${icon('chevron')}<span>Короткий клип marin</span>${icon('chevron')}<span>Эксперт</span>${icon('chevron')}<span>Ответ marin</span>${icon('chevron')}<span>Уточнение</span></div></div></section><div class="two-col"><div class="stack">${panel('Как София отвечает','Предпочтения для будущей единой формы настроек',fields(['voice.language','voice.responseLength'])+`<div class="form-section"><h3>Передача эксперту</h3>${fields(['expert.confirm','expert.fallback'])}</div>`)}</div><div class="stack">${panel('Единый голос','Одинаковое звучание всех частей ответа',`<dl>${row('Быстрый разговор','marin')}${row('Клип ожидания','marin')}${row('Диктор эксперта','marin')}</dl>`+note('Голос закреплён в текущей реализации. Другие голоса не предлагаются как готовая замена, пока вся цепочка не проверена.'))}${panel('Если закончилась квота','Сбой провайдера не должен менять модель молча',`<p>По вашему сообщению недельная квота Codex исчерпана. Сейчас выбран Antigravity. Доступность профиля и реальный остаток квоты показываются отдельно.</p><div class="section-actions">${button('Посмотреть подключения','go','data-page="connections"')}</div>`)}${panel('Продолжение и остановка','Правила текущего разговора',`<ul class="list-spacing"><li>Одиночное «София» должно ждать вопрос.</li><li>После завершённого ответа можно уточнить без имени.</li><li>Имя или касание во время ответа останавливают воспроизведение.</li><li>Контекст получает услышанный ответ после подтверждения окончания.</li></ul><div class="section-actions">${button('Пробуждение и касание','skill','data-id="interrupt"')}</div>`)}</div></div></div>`;
  }
  function connectionCard(name,description,i,state,body) {
    return `<section class="panel connection-card"><div class="card-title-row"><div class="card-icon">${icon(i)}</div><div><h3>${esc(name)}</h3></div>${state}</div><p>${description}</p>${body}</section>`;
  }
  function renderConnections() {
    return heading('Серверы и сервисы','Домашний компьютер, его службы и внешние поставщики — у каждого своя роль.','ПОДКЛЮЧЕНИЯ')+
    callout('Это снимок, а не мониторинг в реальном времени','Проверенные состояния отмечены временем. Макет не проверяет ключи, не запускает модели и не перезапускает службы.',button('Источник данных','about'),'information','info')+
    `<div class="connection-grid">${connectionCard('Домашний сервер PLAN','Координирует колонку, голосовой разговор и инструменты.','server',chip('Доступен в снимке','green'),`<dl>${row('Текущий runtime','66fcae0')}${row('Автозапуск','При входе пользователя PLAN')}${row('Применение из админки','Ещё не подключено')}</dl><details class="details"><summary>Службы на этом сервере</summary><ul class="service-list">${[['GoBot Brain','Маршрутизация и правила','18781'],['Host Bridge','Изолированный эксперт','18782'],['Голосовой сервис','Распознавание и диктор','18783'],['Сервис изображений','Разрешённые визуальные ответы','18784'],['Device Gateway','Связь с колонкой','18789'],['Панель Софии','Нынешний интерфейс','18811']].map(x=>`<li><div>${x[0]}<small>${x[1]}</small></div><code>${x[2]}</code></li>`).join('')}</ul><p>Перечень служб из конфигурации. Отдельные показатели каждой службы в макет не загружены.</p></details><div class="section-actions">${button('Состояние устройства','go','data-page="devices"')}</div>`)}
    ${connectionCard('OpenAI','Быстрый разговор, распознавание задачи и голос marin.','wave',chip('Разговор разрешён','green'),`<dl>${row('Голос','marin')}${row('Учёт','API, отдельно по операциям')}${row('Ключ','Значение хранится на сервере')}</dl>`+note('Готовность голосового соединения подтверждена снимком. Ключи не читаются и не сохраняются в этом прототипе.')+`<div class="section-actions">${button('Расходы по операциям','go','data-page="costs"')}</div>`)}
    ${connectionCard('Antigravity CLI','Выбранный эксперт для аналитических задач.','spark',chip('Профиль выбран','blue'),`<dl>${row('Профиль','ARGON_DEEP')}${row('Модель','gemini-4-argon-medium')}${row('Где работает','На PLAN')}${row('Реальная квота','Остаток не загружен')}${row('Доступ в веб','Не разрешён изолированному эксперту')}</dl><div class="section-actions">${button('Правила передачи эксперту','go','data-page="voice"')}</div>`)}
    ${connectionCard('Open-Meteo','Текущая погода и дневной прогноз для выбранного места.','weather',chip('Источник ответил','green'),`<dl>${row('Проверка','20 ноября · 13:45 BRT')}${row('Время запроса','887 мс')}${row('Домашнее место','Настроено на PLAN')}${row('Голосовой ответ','Требует проверки')}</dl><div class="section-actions">${button('Дом и погода','go','data-page="home"')}</div>`)}
    ${connectionCard('Codex CLI','Другой зарегистрированный эксперт. Сейчас не выбран.','terminal',chip('Квота требует внимания','amber'),`<dl>${row('Основание','Ваше сообщение о недельном лимите')}${row('Повторная проверка квоты','Не выполнялась')}${row('Автоматический переход','Выключен')}</dl>`+note('Наличие программы в каталоге не означает доступную квоту. Текущая модель эксперта — Antigravity.'))}
    ${connectionCard('Будущие подключения','Поиск, календарь, музыка и умный дом.','link',chip('Нет адаптеров'),`<p>Для подключения нужны работающий исполнитель, права и проверка результата на выбранном устройстве. Ввод одного ключа этого не заменяет.</p><div class="section-actions">${button('Показать неподключённые умения','missing-skills')}</div>`)}</div>`;
  }
  function renderDevices() {
    return heading('Устройства','Состояние колонки и настройки, которые действительно относятся к ней.','КОЛОНКА SPOTPEAR')+
    `<div class="two-col"><div class="stack">${panel('София · Spotpear','Проверена 20 ноября, 13:44 BRT',`<div class="hero-device"><div class="large-face" aria-hidden="true"><i></i><i></i></div><div><h2>Я рядом</h2><p>Готова к новому обращению в снимке</p>${chip('Быстрый разговор','green')}</div></div><div class="form-section">${fields(['device.name','device.room'])}</div>`)}${panel('Звук и экран','Вид настроек для следующего этапа интеграции',fields(['device.volume','device.brightness','device.nightDisplay'])+note('Фактическая громкость и яркость не опрашивались. Значения здесь — примеры для оценки интерфейса; они не отправляются в прошивку.'))}</div><div class="stack">${panel('Пробуждение и прерывание','Рабочая основа Sophia V4 сохранена',`<div class="device-gesture"><div class="gesture">${icon('mic')}<strong>«София»</strong><p>Начать или прервать</p></div><div class="gesture">${icon('hand')}<strong>Касание</strong><p>Остановить ответ</p></div><div class="gesture">${icon('hand')}<strong>Удержание</strong><p>Завершить обмен</p></div></div>`+note('Аппаратная остановка и работа подавления эха проверены. Человеческое пробуждение во время ответа и качество речи ещё требуют живого прогона.')+`<dl style="margin-top:20px">${row('Слово пробуждения','София · фиксировано')}${row('Версия приложения','0.4.18-dev-sophia-barge-v4')}${row('Микрофон','Был доступен в снимке')}${row('Граница контекста','После playback_finished')}</dl>`)}${panel('Браузер — отдельное устройство','У него собственные привязка и доступ',`<p>Браузерный тест не подтверждает работу колонки и не получает её разрешения автоматически.</p>`+note('В готовой админке устройство выбирается явно. Профиль и настройки нельзя переносить между колонкой и браузером незаметно.'))}${panel('Обновление и восстановление','Обновления нужно показывать отдельно от настроек',`<dl>${row('Прежнее приложение','0.4.17 сохранено')}${row('Проверка отката','Выполнена при развёртывании')}${row('Изменение прошивки из макета','Недоступно')}</dl>`)}</div></div>`;
  }
  function renderPrivacy() {
    return heading('Люди и память','Кто может менять настройки, что София помнит и что попадает в диагностику.','ДОСТУП И ДАННЫЕ')+
    callout('Знакомый голос не открывает личные данные','Разрешение колонки на разговор не подтверждает личность человека рядом с ней. Для семейных архивов и изменений нужен отдельный проверенный доступ.','','information','shield')+
    `<div class="two-col"><div class="stack">${panel('Участники и права','Структура будущей формы, без персональных данных',`<ul class="service-list"><li><div><strong>Владелец</strong><small>Подтверждённые административные действия</small></div>${chip('Нужен owner-вход','blue')}</li><li><div><strong>Семья</strong><small>Индивидуальные права и предпочтения</small></div>${chip('Профили не загружены')}</li><li><div><strong>Гость</strong><small>Публичный разговор без личного архива</small></div>${chip('Контекст текущей беседы','green')}</li></ul><div class="form-section">${fields(['privacy.guestName'])}</div>`)}${panel('Текущий разговор и долговременная память','Это разные механизмы',`<dl>${row('Контекст беседы','В оперативной памяти')}${row('Ответ в контексте','После окончания воспроизведения')}${row('Личная память текущей колонки','Не включена в этом маршруте')}</dl><div class="form-section">${fields(['privacy.memory'])}</div>`)}</div><div class="stack">${panel('Текстовый журнал для отладки','Отдельное согласие, без фоновой записи звука',fields(['privacy.debug','privacy.retention'])+note('Действующий opt-in журнала в снимок не загружен. Прототип не включает запись и не получает домашние реплики. Срок хранения относится только к данным, а не к работе терминала.'))}${panel('Что хранится где','Принципы будущей админки',`<ul class="check-list"><li>${icon('server')}<span>Секреты сервисов остаются на PLAN.</span></li><li>${icon('lock')}<span>Отладочный текст шифруется локально и удаляется по сроку.</span></li><li>${icon('mic')}<span>Сырые домашние аудиозаписи не нужны для панели.</span></li><li>${icon('users')}<span>Данные семьи не смешиваются с гостевым контекстом.</span></li></ul>`)}</div></div>`;
  }
  function renderCosts() {
    return heading('Расходы и квоты','Учёт использования без искусственных окон работы и выключения по проектному бюджету.','ПОСТОЯННЫЙ ТЕРМИНАЛ')+
    callout('Терминал работает постоянно','Срок окончания не задан, общий денежный лимит проекта не задан. Квоты поставщиков остаются отдельными: например, подписка Codex может исчерпаться независимо от API.','','success','clock')+
    `<div class="metrics">${metric('Ответы быстрого режима','14','Подтверждённый счётчик снимка','wave')}${metric('Разговорные операции','4','Исторический учёт сохранён','history')}${metric('Задания эксперту','0','В текущем учёте терминала','spark')}${metric('Стоимость','Не загружена','Не подменяем неизвестную сумму нулём','wallet',true)}</div>`+
    `<div class="two-col"><div class="stack">${panel('За что учитываются расходы','Категории операций',`<ul class="service-list"><li><div><strong>Быстрый разговор</strong><small>OpenAI Realtime · 14 записей usage</small></div><span class="data-unavailable">Сумма не загружена</span></li><li><div><strong>Распознавание задачи</strong><small>Отдельная операция для эксперта</small></div><span>Нет операций в снимке</span></li><li><div><strong>Озвучивание эксперта</strong><small>Диктор marin</small></div><span>Нет операций в снимке</span></li><li><div><strong>Antigravity / Codex</strong><small>Квота CLI и подписки отдельно от API</small></div><span>Остаток не загружен</span></li></ul>`)}${panel('Уведомления','Показывают расход и не выключают колонку',fields(['costs.notify']))}</div><div class="stack">${panel('Три разных числа','Чтобы краткий ответ не выглядел дорогой сессией',`<ul class="list-spacing"><li><strong>Оценка стоимости</strong> — расчёт по известным показателям, не банковский счёт.</li><li><strong>Измеренное использование</strong> — данные, полученные от поставщика.</li><li><strong>Ожидает уточнения</strong> — незавершённый учёт; нельзя молча стереть или повторить запрос.</li></ul>`)}${panel('Если провайдер недоступен','Следующее действие выбираете вы',`<p>София объясняет причину и показывает доступный вариант. Сбой или исчерпание квоты не запускает другую платную модель автоматически.</p><div class="section-actions">${button('Проверить выбранного эксперта','go','data-page="connections"')}</div>`)}</div></div>`;
  }
  function renderDiagnostics() {
    return heading('Диагностика','Видно, на каком шаге возникла проблема и какие данные действительно получены.','ПОНИМАТЬ ПРИЧИНУ СБОЯ')+
    callout('Погодный сбой: сервис доступен, проверяем команду','Конфигурация и источник подтверждены. Бесплатный тест кода воспроизводит пропуск погодной команды с обращением «София». Точную причину последнего разговора ещё не установили.',button('Подробности проверки','weather-proof'))+
    `<div class="two-col"><div class="stack">${panel('Проверка погоды','Факты по шагам',`<ol class="timeline"><li>${icon('check')}<strong>Домашний профиль найден</strong><p>Погода включена, источник Open-Meteo, координаты корректны.</p><small>20 ноября · 13:44 BRT · чтение конфигурации</small></li><li>${icon('check')}<strong>Источник ответил</strong><p>887 мс, данные проверены, возраст 42 секунды.</p><small>20 ноября · 13:45 BRT · прямой запрос с PLAN</small></li><li>${icon('info')}<strong>Найден дефект обращения по имени</strong><p>«Какая погода завтра?» распознаётся; «София, какая погода завтра?» может не попасть в погодный обработчик.</p><small>Изолированная проверка функций · без платной модели</small></li><li>${icon('search')}<strong>Последний голосовой запрос не восстановлен</strong><p>Сейчас техническому журналу недостаёт безопасной записи конкретного результата погодного инструмента.</p><small>Нет доказательства, что именно найденный дефект вызвал последний отказ</small></li></ol>`)}${panel('Состояния, которые должна различать панель','Человек получает причину и следующее действие',`<ul class="service-list"><li><div>Нет домашнего места<small>Выбрать город и подтвердить</small></div>${chip('Настройка','blue')}</li><li><div>Источник не ответил<small>Показать время проверки и причину</small></div>${chip('Сервис','amber')}</li><li><div>Команда не распознана<small>Разобрать путь вопроса до инструмента</small></div>${chip('Маршрут','amber')}</li><li><div>Воспроизведение не подтверждено<small>Проверить соединение и очередь звука</small></div>${chip('Колонка','amber')}</li></ul>`)}</div><div class="stack">${panel('Задержки реальной реплики','Поля будущего отчёта, без выдуманных измерений',`<div class="diagnostic-steps"><div class="diagnostic-step"><span>Пробуждение</span><strong>Не загружено</strong><small>wake</small></div><div class="diagnostic-step"><span>Вопрос окончен</span><strong>Не загружено</strong><small>endpoint_decided</small></div><div class="diagnostic-step"><span>Первый звук пришёл</span><strong>Не загружено</strong><small>first_audio_packet</small></div><div class="diagnostic-step"><span>Колонка начала ответ</span><strong>Не загружено</strong><small>playback_started</small></div></div><dl>${row('Окончание воспроизведения','Не загружено')}${row('Просадки очереди звука','Для этой реплики не измерены')}${row('DMA underrun','Счётчик не инструментирован')}</dl>`+note('887 мс — время запроса к погодному источнику. Оно не является задержкой от пробуждения до голоса.'))}${panel('Поделиться диагностикой','Без реплик, ключей и координат',`<p>Можно выгрузить описание прототипа и уже известные технические факты. Домашняя история в него не входит.</p><div class="section-actions">${button('Скачать безопасный отчёт','export-report')}</div>`+note('Для реальной админки планируется журнал причины, источника, времени и результата. Текст диалога — только при отдельном согласии.'))}</div></div>`;
  }
  function renderHistory() {
    return heading('Изменения','Что вы настроили в прототипе. История сервера PLAN сюда не копировалась.','ЛОКАЛЬНЫЙ МАКЕТ',button('Сбросить макет','reset-demo','','subtle'))+
    (changes().length?callout('Есть несохранённые изменения',`Изменено полей: ${changes().length}. Перед сохранением можно сравнить прежние и новые значения.`,button('Проверить изменения','review'),'information','settings'):'')+
    `<section class="panel"><div class="panel-head"><div><h2>История настроек макета</h2><p>«Сохранено в макете» не означает «применено на колонке».</p></div>${chip('Только этот браузер','blue')}</div>${history.length?`<ol class="history-list">${history.map((h,index)=>`<li><div class="history-entry-head"><div><strong>Сохранено в макете · ${h.changes.length} ${h.changes.length===1?'поле':'поля'}</strong><small>${esc(dateTime(h.at))}</small></div>${index===0?button('Вернуть значения','revert','data-id="'+esc(h.id)+'"','small'):chip('Сохранено')}</div><ul class="history-changes">${h.changes.map(c=>`<li>${esc(data.fields[c.key]?.label||c.key)}: ${esc(displayValue(c.key,c.before))} · новое: ${esc(displayValue(c.key,c.after))}</li>`).join('')}</ul></li>`).join('')}</ol>`:`<div class="empty-state">${icon('history')}<h2>Вы ещё ничего не меняли</h2><p>Выберите город или измените предпочтение ответа. Здесь появится запись после сохранения макета.</p>${button('Открыть дом и погоду','go','data-page="home"')}</div>`}</section>`;
  }
  const views={overview:renderOverview,skills:renderSkills,home:renderHome,voice:renderVoice,connections:renderConnections,devices:renderDevices,privacy:renderPrivacy,costs:renderCosts,diagnostics:renderDiagnostics,history:renderHistory};
  function render() {
    const path=location.hash.replace(/^#\//,'').split('?')[0]; page=views[path]?path:'skills';
    renderNavigation(); $('main').innerHTML=views[page](); updateSave();
    document.title=$('breadcrumb').textContent+' · София · GoBot';
    if(!storageHealthy) toast('Хранилище браузера недоступно. Изменения пока можно только просмотреть.');
  }
  const narrowScreen=window.matchMedia('(max-width:760px)');
  function closeMobile(returnFocus=false) {
    $('sidebar').classList.remove('open');$('sidebar').inert=narrowScreen.matches;
    document.querySelector('.workspace').inert=false;$('mobileBackdrop').hidden=true;
    $('menuButton').setAttribute('aria-expanded','false');if(returnFocus)$('menuButton').focus();
  }
  function openMobile() {
    $('sidebar').inert=false;$('sidebar').classList.add('open');document.querySelector('.workspace').inert=true;
    $('mobileBackdrop').hidden=false;$('menuButton').setAttribute('aria-expanded','true');
    $('mobileNavClose').focus();
  }
  narrowScreen.addEventListener('change',()=>closeMobile());
  function dialogShell(title,subtitle,body,footer='',label='НАСТРОЙКИ УМЕНИЯ') {
    return `<header class="dialog-header"><div><div class="eyebrow">${esc(label)}</div><h2 id="dialogTitle">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="icon-button" data-action="close-dialog" aria-label="Закрыть панель">${icon('cross')}</button></header>${body}<footer class="dialog-footer"><p>Изменения только в макете. На PLAN ничего не отправляется.</p>${footer||button('Готово','close-dialog')}</footer>`;
  }
  function showDialog(content) { $('dialogContent').innerHTML=content;if(!$('settingsDialog').open)$('settingsDialog').showModal(); }
  function openSkill(id,tab='settings') {
    const s=data.skills.find(x=>x.id===id);if(!s)return;openedSkill=id;skillTab=tab;
    let content='';
    if(tab==='overview') content=badge(s.status)+`<p>${esc(s.detail)}</p><div class="quote">${esc(s.example)}</div><dl>${row('Сервис',esc(s.service))}${row('Разговорный режим',esc(s.mode))}${row('Устройство','Spotpear')}${row('Основание','Код и датированный снимок')}</dl>`;
    if(tab==='settings') content=badge(s.status)+(s.status==='missing'?note('Для этого умения ещё нужен адаптер. Поля ниже показывают будущие настройки и не включают сервис.'):'')+`<p style="margin-bottom:22px">${esc(s.detail)}</p>`+(s.fields.length?fields(s.fields):note(s.id==='interrupt'?'Слово «София» и основа V4 закреплены. Произвольное изменение детектора здесь не предлагается.':'Для этой возможности нет готовой настройки, которую можно безопасно менять из панели.'))+(s.page?`<div class="section-actions">${button('Открыть раздел настроек','go','data-page="'+s.page+'"')}</div>`:'');
    if(tab==='checks') content=badge(s.status)+`<p>${esc(s.detail)}</p><dl style="margin-top:20px">${row('Сервис',esc(s.service))}${row('Подтверждение на колонке',s.id==='fast'?'Готовность в снимке':'Не является полной живой приёмкой')}${row('Проверено',s.id==='weather'?'Источник · 20 ноября, 13:45 BRT':'По коду и паспорту системы')}${row('Прямой опрос сейчас','Из макета не выполняется')}</dl><details class="details"><summary>Техническое основание</summary><p><code>${esc(s.evidence)}</code></p><p>Ревизия исходников снимка: 6c1cbe7. Загруженный runtime: 66fcae0.</p></details>`+(s.id==='weather'?`<div class="section-actions">${button('Результат проверки источника','weather-proof')}</div>`:'');
    const tabs=`<div class="dialog-tabs" role="tablist" aria-label="Сведения об умении">${[['overview','Об умении'],['settings','Настройки'],['checks','Проверка']].map(([key,label])=>`<button class="dialog-tab" role="tab" id="skill-tab-${key}" aria-controls="skill-panel" aria-selected="${key===tab}" tabindex="${key===tab?0:-1}" data-action="skill-tab" data-tab="${key}">${label}</button>`).join('')}</div><div class="dialog-body" id="skill-panel" role="tabpanel" aria-labelledby="skill-tab-${tab}">${content}</div>`;
    showDialog(dialogShell(s.name,s.description,tabs));
  }
  function openCity() {
    selectedCity=null;
    showDialog(dialogShell('Выбрать домашний город','Сначала выбираем конкретное место, затем подтверждаем.',`<div class="dialog-body"><div class="field"><label class="field-label" for="citySearch">Город или населённый пункт</label><input id="citySearch" type="search" placeholder="Например, Имбитуба" autocomplete="off" aria-describedby="citySearchHint"><span class="field-hint" id="citySearchHint">Демонстрационный справочник из пяти мест. Реальный поиск географии к макету не подключён.</span></div><ul class="city-results" id="cityResults">${cityResults('')}</ul><div id="citySelection" aria-live="polite"></div>${note('При подключении к серверу сначала проверим погоду для выбранного места, затем сохраним. Ошибка проверки сохранит прежний домашний город.')}</div>`,'','ДОМ И ПОГОДА'));
    $('citySearch').focus();
  }
  function cityResults(query) {
    const q=query.trim().toLocaleLowerCase();
    const found=data.cities.filter(c=>[c.name,c.id,c.detail].join(' ').toLocaleLowerCase().includes(q));
    return found.length?found.map(c=>`<li><button class="city-choice" data-action="city-select" data-id="${c.id}">${icon('pin')}<div><strong>${esc(c.name)}</strong><span>${esc(c.detail)}</span></div></button></li>`).join(''):`<li class="empty-state"><p>Нет такого места в примерах. В готовой панели здесь будет поиск через геокодер.</p></li>`;
  }
  function about() {
    showDialog(dialogShell('Что здесь настоящее','Прототип интерфейса построен на проверенных исходниках и снимке системы.',`<div class="dialog-body"><h3>Факты, полученные с PLAN</h3><ul class="list-spacing"><li>Колонка 0.4.18 готова к быстрому разговору.</li><li>Выбран эксперт Antigravity, голос marin.</li><li>Домашняя погода включена; источник Open-Meteo ответил за 887 мс.</li><li>4 разговорные операции, 14 ответов в учёте на момент снимка.</li><li>Проектного срока и денежного лимита нет.</li></ul><h3 style="margin-top:24px">Что вы пробуете в макете</h3><ul class="list-spacing"><li>Навигацию, поиск, фильтры и боковые панели.</li><li>Выбор примера города и настройку предпочтений.</li><li>Просмотр изменений, сохранение в этом браузере и возврат значений.</li></ul>${note('Снимок: 20 ноября 2026, 13:44–13:45 BRT. Это не live-мониторинг. Имена домашнего места, координаты, ключи, реплики и частные журналы не включены.')}<details class="details"><summary>Граница следующего этапа</summary><p>Нужны owner-доступ, безопасный API конкретной колонки, ревизии настроек и подтверждение их фактического применения. Нынешний API /sophia умеет status, mode, mute и stop; универсальное сохранение настроек ещё не подключено.</p></details></div>`,'','О ПРОТОТИПЕ'));
  }
  function legend() {
    showDialog(dialogShell('Состояния умений','Зелёная отметка должна иметь понятное основание.',`<div class="dialog-body"><p>Установленный адаптер, доступный сервис и работающая голосовая команда — разные проверки.</p><div class="legend">${Object.keys(data.statuses).map(k=>`<div>${badge(k)}<p>${esc(data.statuses[k].help)}</p></div>`).join('')}</div>${note('Для полной готовности нужно подтвердить результат на выбранном устройстве. Дата снимка всегда сохраняется; неизвестное значение не превращается в «работает».')}</div>`,'','СОСТОЯНИЕ СИСТЕМЫ'));
  }
  function weatherProof() {
    showDialog(dialogShell('Проверка погодного источника','Фактический результат с домашнего сервера PLAN.',`<div class="dialog-body"><div class="source-proof"><strong>Open-Meteo ответил успешно</strong><p>Проверена существующая конфигурация одной колонки. Ничего не записывалось в её профиль.</p></div><dl style="margin-top:20px">${row('Время проверки','20 ноября 2026 · 13:45:42 BRT')}${row('Запрос занял','887 мс')}${row('Возраст данных','42 с в момент получения')}${row('Часовой пояс','Присутствует')}${row('Домашние координаты','Корректны · не опубликованы')}${row('Вызов платной модели','Не выполнялся')}</dl>${note('<strong>Голосовой путь — отдельная проверка.</strong> Найден воспроизводимый дефект обработки обращения «София», но текущий журнал не позволяет доказать, что именно он вызвал последний неверный ответ.')}<div class="section-actions">${button('Открыть диагностику','go','data-page="diagnostics"')}</div></div>`,'','ИСТОЧНИК ОТВЕЧАЕТ'));
  }
  function openReview() {
    const diff=changes(); if(!diff.length){toast('Изменений пока нет.');return;}
    $('reviewContent').innerHTML=`<header class="dialog-header"><div><div class="eyebrow">ПЕРЕД СОХРАНЕНИЕМ</div><h2 id="reviewTitle">Проверить изменения</h2><p>Только макет · ${diff.length} ${diff.length===1?'поле':'поля'}</p></div><button class="icon-button" data-action="close-review" aria-label="Закрыть проверку">${icon('cross')}</button></header><div class="review-body"><p>Изменения будут сохранены в этом браузере. Существующая конфигурация PLAN и физической колонки останется прежней.</p>${diff.map(c=>`<div class="review-item"><strong>${esc(data.fields[c.key].label)} ${data.fields[c.key].kind==='proposal'?'<span class="field-kind">Проект настройки</span>':''}</strong><div class="review-values"><span><small>Было в макете</small>${esc(displayValue(c.key,c.before))}</span><span class="new"><small>Станет в макете</small>${esc(displayValue(c.key,c.after))}</span></div></div>`).join('')}${note('В рабочей админке следующий шаг будет отдельным: проверка прав и источника, сохранение на сервере, затем подтверждение применения на колонке. Здесь серверных действий нет.')}</div><footer class="review-actions">${button('Отменить изменения','discard','','subtle')}${button('Сохранить макет','save-demo','','primary')}</footer>`;
    if(!$('reviewDialog').open)$('reviewDialog').showModal();
  }
  function persist(nextSettings,nextHistory) {
    try { localStorage.setItem(storageKey,JSON.stringify({version:1,settings:nextSettings,history:nextHistory}));storageHealthy=true;return true; }
    catch {storageHealthy=false;toast('Не удалось сохранить в браузере. Изменения сохранены только на открытой странице.');return false;}
  }
  function saveDemo() {
    const diff=changes();if(!diff.length)return;
    const entry={id:'change-'+Date.now(),at:new Date().toISOString(),changes:diff};
    const nextHistory=[entry,...history].slice(0,20);
    if(!persist(draft,nextHistory))return;
    saved=clone(draft);history=nextHistory;$('reviewDialog').close();if($('settingsDialog').open)$('settingsDialog').close();render();toast('Сохранено в макете. Колонка и сервер не изменены.');
  }
  function resetDemo() {
    showDialog(dialogShell('Сбросить макет','Удалится только история этого прототипа в данном браузере.',`<div class="dialog-body"><p>Пример настроек вернётся к исходным значениям. Это действие не затрагивает PLAN, колонку, учёт расходов или реальную память Софии.</p></div>`,button('Сбросить только макет','reset-demo-confirm','','danger'),'ЛОКАЛЬНЫЕ ДАННЫЕ'));
  }
  function exportReport() {
    const report={kind:'gobot_admin_ui_redacted_snapshot',schema_version:1,generated_at:new Date().toISOString(),not_live:true,snapshot:data.snapshot,weather_issue:{source:'verified',voice_result:'not_verified',candidate:'sophia_prefix_not_normalized',last_voice_failure_cause:'unknown'},measured_voice_latency:null,dma_underrun_counter:'not_instrumented',runtime_modified:false,private_text_included:false};
    const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='sophia-admin-safe-report.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);toast('Выгружен снимок без ключей, координат и диалогов.');
  }
  function onAction(event) {
    const el=event.target.closest('[data-action]');if(!el)return;
    const action=el.dataset.action;
    if(action==='go'){if($('settingsDialog').open)$('settingsDialog').close();navigate(el.dataset.page);}
    if(action==='about')about();if(action==='legend')legend();if(action==='weather-proof')weatherProof();
    if(action==='skill')openSkill(el.dataset.id);
    if(action==='skill-tab'){openSkill(openedSkill,el.dataset.tab);$('skill-tab-'+el.dataset.tab)?.focus();}
    if(action==='close-dialog')$('settingsDialog').close();
    if(action==='close-review')$('reviewDialog').close();
    if(action==='category'){category=el.dataset.category;$('skillResults').innerHTML=skillRows();document.querySelectorAll('[data-action=category]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.category===category)));announceFilters();}
    if(action==='reset-filters'){category='Все умения';filterStatus='';searchText='';render();$('skillSearch')?.focus();}
    if(action==='missing-skills'){filterStatus='missing';category='Все умения';searchText='';if(page==='skills')render();else navigate('skills');}
    if(action==='choose-city')openCity();
    if(action==='city-select'){
      selectedCity=data.cities.find(c=>c.id===el.dataset.id);if(!selectedCity)return;
      $('citySelection').innerHTML=`<div class="city-selection"><strong>${esc(selectedCity.name)}</strong><p>${esc(selectedCity.detail)}<br>Пояс: ${esc(selectedCity.timezone)}</p><p>Этот выбор заменит только пример домашнего города в макете.</p>${button('Подтвердить город в макете','city-confirm','','primary')}</div>`;
      $('citySelection').scrollIntoView({block:'nearest'});
    }
    if(action==='city-confirm'&&selectedCity){draft['home.city']=selectedCity.id;draft['home.timezone']=selectedCity.timezone;$('settingsDialog').close();render();toast('Город добавлен в изменения макета. Проверьте и сохраните.');}
    if(action==='review')openReview();
    if(action==='discard'){draft=clone(saved);$('reviewDialog').close();if($('settingsDialog').open)$('settingsDialog').close();render();toast('Несохранённые изменения отменены.');}
    if(action==='save-demo')saveDemo();
    if(action==='revert'){const entry=history.find(h=>h.id===el.dataset.id);if(entry){for(const c of entry.changes)draft[c.key]=c.before;updateSave();openReview();}}
    if(action==='reset-demo')resetDemo();
    if(action==='reset-demo-confirm'){const initial=clone(data.defaults);if(persist(initial,[])){saved=initial;draft=clone(saved);history=[];$('settingsDialog').close();render();toast('Макет сброшен. Реальная система не изменена.');}}
    if(action==='export-report')exportReport();
  }
  function announceFilters(){const count=$('skillResults')?.querySelectorAll('tbody tr').length||0;if($('filterResultStatus'))$('filterResultStatus').textContent=`Найдено умений: ${count}`;}
  document.addEventListener('click',onAction);
  document.addEventListener('input',event=>{
    const el=event.target;
    if(el.id==='skillSearch'){searchText=el.value;$('skillResults').innerHTML=skillRows();announceFilters();}
    if(el.id==='citySearch')$('cityResults').innerHTML=cityResults(el.value);
    if(el.dataset.field){const key=el.dataset.field;const val=el.type==='checkbox'?el.checked:el.value;if(validValue(key,val)){draft[key]=val;updateSave();if(el.type==='range')el.parentElement.querySelector('output').textContent=val+'%';}}
  });
  document.addEventListener('change',event=>{
    const el=event.target;if(el.id==='statusFilter'){filterStatus=el.value;$('skillResults').innerHTML=skillRows();announceFilters();}
    if(el.dataset.field){const key=el.dataset.field,val=el.type==='checkbox'?el.checked:el.value;if(validValue(key,val)){draft[key]=val;updateSave();}}
  });
  document.addEventListener('keydown',event=>{
    if(event.target.matches('.dialog-tab')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      event.preventDefault();const tabs=['overview','settings','checks'];let i=tabs.indexOf(skillTab);i=event.key==='Home'?0:event.key==='End'?2:(i+(event.key==='ArrowRight'?1:2))%3;openSkill(openedSkill,tabs[i]);$('skill-tab-'+tabs[i]).focus();
    }
    if($('sidebar').classList.contains('open')){
      if(event.key==='Escape'){closeMobile(true);}
      if(event.key==='Tab'){
        const focusable=[...$('sidebar').querySelectorAll('button,a[href]')].filter(e=>e.offsetParent!==null);
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      }
    }
  });
  $('reviewButton').addEventListener('click',openReview);
  $('menuButton').addEventListener('click',openMobile);
  $('mobileNavClose').addEventListener('click',()=>closeMobile(true));
  $('mobileBackdrop').addEventListener('click',()=>closeMobile(true));
  $('sidebar').addEventListener('click',event=>{if(narrowScreen.matches&&event.target.closest('a')){closeMobile();$('main').focus({preventScroll:true});}});
  window.addEventListener('hashchange',()=>{closeMobile();render();window.scrollTo(0,0);$('main').focus({preventScroll:true});});
  window.addEventListener('beforeunload',e=>{if(changes().length){e.preventDefault();e.returnValue='';}});
  render();closeMobile();
})();
