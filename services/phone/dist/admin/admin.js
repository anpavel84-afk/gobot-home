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
  const API = '/api/sophia/admin';
  let snapshot = null, latest = null, saved = null, revision = null, changesLog = [];
  let draftEnabled = null, draftCandidate = null, draftProof = null, currentProof = null;
  let page = 'skills', category = 'Все умения', filterStatus = '', searchText = '';
  let fieldSequence = 0, openedSkill = null, skillTab = 'settings', selectedCity = null;
  let candidates = [], toastTimer = null, busy = false, loading = false, loadSequence = 0;
  let problem = '', conflict = false, lastLoaded = 0, actionError = '', pendingApply = null;
  let reviewAfterVerify = false;
  const errorMessages = {
    sophia_admin_private_owner_only:'Панель доступна локально на PLAN или через приватный адрес Tailscale владельца.',
    sophia_admin_owner_binding_unavailable:'Не удалось прочитать привязку владельца панели. Требуется восстановление настройки на PLAN.',
    sophia_admin_owner_required:'Доступ к панели разрешён учётной записи Tailscale владельца.',
    admin_profile_unavailable:'Профиль выбранной колонки сейчас недоступен. Сохранение заблокировано.',
    admin_profile_ambiguous:'Найдено несколько профилей колонки. Сервер не будет выбирать произвольно.',
    operation_conflict:'Операция с таким идентификатором уже существует с другими значениями. Настройки не перезаписаны.',
    weather_source_timeout:'Погодный источник не ответил вовремя. Сохранённые настройки не изменились.',
    weather_source_unavailable:'Погодный источник сейчас недоступен. Сохранённые настройки не изменились.',
    weather_provider_rate_limit:'Погодный сервис временно ограничил запросы. Повторите проверку позже.',
    weather_data_not_fresh:'Погодный сервис вернул устаревшие данные. Новый город не сохранён.',
    weather_invalid_data:'Погодный сервис вернул данные, которые не прошли проверку. Настройки не изменились.',
    weather_source_rejected:'Погодный сервис отклонил запрос. Настройки не изменились.',
    weather_response_limit:'Ответ погодного сервиса превышает допустимый размер. Настройки не изменились.',
    weather_verification_mismatch:'Проверка относится к другому месту. Проверьте выбранный город снова.',
    admin_owner_required:'Доступ к настройкам разрешён только владельцу. Откройте панель на PLAN или через свою учётную запись Tailscale.',
    owner_required:'Нужен доступ владельца к этой панели.',
    private_voice_panel_only:'Откройте панель по локальному адресу PLAN или приватному адресу Tailscale.',
    admin_owner_unavailable:'Не удалось проверить доступ владельца. Проверьте подключение Tailscale.',
    revision_conflict:'Настройки изменились в другой вкладке. Обновите значения и заново проверьте свой выбор.',
    weather_candidate_expired:'Результат поиска города устарел. Найдите и выберите город ещё раз.',
    verification_expired:'Проверка источника устарела. Проверьте выбранное место ещё раз.',
    weather_verification_expired:'Проверка источника устарела. Проверьте выбранное место ещё раз.',
    weather_verification_required:'Перед сохранением проверьте погодный источник для выбранного места.',
    weather_location_required:'Сначала найдите и подтвердите домашний город.',
    invalid_setting:'Сервер не принял настройку. Проверьте выбранный город и значение поля.',
    source_timeout:'Погодный источник не ответил вовремя. Сохранённые настройки не изменились.',
    source_unavailable:'Погодный источник сейчас недоступен. Сохранённые настройки не изменились.',
    provider_rate_limit:'Погодный сервис временно ограничил запросы. Повторите проверку позже.',
    data_not_fresh:'Погодный сервис вернул устаревшие данные. Новый город не сохранён.',
    target_unavailable:'Профиль этой колонки не найден. Сохранение недоступно до восстановления профиля.',
    target_ambiguous:'Сервер не смог однозначно выбрать профиль колонки. Изменения заблокированы.',
    admin_target_unavailable:'Не удалось прочитать профиль выбранной колонки.',
    mode_change_requires_idle:'Дождитесь окончания ответа или нажмите «Остановить ответ».',
    voice_device_not_connected:'Колонка сейчас не подключена к голосовому серверу.',
    conversation_busy:'Сейчас идёт реплика. Дождитесь её окончания или остановите ответ.',
    voice_control_unavailable:'Команда не подтверждена голосовым сервером. Обновите состояние перед повтором.',
    operation_id_conflict:'Такая операция уже существует с другими значениями. Обновите настройки.',
    request_failed:'Не удалось связаться с PLAN. Проверьте сеть и Tailscale, затем обновите страницу.',
    request_timeout:'Сервер не ответил вовремя. Результат сохранения пока неизвестен — проверьте состояние.',
    unavailable:'Сервер настроек временно недоступен. Работу колонки проверяйте отдельно.'
  };
  function humanError(error) {
    if (errorMessages[error?.code]) return errorMessages[error.code];
    if (error?.status === 403) return errorMessages.admin_owner_required;
    if (error?.status === 409) return errorMessages.revision_conflict;
    if (error?.status === 410) return 'Выбор города или проверка устарели. Повторите поиск и проверку источника.';
    if (error?.status === 422) return errorMessages.invalid_setting;
    if (error?.status === 429) return 'Слишком много запросов подряд. Подождите немного и повторите действие.';
    return errorMessages.unavailable;
  }
  async function api(path, body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 18000);
    try {
      const response = await fetch(API+path, {method:body === undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal,...(body === undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
      let value; try { value = await response.json(); } catch { value = {}; }
      if (!response.ok || value.ok === false) {
        const error = new Error('admin_request_failed');
        error.status=response.status;
        error.code=typeof value.detail==='string'?value.detail:typeof value.code==='string'?value.code:'unavailable';
        throw error;
      }
      return value;
    } catch (error) {
      if (!error.code) error.code=error.name==='AbortError'?'request_timeout':'request_failed';
      throw error;
    } finally { clearTimeout(timer); }
  }
  function dateTime(value) {
    if (value == null) return 'Не получено';
    const date = new Date(typeof value === 'number' && value < 1e12 ? value*1000 : value);
    return Number.isFinite(date.getTime())?new Intl.DateTimeFormat('ru-RU',{dateStyle:'medium',timeStyle:'short',timeZone:'America/Sao_Paulo'}).format(date)+' BRT':'Не получено';
  }
  function timestamp(value) { return typeof value==='number'?(value<1e12?value*1000:value):Date.parse(value); }
  const proofFresh = proof => proof?.verified === true && Number.isFinite(timestamp(proof.expires_at)) && timestamp(proof.expires_at)>Date.now();
  const chip = (label,tone='gray') => `<span class="chip ${tone}">${esc(label)}</span>`;
  const badge = status => {const s=data.statuses[status]||data.statuses.unknown;return `<span class="chip ${s.className}" title="${esc(s.help)}">${icon(status==='configured'?'check':status==='check'?'info':status==='restricted'?'lock':status==='available'?'link':'minus')}${esc(s.label)}</span>`;};
  const button = (label,action,extra='',cls='') => `<button class="button ${cls}" data-action="${action}" ${extra}>${esc(label)}</button>`;
  const heading = (title,description,label='НАСТРОЙКИ СОФИИ',action='') => `<section class="page-heading"><div><div class="eyebrow">${esc(label)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${action}</section>`;
  const panel = (title,description,content,extra='') => `<section class="panel ${extra}"><div class="panel-head"><div><h2>${esc(title)}</h2>${description?`<p>${esc(description)}</p>`:''}</div></div><div class="panel-body">${content}</div></section>`;
  const row = (label,value) => `<div class="readonly-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
  const note = text => `<p class="note">${text}</p>`;
  const metric = (label,value,subtitle,i,words=false) => `<div class="metric"><div class="metric-top"><span>${esc(label)}</span>${icon(i)}</div><strong class="metric-value ${words?'words':''}">${esc(value)}</strong><span class="metric-note">${esc(subtitle)}</span></div>`;
  const callout = (title,text,action='',tone='',i='info') => `<section class="callout ${tone}"><div class="callout-icon">${icon(i)}</div><div class="callout-content"><h2>${esc(title)}</h2><p>${text}</p></div>${action}</section>`;
  const runtime = () => snapshot?.runtime || {};
  const session = () => runtime().brain?.sessions?.[0] || {};
  const device = () => runtime().device || {};
  const admission = () => runtime().brain?.admission || {};
  const canEdit = () => saved !== null && !problem && !busy && !conflict && !pendingApply;
  const hasChanges = () => saved !== null && (draftEnabled !== saved.enabled || !!draftCandidate);
  function modeName(mode) { return mode==='fast'?'Быстрый разговор':mode==='expert'?'Эксперт':'Не получен'; }
  function phaseName() {
    if (problem || !snapshot) return 'Нет свежих данных';
    if (['unavailable','stale'].includes(runtime().status) || runtime().stale === true || runtime().gateway_fresh === false) return 'Связь требует проверки';
    if (device().device_protocol_confirmed !== true) return 'Ожидается колонка';
    if (session().muted === true) return 'Микрофон выключен';
    const state=device().voice_phase || session().state;
    return {listening:'Слушает',speaking:'Отвечает',thinking:'Обдумывает',closing_input:'Готовит ответ',stopping:'Останавливает ответ',waiting:'Ожидает продолжения',ready:'На связи',blocked:'Допуск закрыт',disconnected:'Нет связи',closed:'Разговор закрыт'}[state] || (session().ready?'На связи':'Проверяем разговор');
  }
  function ready() { return !problem && !['unavailable','stale'].includes(runtime().status) && runtime().stale!==true && runtime().gateway_fresh!==false && session().ready===true && device().device_protocol_confirmed===true; }
  function cloudReady() { return !problem && snapshot!==null && runtime().status!=='unavailable' && session().ready===true; }
  function deviceConnected() { return !problem && runtime().gateway_fresh!==false && !['stale','unavailable'].includes(runtime().status) && device().device_protocol_confirmed===true; }
  function weatherProof() { return draftCandidate ? draftProof : currentProof; }
  function weatherState() {
    if (!saved || problem) return 'Нет свежих данных';
    if (draftCandidate) return proofFresh(draftProof)?'Новый город проверен':'Проверьте новый город';
    if (!saved.enabled) return 'Выключена';
    if (!saved.location_name) return 'Нужно выбрать город';
    if (currentProof?.verified===false) return 'Проверка не прошла';
    return proofFresh(currentProof)?'Источник отвечает':'Источник нужно проверить';
  }
  function applicationText(app=snapshot?.application) {
    const home=session().lifecycle?.home_context;
    if(!problem && ready() && home?.state==='applied' && home.applied_revision && home.applied_revision===app?.expected_home_context_revision) return 'Город подтверждён текущим голосовым сеансом. Новый погодный вопрос использует сохранённое место. Это подтверждение серверной настройки, а не воспроизведения на колонке.';
    return typeof app?.message === 'string'?app.message:'Сохранение действует для погоды этой колонки. Получение ответа на колонке подтверждается отдельно.';
  }
  function skillState(s) {
    if (s.id==='fast') return !snapshot||problem?'unknown':ready()&&session().generation_allowed===true?'configured':'check';
    if (s.id==='expert') return !snapshot||problem?'unknown':session().selected_expert?'configured':'check';
    if (s.id==='weather') return !saved||problem?'unknown':saved.enabled&&saved.location_name?'configured':'check';
    return s.status;
  }
  function skillSetting(s) {
    if (s.id==='weather') return !saved?'Профиль ещё не загружен':saved.enabled?(saved.location_name||'Выберите город'):'Погода выключена';
    if (s.id==='expert') return session().selected_expert?.model || 'Профиль не получен';
    if (s.id==='fast') return !snapshot?'Состояние не загружено':phaseName();
    return s.settings;
  }
  function toast(message) { $('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500); }
  function updateHeader() {
    $('connectionLabel').textContent=problem?'Нет связи':snapshot?'PLAN · подключено':'Подключение…';
    $('connectionStrip').classList.toggle('connection-error',!!problem);
    $('connectionDescription').textContent=problem || (snapshot?`Настройки колонки Spotpear. Обновлено ${dateTime(snapshot.observed_at || lastLoaded)}. Сохранение меняет настройки на PLAN.`:'Загружаем настройки колонки с PLAN…');
    $('refreshButton').disabled=loading||busy;
    const count=saved?Number(draftEnabled!==saved.enabled)+Number(!!draftCandidate):0;
    $('reviewButton').disabled=!count||busy||!!problem||conflict||!!pendingApply;
    $('reviewButton').textContent=count?`Проверить изменения · ${count}`:'Нет изменений';
  }
  function acceptSnapshot(value,{reset=false}={}) {
    if (!value || !value.target || typeof value.revision!=='string' || typeof value.settings?.weather?.enabled!=='boolean') {
      const error=new Error('invalid_snapshot');error.code='unavailable';throw error;
    }
    if (snapshot && value.target.id!==snapshot.target.id) {const error=new Error('target_changed');error.code='target_ambiguous';throw error;}
    const dirty=hasChanges(); latest=value;
    if (!saved || reset || !dirty) {
      saved=clone(value.settings.weather);revision=value.revision;draftEnabled=saved.enabled;draftCandidate=null;draftProof=null;conflict=false;
    } else if (revision!==value.revision) { conflict=true; }
    snapshot=value;currentProof=value.weather_check || null;
    if (Array.isArray(value.changes)) changesLog=value.changes;
    lastLoaded=Date.now();problem='';
  }
  async function load({manual=false,reset=false}={}) {
    if (loading || busy) return;
    loading=true;const seq=++loadSequence;updateHeader();
    try {
      const value=await api('/snapshot');
      if (seq!==loadSequence)return;
      acceptSnapshot(value,{reset});
      if (manual || conflict || !$('settingsDialog').open && !$('reviewDialog').open) render();
      else updateHeader();
      if (manual)toast('Состояние и настройки прочитаны с PLAN.');
    } catch(error) {
      problem=humanError(error);updateHeader();
      render();
    } finally { loading=false;updateHeader(); }
  }
  function navigate(route) { location.hash='#/'+route; }
  function renderNavigation() {
    $('navigation').innerHTML=data.navigation.map(g=>`<div class="nav-group"><div class="nav-label">${esc(g.group)}</div>${g.items.map(([id,label,i])=>`<a class="nav-link" href="#/${id}" ${id===page?'aria-current="page"':''}>${icon(i)}${esc(label)}</a>`).join('')}</div>`).join('');
    $('breadcrumb').textContent=data.navigation.flatMap(g=>g.items).find(x=>x[0]===page)?.[1]||'Умения';$('menuButton').innerHTML=icon('menu');
  }
  function field(key) {
    const f=data.fields[key],id='field-'+(++fieldSequence);if(!f)return '';
    const disabled=!canEdit()?'disabled':'';
    if(key==='home.city')return `<div class="field"><div class="field-label">Домашний город ${chip('Эта колонка','blue')}</div><div class="city-current">${icon('pin')}<div><strong>${esc(draftCandidate?.location_name || saved?.location_name || (saved?'Не выбран':'Загружается…'))}</strong><p>${draftCandidate?'Проверенный выбор · ещё не сохранён':'Сохранённое место на домашнем сервере'}</p></div></div>${button('Найти и выбрать город','choose-city',disabled,'small')}</div>`;
    if(key==='weather.enabled')return `<div class="toggle-field"><div><label class="field-label" for="${id}">${esc(f.label)}</label><span class="field-hint" id="${id}-hint">Использовать домашнее место, когда в вопросе не назван другой город.</span></div><label class="switch"><input type="checkbox" id="${id}" data-field="weather.enabled" ${draftEnabled===true?'checked':''} ${disabled} aria-describedby="${id}-hint"><span class="switch-track"></span></label></div>`;
    if(key==='weather.provider')return `<div class="field"><label class="field-label" for="${id}">Погодный сервис</label><select id="${id}" disabled aria-describedby="${id}-hint"><option>${saved?.provider==='open_meteo'?'Open-Meteo · действующий адаптер':'Сервис не получен'}</option><option disabled>Weather.com · адаптер ещё не подключён</option><option disabled>OpenWeather · адаптер ещё не подключён</option></select><span class="field-hint" id="${id}-hint">Сейчас доступен один проверенный адаптер. Для других источников потребуется интеграция.</span></div>`;
    if(f.type==='fixed')return `<div class="field"><div class="field-label">${esc(f.label)} <span class="field-kind">Правило системы</span></div><strong>${esc(f.value)}</strong>${f.description?`<span class="field-hint">${esc(f.description)}</span>`:''}</div>`;
    return `<div class="field unsupported-field"><div class="field-label">${esc(f.label)} <span class="field-kind">Пока не редактируется</span></div><div class="unsupported-value">Управление этой настройкой ещё не подключено</div>${f.description?`<span class="field-hint">${esc(f.description)}</span>`:''}</div>`;
  }
  const fields=keys=>keys.map(field).join('');
  function editingNotices() {
    let html='';
    if(conflict)html+=callout('Настройки изменились на сервере','Ваш черновик сохранён на этой странице. Просмотрите новое серверное значение перед повторным выбором.',button('Сравнить версии','conflict'),'','history');
    if(pendingApply)html+=callout('Результат сохранения уточняется','Запрос уже отправлен. Проверьте его по идентификатору операции, прежде чем менять настройки снова.',button('Проверить сохранение','resolve-apply'),'','history');
    return html;
  }
  function filteredSkills() {
    const q=searchText.toLocaleLowerCase('ru').trim();
    return data.skills.filter(s=>(category==='Все умения'||s.category===category)&&(!filterStatus||skillState(s)===filterStatus)&&(!q||[s.name,s.description,s.service,s.settings,s.example,s.category].join(' ').toLocaleLowerCase('ru').includes(q)));
  }
  function skillRows() {
    const list=filteredSkills();
    if(!list.length)return `<div class="empty-state">${icon('search')}<h2>Таких умений не найдено</h2><p>Попробуйте другое название или снимите фильтры.</p>${button('Сбросить фильтры','reset-filters')}</div>`;
    return `<div class="table-wrap"><table><caption class="sr-only">Умения выбранной колонки и доступные настройки</caption><thead><tr><th scope="col">Умение</th><th scope="col">Состояние</th><th scope="col">Сервис и режим</th><th scope="col" class="th-settings">Главная настройка</th><th scope="col"><span class="sr-only">Действие</span></th></tr></thead><tbody>${list.map(s=>`<tr><td><div class="skill-name"><div class="skill-symbol">${icon(s.icon)}</div><div><strong>${esc(s.name)}</strong><small>${esc(s.description)}</small></div></div></td><td class="td-status">${badge(skillState(s))}</td><td class="td-service"><span class="service-name">${esc(s.service)}</span><span class="secondary">${esc(s.mode)}</span></td><td class="table-setting">${esc(skillSetting(s))}</td><td class="td-action"><button class="row-action" data-action="skill" data-id="${s.id}" aria-label="Настройки: ${esc(s.name)}">${icon('settings')}Открыть</button></td></tr>`).join('')}</tbody></table></div><div class="table-footer"><span>Показано ${list.length} из ${data.skills.length} умений · колонка Spotpear</span><button class="text-button" data-action="legend">Что означают состояния</button></div>`;
  }
  function renderSkills() {
    return heading('Умения Софии','Все возможности, их зависимости и доступные настройки в одном месте.','ВОЗМОЖНОСТИ И ПОДКЛЮЧЕНИЯ')+
      callout('Дом и погода — можно настраивать',`Домашнее место: <strong>${esc(saved?.location_name || (saved?'не выбрано':'загружается'))}</strong>. ${esc(weatherState())}.`,button('Открыть настройки погоды','go','data-page="home"'),'','weather')+
      `<div class="metrics">${metric('В каталоге',data.skills.length,'Реализованные и будущие умения','grid')}${metric('Колонка',phaseName(),'По последнему ответу сервера','speaker',true)}${metric('Не подключено',data.skills.filter(s=>s.status==='missing').length,'Нужны реальные интеграции','link')}${metric('Настройки','На PLAN','Выбранная колонка Spotpear','settings',true)}</div>`+
      `<section class="panel" aria-label="Каталог умений"><div class="toolbar"><label class="search">${icon('search')}<input id="skillSearch" type="search" placeholder="Найти умение, настройку или сервис" aria-label="Поиск по умениям" value="${esc(searchText)}"></label><div class="toolbar-right"><select id="statusFilter" aria-label="Фильтр по состоянию"><option value="">Все состояния</option>${Object.entries(data.statuses).map(([k,v])=>`<option value="${k}" ${filterStatus===k?'selected':''}>${esc(v.label)}</option>`).join('')}</select><button class="text-button" data-action="legend">О состояниях</button></div></div><div class="tabs" role="group" aria-label="Категории умений">${data.categories.map(c=>`<button class="tab" data-action="category" data-category="${esc(c)}" aria-pressed="${category===c}">${esc(c)}</button>`).join('')}</div><div id="skillResults">${skillRows()}</div><div class="sr-only" id="filterResultStatus" role="status" aria-live="polite"></div></section>`;
  }
  function renderOverview() {
    return heading('София под контролем','Состояние колонки и домашнего сервера, настройки и доступные действия.','МОЙ GOBOT',button('Все умения','go','data-page="skills"'))+
      `<div class="metrics">${metric('Колонка',phaseName(),'По состоянию голосового сервера','speaker',true)}${metric('Режим',modeName(session().input_mode || device().mode),'Выбранный режим следующего вопроса','wave',true)}${metric('Погода',weatherState(),'Проверка источника — отдельное действие','weather',true)}${metric('Сервер',snapshot&&!problem?'Доступен':'Проверяем','Приватная панель PLAN','server',true)}</div>`+
      `<div class="two-col"><div class="stack">${panel('Ваше устройство','Управление именно колонкой, а не микрофоном этого браузера',`<div class="hero-device"><div class="large-face" aria-hidden="true"><i></i><i></i></div><div><h2>София</h2><p>Колонка Spotpear</p>${chip(phaseName(),ready()?'green':'amber')}</div></div><div class="section-actions">${button('Разговор и голос','go','data-page="voice"')}${button('Настройки устройства','go','data-page="devices"')}</div>`)}${panel('Домашнее место','Город для вопроса без уточнения места',`<div class="city-current">${icon('pin')}<div><strong>${esc(saved?.location_name || 'Не получено')}</strong><p>${esc(saved?.provider==='open_meteo'?'Open-Meteo':'Погодный источник не получен')}</p></div></div><div class="section-actions">${button('Настроить дом и погоду','go','data-page="home"')}</div>`)}</div><div class="stack">${panel('Что можно изменить сейчас','Проверенные действия на существующем сервере',`<ul class="check-list"><li>${icon('pin')}<span>Выбрать домашний город и проверить погодный источник.</span></li><li>${icon('weather')}<span>Включить или выключить погоду для сохранённого места.</span></li><li>${icon('wave')}<span>Выбрать разговорный режим, остановить ответ и управлять микрофоном.</span></li><li>${icon('history')}<span>Посмотреть реальные изменения и их время.</span></li></ul>`)}${panel('Постоянная доступность','Без тестовых двухчасовых окон',`<p>Эта панель не вводит сроков тестирования или новых ограничений расходов. Действующие допуски колонки и учёт операций сохраняются.</p><div class="section-actions">${button('Расходы и квоты','go','data-page="costs"')}</div>`)}</div></div>`;
  }
  function proofCard(proof=weatherProof()) {
    if(!proof)return `<div class="weather-picture">${icon('weather')}<div><strong>Источник ещё не проверен здесь</strong><p>Проверка запрашивает погоду с PLAN и не вызывает голосовую модель.</p></div></div>`;
    if(proof.verified!==true)return `<div class="source-proof source-failed"><strong>Последняя проверка не прошла</strong><p>${esc(humanError({code:proof.reason_code}))}</p><dl>${row('Когда',esc(dateTime(proof.checked_at)))}${row('Источник','Open-Meteo')}</dl></div>`;
    return `<div class="source-proof"><strong>${proofFresh(proof)?'Источник вернул проверенные данные':'Предыдущая проверка устарела'}</strong><p>${esc(draftCandidate?'Проверено выбранное новое место. Оно ещё не сохранено.':'Проверено сохранённое домашнее место.')}</p><dl>${row('Проверено',esc(dateTime(proof.checked_at)))}${row('Длительность',Number.isFinite(proof.duration_ms)?esc(Math.round(proof.duration_ms))+' мс':'Не измерено')}${row('Возраст данных',Number.isFinite(proof.data_age_seconds)?esc(Math.round(proof.data_age_seconds))+' с':'Не получен')}${row('Источник','Open-Meteo')}</dl></div>`;
  }
  function renderHome() {
    const verifyLabel=draftCandidate?'Проверить выбранный город':'Проверить погодный источник';
    const needProof=draftEnabled===true&&saved?.enabled===false&&!proofFresh(draftProof);
    return heading('Дом и погода','Сохранённое домашнее место и погодный источник для этой колонки.','НАСТРОЙКИ ДОМА')+
      (needProof?callout('Перед включением проверьте источник','Погода включится после проверки сохранённого места и подтверждения изменений.',button('Проверить источник','verify-weather',canEdit()?'':'disabled'),'','weather'):'')+
      `<div class="two-col"><div class="stack">${panel('Домашнее место','Используется, когда в вопросе не назван другой город',fields(['home.city']))}${panel('Погодный сервис','Сначала проверка, затем сохранение',fields(['weather.enabled','weather.provider'])+note('Новый домашний город меняется только после поиска, выбора и проверки источника. Сбой проверки оставляет действующие настройки прежними.'))}${panel('Единицы и часы','Дополнительные предпочтения',fields(['weather.temperature','weather.wind','home.timezone','home.clockFormat']))}</div><div class="stack">${panel('Проверка источника','Результат не является проверкой голосового ответа на колонке',proofCard()+`<div class="section-actions">${button(verifyLabel,'verify-weather',canEdit()&&(saved?.location_name||draftCandidate)?'':'disabled')}</div>`)}${panel('Как применяется изменение','Понятное подтверждение результата',`<p>${esc(applicationText())}</p><dl>${row('Где сохраняется','Домашний сервер PLAN')}${row('Для какого устройства','Эта колонка Spotpear')}${row('Подтверждение голоса','Отдельная проверка на колонке')}</dl>`)}${panel('Возможности погодного адаптера','По существующей реализации',`<dl>${row('Сейчас','Температура, осадки, ветер')}${row('Дневной прогноз','До 16 дней')}${row('Уточнения','«А завтра?» · «А ветер?»')}${row('Weather.com',chip('Адаптер не подключён'))}${row('Другой город в вопросе','Не меняет домашнее место')}</dl>`)}</div></div>`;
  }
  function voiceControls() {
    const s=session(),active=!!s.session_id||!!s.id||typeof s.state==='string';
    const disabled=controlBusy||!!problem||!active?'disabled':'';
    const idle=['ready','idle','blocked','muted','closed','disconnected'].includes(s.state);
    const modesDisabled=disabled||!idle?'disabled':'';
    return `<div class="mode-grid">${[['fast','Быстрый разговор','wave','Короткий вопрос, ответ и продолжение беседы.'],['expert','Эксперт','spark','Сложная задача выбранному CLI-эксперту и ответ голосом marin.']].map(([mode,label,i,desc])=>`<article class="mode-card ${s.input_mode===mode?'selected':''}">${icon(i)}<h3>${label}</h3><p>${desc}</p><div class="mode-meta">${esc(mode==='fast'?(s.model || 'Модель не получена'):(s.selected_expert?.model || 'Профиль не получен'))}</div>${button(s.input_mode===mode?'Выбран':'Выбрать режим','mode',`data-mode="${mode}" ${modesDisabled} aria-pressed="${s.input_mode===mode}"`,s.input_mode===mode?'subtle':'')}</article>`).join('')}</div><div class="section-actions">${button('Остановить ответ','stop',disabled,'danger')}${button(s.muted===true?'Включить микрофон':'Выключить микрофон','mute',disabled)}</div>${note('Выбор режима сам по себе не задаёт вопрос и не запускает экспертное задание. При активной реплике сначала дождитесь ответа или остановите его.')}`;
  }
  function renderVoice() {
    const expert=session().selected_expert;
    return heading('Разговор и голос','Управление текущей колонкой. Голос marin остаётся единым.','ГОЛОСОВОЕ ОБЩЕНИЕ')+
      panel('Режим следующего обращения',`Состояние: ${phaseName()}`,voiceControls())+
      `<div class="two-col section-gap"><div class="stack">${panel('Выбранный эксперт','Сведения из текущего голосового сеанса',`<dl>${row('Программа',esc(expert?.provider || 'Не получена'))}${row('Модель',esc(expert?.model || 'Не получена'))}${row('Профиль',esc(expert?.profile || 'Не получен'))}${row('Остаток внешней квоты','Не предоставлен провайдером')}</dl>`+fields(['expert.confirm']))}${panel('Предпочтения ответа','Управление пока не подключено',fields(['voice.language','voice.responseLength','expert.speechLength']))}</div><div class="stack">${panel('Единый голос','Правило текущего голосового маршрута',`<dl>${row('Голос',esc(device().voice || session().voice || 'marin — голос текущего маршрута'))}${row('Клип ожидания','marin')}${row('Диктор эксперта','marin')}</dl>`)}${panel('Продолжение и остановка','Ожидаемое поведение проверяется на колонке',`<ul class="list-spacing"><li>После одиночного «София» колонка ждёт вопрос.</li><li>После ответа можно задать уточнение.</li><li>Имя или касание во время ответа останавливают воспроизведение.</li><li>Контекст ответа подтверждается после окончания воспроизведения.</li></ul><div class="section-actions">${button('Пробуждение и касание','skill','data-id="interrupt"')}</div>`)}${panel('Подробные параметры','Действующая конфигурация остаётся под контролем сервера',fields(['conversation.followup','conversation.followupSeconds','expert.fallback']))}</div></div>`;
  }
  function connectionCard(name,description,i,state,body) {
    return `<section class="panel connection-card"><div class="card-title-row"><div class="connection-icon">${icon(i)}</div><div><h2>${esc(name)}</h2><p>${esc(description)}</p></div>${state}</div><div class="panel-body">${body}</div></section>`;
  }
  function renderConnections() {
    const s=session(),ex=s.selected_expert;
    return heading('Серверы и сервисы','Назначение каждого подключения и подтверждённое состояние.','ПОДКЛЮЧЕНИЯ')+
      `<div class="connection-grid">${connectionCard('Домашний сервер PLAN','Настройки, разговор и инструменты','server',chip(snapshot&&!problem?'Отвечает':'Не подтверждён',snapshot&&!problem?'green':'amber'),`<dl>${row('Адрес панели',esc(location.host))}${row('Проверено',esc(dateTime(snapshot?.observed_at || lastLoaded || null)))}${row('Доступ','Локально и через приватный Tailscale')}</dl>`)}${connectionCard('Колонка Spotpear','Передаёт вопрос и воспроизводит ответ','speaker',chip(phaseName(),ready()?'green':'amber'),`<dl>${row('Протокол',deviceConnected()?'Подтверждён сервером':'Не подтверждён')}${row('Голосовой сеанс',cloudReady()?'Конфигурация подтверждена':'Не подтверждён')}${row('Прослушивание',s.muted===true?'Микрофон выключен':s.muted===false?'Микрофон разрешён':'Не получено')}</dl>`)}${connectionCard('Быстрый разговор','OpenAI Realtime','wave',chip(cloudReady()?'Конфигурация подтверждена':'Нужна проверка',cloudReady()?'green':'amber'),`<dl>${row('Модель',esc(s.model || 'Не получена'))}${row('Допуск к ответу',s.generation_allowed===true?'Есть':s.generation_allowed===false?'Закрыт':'Не получен')}${row('Голос','marin')}</dl>`)}${connectionCard('Эксперт','Задача только после явной просьбы','spark',chip(ex?'Профиль выбран':'Не получен',ex?'blue':'gray'),`<dl>${row('Программа',esc(ex?.provider || 'Не получена'))}${row('Модель',esc(ex?.model || 'Не получена'))}${row('Квота','Остаток не получен')}</dl>`)}${connectionCard('Погода','Open-Meteo','weather',chip(weatherState(),!problem&&proofFresh(currentProof)&&!draftCandidate?'green':'amber'),`<dl>${row('Домашний город',esc(saved?.location_name || 'Не получен'))}${row('Проверка источника',esc(dateTime(currentProof?.checked_at)))}</dl><div class="section-actions">${button('Настроить','go','data-page="home"')}</div>`)}${connectionCard('Другие подключения','Поиск, музыка, календарь и умный дом','link',chip('Нужны интеграции'),`<p>Для каждого будущего сервиса в каталоге указаны назначение и необходимые настройки.</p><div class="section-actions">${button('Посмотреть неподключённые','missing-skills')}</div>`)}</div>`;
  }
  function renderDevices() {
    return heading('Устройства','Настройки и состояние выбранной физической колонки.','УСТРОЙСТВА ДОМА')+
      `<div class="two-col"><div class="stack">${panel('София · Spotpear','Текущий серверный профиль',`<div class="hero-device"><div class="large-face" aria-hidden="true"><i></i><i></i></div><div><h2>Ваша колонка</h2><p>${esc(phaseName())}</p>${chip('Выбрана','blue')}</div></div><dl>${row('Основа пробуждения',esc(runtime().wake_baseline || 'Не получена'))}${row('Версия прошивки',esc(device().firmware_version || 'Не передана в текущем API'))}${row('Подтверждение протокола',deviceConnected()?'Есть':'Не получено')}</dl><div class="section-actions">${button('Разговор и микрофон','go','data-page="voice"')}</div>`)}${panel('Громкость и экран','Эти параметры пока не подключены к управлению текущей прошивкой',fields(['device.volume','device.brightness','device.nightDisplay']))}</div><div class="stack">${panel('Название и оформление','Будущие настройки устройства',fields(['device.name','device.room','display.face','display.reduceMotion']))}${panel('Браузер — отдельное устройство','Панель не превращает этот браузер в микрофон колонки',`<p>Для голосового разговора в браузере используется существующая отдельная привязка. Эта страница только управляет выбранной колонкой.</p><div class="section-actions"><a class="button" href="/sophia">Открыть разговорную панель</a></div>`)}</div></div>`;
  }
  function renderPrivacy() {
    return heading('Люди и память','Права управления отделены от личности собеседника и личной памяти.','ДОСТУП И ДАННЫЕ')+
      `<div class="two-col"><div class="stack">${panel('Доступ к настройкам','Проверяется сервером для этой панели',`<ul class="service-list"><li><div><strong>Владелец панели</strong><small>Локальный доступ PLAN или разрешённая учётная запись Tailscale</small></div>${chip(snapshot&&!problem?'Доступ подтверждён':'Не подтверждён',snapshot&&!problem?'green':'amber')}</li><li><div><strong>Собеседник колонки</strong><small>Голос не даёт прав владельца панели</small></div>${chip('Отдельная проверка','blue')}</li><li><div><strong>Личный архив</strong><small>На этой странице не загружается</small></div>${chip('Нет доступа')}</li></ul>`)}${panel('Память разговора','Краткий контекст и личная память — разные механизмы',`<p>Ответ учитывается как услышанный после подтверждения окончания воспроизведения. Долговременная личная память требует отдельного подтверждения личности и согласия.</p>`+fields(['privacy.memory']))}</div><div class="stack">${panel('Текстовый журнал','Панель не извлекает домашние реплики',fields(['privacy.debug','privacy.retention']))}${panel('Что хранится в панели','Личные данные остаются в существующей системе',`<ul class="check-list"><li>${icon('server')}<span>Настройки сохраняются на PLAN в профиле этой колонки.</span></li><li>${icon('lock')}<span>Ключи сервисов не возвращаются в браузер.</span></li><li>${icon('mic')}<span>Панель не запрашивает микрофон и не записывает звук.</span></li><li>${icon('history')}<span>В истории видны изменения настроек без текстов разговоров.</span></li></ul>`)}</div></div>`;
  }
  function renderCosts() {
    const budget=runtime().brain?.status?.budget || null;
    const usage=snapshot?.usage || runtime().usage || (budget?{fast_responses:budget.response_attempts,fast_sessions:budget.sessions_reserved,estimated_usd:budget.reported_response_estimate_usd}:null);
    const count=(key)=>typeof usage?.[key]==='number'?String(usage[key]):'Не получено';
    return heading('Расходы и квоты','Учёт использования сохраняется на сервере. Неизвестные суммы не подменяются нулями.','ПОСТОЯННЫЙ ТЕРМИНАЛ')+
      callout('Тестируйте в удобное время','Эта панель не создаёт двухчасовых окон, денежных или общих количественных ограничений. Состояние внешних квот провайдеров проверяется отдельно.','','information','clock')+
      `<div class="metrics">${metric('Попытки ответа',count('fast_responses'),'Учтённые попытки ответа · данные сервера','wave',true)}${metric('Запуски разговора',count('fast_sessions'),'Учтённые старты · исторические записи сохранены','history',true)}${metric('Задачи эксперту',count('expert_jobs'),'Отдельный учёт CLI','spark',true)}${metric('Стоимость',typeof usage?.estimated_usd==='number'?'$'+usage.estimated_usd.toFixed(4):'Не получена','Оценка отдельно от счёта провайдера','wallet',true)}</div>`+
      `<div class="two-col"><div class="stack">${panel('Источники расходов','Существующие журналы не изменяются этой страницей',`<ul class="service-list"><li><div><strong>Быстрый разговор</strong><small>OpenAI Realtime</small></div>${chip('Учёт на PLAN','blue')}</li><li><div><strong>Распознавание и озвучивание</strong><small>Отдельные операции экспертного маршрута</small></div>${chip('Учёт на PLAN','blue')}</li><li><div><strong>Эксперт CLI</strong><small>Внешняя квота подписки</small></div>${chip('Остаток неизвестен')}</li></ul>`)}${panel('Уведомления','Управление уведомлениями пока не подключено',fields(['costs.notify']))}</div><div class="stack">${panel('Когда числа появятся','Без выдуманных показателей',`<p>Панель показывает счётчики только там, где сервер отдаёт подтверждённое значение для этой колонки. «Не получено» означает отсутствие данных в этом API, а не отсутствие расхода.</p>`)}${panel('Если провайдер недоступен','Автоматической платной замены из панели нет',`<p>Выбранный профиль эксперта виден в подключениях. Эта страница не запускает задачи для проверки квоты и не переключает платную модель автоматически.</p><div class="section-actions">${button('Открыть подключения','go','data-page="connections"')}</div>`)}</div></div>`;
  }
  function renderDiagnostics() {
    const d=device(),s=session();
    return heading('Диагностика','Проверка источника, серверные состояния и честные границы измерений.','ПОНЯТЬ ПРИЧИНУ СБОЯ',button('Обновить состояние','refresh',busy||loading?'disabled':''))+
      `<div class="two-col"><div class="stack">${panel('Связь и разговор','Последний ответ текущего сервера',`<dl>${row('Сервер PLAN',snapshot&&!problem?'Отвечает':'Нет свежего ответа')}${row('Колонка',esc(phaseName()))}${row('Режим',esc(modeName(s.input_mode || d.mode)))}${row('Голосовой сервис',cloudReady()?'Конфигурация подтверждена':'Не подтверждён')}${row('Последняя причина',esc(d.last_error || s.last_error || 'Не передана'))}${row('Проверено',esc(dateTime(snapshot?.observed_at || lastLoaded || null)))}</dl>`)}${panel('Погода','Отдельная проверка с домашнего сервера',proofCard(currentProof)+`<div class="section-actions">${button('Дом и погода','go','data-page="home"')}</div>`)}${panel('Применение настроек','Серверное сохранение и голосовая проверка разделены',`<p>${esc(applicationText())}</p>`)}</div><div class="stack">${panel('Путь одной реплики','Этот API пока не передаёт полный набор задержек',`<div class="diagnostic-steps">${[['Пробуждение','wake'],['Вопрос окончен','endpoint_decided'],['Первый пакет','first_audio_packet'],['Начало звука','playback_started']].map(([label,key])=>`<div class="diagnostic-step"><span>${label}</span><strong>Не получено</strong><small>${key}</small></div>`).join('')}</div><dl>${row('Окончание воспроизведения','Не сопоставлено с конкретной репликой')}${row('Просадки очереди','Не измерены для этой реплики')}${row('DMA underrun','Отдельного счётчика в API нет')}</dl>`+note('Длительность погодного запроса не является задержкой от пробуждения до голоса.'))}${panel('Безопасный отчёт','Без ключей, города, координат и домашних реплик',`<p>Можно скачать текущие технические состояния и результат проверки источника. Полная конфигурация и личная история в отчёт не входят.</p><div class="section-actions">${button('Скачать отчёт','export-report',snapshot?'':'disabled')}</div>`)}</div></div>`;
  }
  function changeValue(value) {
    if(typeof value==='boolean')return value?'Включено':'Выключено';
    if(value==null)return 'Не задано';
    if(typeof value==='object')return [typeof value.enabled==='boolean'?(value.enabled?'Погода включена':'Погода выключена'):'',value.location_name || '',value.provider || ''].filter(Boolean).join(' · ');
    return String(value);
  }
  function renderHistory() {
    return heading('Изменения','Записи изменений настроек этой колонки, сохранённые на PLAN.','ИСТОРИЯ СЕРВЕРА',button('Обновить','refresh',busy||loading?'disabled':''))+
      (hasChanges()?callout('Есть несохранённые изменения','Черновик находится только на этой странице. Перед применением можно сравнить старые и новые значения.',button('Проверить изменения','review',canEdit()?'':'disabled'),'information','settings'):'')+
      `<section class="panel"><div class="panel-head"><div><h2>История настроек</h2><p>Запись подтверждает сохранение на сервере. Голосовой ответ проверяется отдельно.</p></div>${chip('PLAN','blue')}</div>${changesLog.length?`<ol class="history-list">${changesLog.map(h=>`<li><div class="history-entry-head"><div><strong>Настройки сохранены на сервере</strong><small>${esc(dateTime(h.at))}</small></div>${chip('Сохранено','green')}</div><ul class="history-changes"><li>Было: ${esc(changeValue(h.before?.weather || h.before))}</li><li>Стало: ${esc(changeValue(h.after?.weather || h.after))}</li></ul></li>`).join('')}</ol>`:`<div class="empty-state">${icon('history')}<h2>${snapshot?'Пока нет изменений из этой панели':'История ещё не загружена'}</h2><p>После сохранения домашнего места или настройки погоды здесь появится запись.</p>${button('Дом и погода','go','data-page="home"')}</div>`}</section>`;
  }
  const views={overview:renderOverview,skills:renderSkills,home:renderHome,voice:renderVoice,connections:renderConnections,devices:renderDevices,privacy:renderPrivacy,costs:renderCosts,diagnostics:renderDiagnostics,history:renderHistory};
  function render() {
    const focused=document.activeElement;
    const restore=focused && (focused.closest('#main') || focused.closest('#navigation'))?{id:focused.id,field:focused.dataset.field,action:focused.dataset.action,skill:focused.dataset.id,href:focused.getAttribute('href'),selection:typeof focused.selectionStart==='number'?[focused.selectionStart,focused.selectionEnd]:null}:null;
    const path=location.hash.replace(/^#\//,'').split('?')[0];page=views[path]?path:'skills';
    renderNavigation();$('main').innerHTML=editingNotices()+views[page]();updateHeader();
    document.title=$('breadcrumb').textContent+' · София · GoBot';
    if(restore){const next=(restore.id?$(restore.id):null)||[...document.querySelectorAll('#main input,#main button,#main select,#navigation a')].find(e=>restore.field?e.dataset.field===restore.field:restore.href?e.getAttribute('href')===restore.href:restore.action?e.dataset.action===restore.action&&e.dataset.id===restore.skill:false);if(next&&!next.disabled){next.focus({preventScroll:true});if(restore.selection&&typeof next.setSelectionRange==='function'){try{next.setSelectionRange(...restore.selection);}catch{}}}}
  }
  const narrowScreen=window.matchMedia('(max-width:760px)');
  let dialogSequence=0,cityRequest=0,controlBusy=false;
  function closeMobile(returnFocus=false) {
    $('sidebar').classList.remove('open');$('sidebar').inert=narrowScreen.matches;
    document.querySelector('.workspace').inert=false;$('mobileBackdrop').hidden=true;
    $('menuButton').setAttribute('aria-expanded','false');if(returnFocus)$('menuButton').focus();
  }
  function openMobile() {
    $('sidebar').inert=false;$('sidebar').classList.add('open');document.querySelector('.workspace').inert=true;
    $('mobileBackdrop').hidden=false;$('menuButton').setAttribute('aria-expanded','true');$('mobileNavClose').focus();
  }
  narrowScreen.addEventListener('change',()=>closeMobile());
  function dialogShell(title,subtitle,body,footer='',label='НАСТРОЙКИ УМЕНИЯ') {
    return `<header class="dialog-header"><div><div class="eyebrow">${esc(label)}</div><h2 id="dialogTitle">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button class="icon-button" data-action="close-dialog" aria-label="Закрыть панель">${icon('cross')}</button></header>${body}<footer class="dialog-footer"><p>Изменения применяются после просмотра и сохранения на PLAN.</p>${footer||button('Готово','close-dialog')}</footer>`;
  }
  function showDialog(content) { dialogSequence++;$('dialogContent').innerHTML=content;if(!$('settingsDialog').open)$('settingsDialog').showModal(); }
  function closeDialog() { dialogSequence++;cityRequest++;$('settingsDialog').close(); }
  function openSkill(id,tab='settings') {
    const s=data.skills.find(x=>x.id===id);if(!s)return;openedSkill=id;skillTab=tab;
    let content='';
    if(tab==='overview')content=badge(skillState(s))+`<p>${esc(s.detail)}</p><div class="quote">${esc(s.example)}</div><dl>${row('Сервис',esc(s.service))}${row('Разговорный режим',esc(s.mode))}${row('Устройство','Spotpear')}</dl>`;
    if(tab==='settings')content=badge(skillState(s))+`<p class="skill-intro">${esc(s.detail)}</p>`+(s.fields.length?fields(s.fields):note('Для этой возможности нет настройки, которую сейчас можно изменить из панели.'))+(s.page?`<div class="section-actions">${button('Открыть раздел настроек','go',`data-page="${s.page}"`)}</div>`:'');
    if(tab==='checks')content=badge(skillState(s))+`<p>${esc(s.detail)}</p><dl>${row('Сервис',esc(s.service))}${row('Состояние сервера',esc(phaseName()))}${row('Последнее чтение',esc(dateTime(snapshot?.observed_at || lastLoaded || null)))}${row('Полная голосовая проверка','Не выполняется открытием этой панели')}</dl><details class="details"><summary>Техническое основание</summary><p><code>${esc(s.evidence)}</code></p><p>Описание возможности и свежий результат работы сервиса — разные сведения.</p></details>`+(s.id==='weather'?`<div class="section-actions">${button('Проверка погоды','go','data-page="home"')}</div>`:'');
    const tabs=`<div class="dialog-tabs" role="tablist" aria-label="Сведения об умении">${[['overview','Об умении'],['settings','Настройки'],['checks','Проверка']].map(([key,label])=>`<button class="dialog-tab" role="tab" id="skill-tab-${key}" aria-controls="skill-panel" aria-selected="${key===tab}" tabindex="${key===tab?0:-1}" data-action="skill-tab" data-tab="${key}">${label}</button>`).join('')}</div><div class="dialog-body" id="skill-panel" role="tabpanel" aria-labelledby="skill-tab-${tab}">${content}</div>`;
    showDialog(dialogShell(s.name,s.description,tabs));
  }
  function legend() {
    showDialog(dialogShell('Что означают состояния','Подключение, настройка и успешный голосовой ответ — разные подтверждения.',`<div class="dialog-body"><ul class="service-list">${Object.entries(data.statuses).map(([key,s])=>`<li><div>${badge(key)}<small>${esc(s.help)}</small></div></li>`).join('')}</ul></div>`));
  }
  function about() {
    showDialog(dialogShell('Настройки Софии на PLAN','Рабочая приватная панель для выбранной колонки.',`<div class="dialog-body"><p>Домашний город и включение погоды сохраняются в существующем профиле колонки. Режим, остановка ответа и микрофон управляются через существующий голосовой сервер.</p><p>Поля с отметкой «Пока не редактируется» показывают границы интеграции. Эта панель не принимает ключи сервисов и не запускает модель для проверки связи.</p><dl>${row('Доступ','На PLAN и через приватный Tailscale')}${row('Время на этой странице','Бразилиа · BRT (UTC−3)')}${row('Обновление состояния','Примерно каждые 15 секунд, пока вкладка видима')}${row('Черновик настроек','Только в оперативной памяти этой страницы')}</dl></div>`));
  }
  function openCity() {
    if(!canEdit())return;selectedCity=null;candidates=[];
    showDialog(dialogShell('Выбрать домашний город','Найдите точное место, затем проверьте погоду перед сохранением.',`<div class="dialog-body"><form id="citySearchForm"><div class="field"><label class="field-label" for="citySearch">Город или населённый пункт</label><input id="citySearch" type="search" minlength="2" maxlength="120" placeholder="Город, регион или страна" autocomplete="off" aria-describedby="citySearchHint"><span class="field-hint" id="citySearchHint">Поиск выполняется через погодный сервис с сервера PLAN.</span></div><button class="button" id="citySearchButton" type="submit" disabled>Найти город</button></form><div id="cityMessage" class="action-message" role="status" aria-live="polite"></div><ul class="city-results" id="cityResults"></ul><div id="citySelection" aria-live="polite"></div>${note('После проверки выбранный город добавится в изменения. Действующий домашний город заменится только после нажатия «Сохранить на PLAN».')}</div>`,'','ДОМ И ПОГОДА'));
    $('citySearch').focus();
  }
  async function searchCity() {
    const query=$('citySearch')?.value.trim();if(!query||query.length<2||busy)return;
    const seq=++cityRequest,dialog=dialogSequence;
    busy=true;updateHeader();selectedCity=null;candidates=[];$('cityResults').innerHTML='';$('citySelection').innerHTML='';$('cityMessage').textContent='Ищем подходящие места…';$('citySearchButton').disabled=true;
    try {
      const result=await api('/weather/locations',{query});
      if(seq!==cityRequest||dialog!==dialogSequence||!$('settingsDialog').open)return;
      candidates=Array.isArray(result.candidates)?result.candidates:[];
      $('cityResults').innerHTML=candidates.map(c=>`<li><button class="city-choice" data-action="city-select" data-id="${esc(c.id)}">${icon('pin')}<div><strong>${esc(c.location_name)}</strong><span>Выбрать это место</span></div></button></li>`).join('');
      $('cityMessage').textContent=candidates.length?'Выберите точное место из результатов.':'Подходящих мест не найдено. Уточните город, регион или страну.';
    } catch(error) {if(seq===cityRequest&&dialog===dialogSequence&&$('cityMessage'))$('cityMessage').textContent=humanError(error);}
    finally {busy=false;if($('citySearchButton'))$('citySearchButton').disabled=!$('citySearch')?.value.trim()||$('citySearch').value.trim().length<2;updateHeader();}
  }
  function selectCity(id) {
    if(busy)return;selectedCity=candidates.find(c=>c.id===id);if(!selectedCity)return;
    $('citySelection').innerHTML=`<div class="city-selection"><strong>${esc(selectedCity.location_name)}</strong><p>Вы выбрали этот город для колонки Spotpear. После сохранения погода будет включена для этого места.</p>${button('Проверить источник и выбрать город','verify-city','','primary')}<p class="field-hint">Проверка не меняет действующий домашний город.</p></div>`;
    $('citySelection').scrollIntoView({block:'nearest'});
  }
  async function verifyWeather(candidate=null) {
    if(busy||!saved||problem||conflict||pendingApply)return;
    const desired=candidate||draftCandidate;
    if(desired && !desired.id)return;
    const seq=dialogSequence;busy=true;actionError='';
    draftProof=null;if(!desired)currentProof=null;updateHeader();
    const control=document.querySelector('[data-action="verify-city"]');if(control){control.disabled=true;control.textContent='Проверяем источник…';}
    try {
      const result=await api('/weather/verify',desired?{candidate_id:desired.id}:{});
      if(result.verified!==true){const error=new Error('source_unverified');error.code='unavailable';throw error;}
      if(desired && result.candidate_id!==desired.id){const error=new Error('candidate_changed');error.code='unavailable';throw error;}
      if(candidate) {
        if(seq!==dialogSequence||!$('settingsDialog').open)return;
        draftCandidate={id:candidate.id,location_name:candidate.location_name};draftEnabled=true;draftProof=result;closeDialog();
      } else {draftProof=result;if(!draftCandidate)currentProof=result;}
      render();toast(candidate?'Источник проверен. Просмотрите изменения и сохраните новый домашний город.':'Погодный источник ответил. Проверка не запускает голосовой ответ.');
    } catch(error) {
      actionError=humanError(error);
      if(error.status===409)await readConflict();
      if(!desired)currentProof={verified:false,checked_at:Date.now(),reason_code:error.code};
      if(candidate&&seq===dialogSequence&&$('cityMessage')){$('cityMessage').textContent=actionError;if(control){control.disabled=false;control.textContent='Проверить источник и выбрать город';}}
      else toast(actionError);
    } finally {busy=false;updateHeader();if(!$('settingsDialog').open)render();}
    if(reviewAfterVerify&&proofFresh(draftProof)){reviewAfterVerify=false;await openReview();}
  }
  function patchBody() {
    const weather={};
    if(draftEnabled!==saved.enabled)weather.enabled=draftEnabled;
    if(draftCandidate){weather.candidate_id=draftCandidate.id;weather.enabled=draftEnabled;}
    if((draftCandidate || draftEnabled===true&&saved.enabled===false) && draftProof?.verification_id)weather.verification_id=draftProof.verification_id;
    return {expected_revision:revision,patch:{weather}};
  }
  function reviewDiff() {
    const changes=[];
    if(draftEnabled!==saved.enabled)changes.push({field:'Погода для домашнего места',before:saved.enabled,after:draftEnabled});
    if(draftCandidate)changes.push({field:'Домашний город',before:saved.location_name,after:draftCandidate.location_name});
    return changes;
  }
  function reviewHTML(diff,footer,lead='Проверьте значения перед сохранением.') {
    return `<header class="dialog-header"><div><div class="eyebrow">КОЛОНКА SPOTPEAR</div><h2 id="reviewTitle">Проверить изменения</h2><p>${esc(lead)}</p></div><button class="icon-button" data-action="close-review" aria-label="Закрыть проверку">${icon('cross')}</button></header><div class="dialog-body"><div class="review-list">${diff.map(c=>`<div class="review-row"><strong>${esc(c.field)}</strong><div class="review-values"><span>${esc(changeValue(c.before))}</span>${icon('chevron')}<strong>${esc(changeValue(c.after))}</strong></div></div>`).join('')}</div><p class="note">${esc(applicationText())}</p><div class="action-message" id="reviewError" role="alert">${esc(actionError)}</div></div><footer class="dialog-footer"><p>Будут изменены настройки этой колонки на PLAN.</p>${footer}</footer>`;
  }
  async function readConflict() {
    try { acceptSnapshot(await api('/snapshot')); } catch {}
    conflict=true;
  }
  async function openReview() {
    if(!hasChanges()||!canEdit())return;
    actionError='';
    const needsProof=!!draftCandidate || draftEnabled===true&&saved.enabled===false;
    if(needsProof&&!proofFresh(draftProof)){
      $('reviewContent').innerHTML=reviewHTML(reviewDiff(),button('Проверить источник','review-verify','','primary'),'Проверка источника нужна перед сохранением нового места или включением погоды.');
      if(!$('reviewDialog').open)$('reviewDialog').showModal();return;
    }
    busy=true;updateHeader();
    try {
      const result=await api('/settings/validate',patchBody());
      if(result.ok!==true){const error=new Error('validation_failed');error.code='invalid_setting';throw error;}
      $('reviewContent').innerHTML=reviewHTML(reviewDiff(),button('Отменить изменения','discard','','subtle')+button('Сохранить на PLAN','save-settings','','primary'));
      if(!$('reviewDialog').open)$('reviewDialog').showModal();
    } catch(error) {actionError=humanError(error);if(error.status===409)await readConflict();toast(actionError);render();}
    finally {busy=false;updateHeader();if(!$('reviewDialog').open&&!$('settingsDialog').open)render();}
  }
  function operationId() {
    if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=[...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  function mergeSavedResult(result) {
    const value=result.settings;
    if(value?.settings?.weather)acceptSnapshot({...snapshot,...value,changes:result.change?[result.change,...changesLog.filter(h=>h.id!==result.change.id)].slice(0,50):changesLog},{reset:true});
    else {const error=new Error('save_receipt_missing');error.code='request_timeout';throw error;}
  }
  async function saveSettings(retry=false) {
    if(busy||!saved||(!retry&&!hasChanges()))return;
    if(!retry){if(!canEdit())return;pendingApply={...patchBody(),operation_id:operationId()};}
    if(!pendingApply)return;
    busy=true;actionError='';updateHeader();
    document.querySelectorAll('#reviewContent button').forEach(b=>b.disabled=true);
    try {
      const result=await api('/settings/apply',pendingApply);
      if(result.ok!==true){const error=new Error('save_failed');error.code='unavailable';throw error;}
      mergeSavedResult(result);pendingApply=null;$('reviewDialog').close();closeDialog();render();toast(result.unchanged?'На сервере уже сохранены эти значения.':'Настройки сохранены на PLAN. '+applicationText());
    } catch(error) {
      actionError=humanError(error);
      if(error.status && error.status<500)pendingApply=null;
      if(error.status===409)await readConflict();
      if($('reviewError'))$('reviewError').textContent=actionError;
      document.querySelectorAll('#reviewContent button').forEach(b=>b.disabled=false);
      if(pendingApply){$('reviewDialog').close();render();toast('Ответ на сохранение не получен. Запрос не будет повторён автоматически. Нажмите «Проверить сохранение».');}
      else toast(actionError);
    } finally {busy=false;updateHeader();if(!$('reviewDialog').open&&!$('settingsDialog').open)render();}
  }
  async function resolveApply() {
    if(!pendingApply||busy)return;
    const operation=pendingApply;
    busy=true;updateHeader();
    try {
      const [historyResult,value]=await Promise.all([api('/changes'),api('/settings')]);
      const entries=Array.isArray(historyResult.changes)?historyResult.changes:[];
      const found=entries.find(h=>h.id===operation.operation_id||h.operation_id===operation.operation_id);
      if(found){acceptSnapshot({...snapshot,...value,changes:entries},{reset:true});pendingApply=null;render();toast('Сохранение подтверждено по истории операций на PLAN.');}
      else {
        acceptSnapshot({...snapshot,...value,changes:entries});
        showDialog(dialogShell('Проверить отправленное изменение','Сервер ещё не подтвердил эту операцию в истории.',`<div class="dialog-body"><p>Можно повторно запросить выполнение той же операции с тем же идентификатором. Сервер выполнит её не более одного раза. Значения нового изменения не отправляются.</p><div class="action-message" role="status">${esc(conflict?'На сервере обнаружена другая версия настроек. Повтор не перезапишет её.':'')}</div></div>`,button('Повторить ту же операцию','retry-apply','','primary'),'СОХРАНЕНИЕ НА PLAN'));
      }
    } catch(error){toast(humanError(error));}
    finally{busy=false;updateHeader();if(!$('reviewDialog').open&&!$('settingsDialog').open)render();}
  }
  function showConflict() {
    if(!latest||!saved)return;
    showDialog(dialogShell('На сервере появилась другая версия','Ваш черновик не перезаписывает чужое изменение.',`<div class="dialog-body"><dl>${row('Было открыто',esc(changeValue(saved)))}${row('Сейчас на сервере',latest.revision!==revision?esc(changeValue(latest.settings.weather)):'Новая версия ещё не прочитана')}${row('Ваш выбранный город',esc(draftCandidate?.location_name || saved.location_name))}${row('Погода в черновике',draftEnabled?'Включена':'Выключена')}</dl><p>Загрузите текущие значения и после этого выберите нужное изменение заново. Неотправленный черновик будет снят.</p></div>`,button('Загрузить текущие значения','discard','','primary'),'КОНФЛИКТ ВЕРСИЙ'));
  }
  async function discardDraft() {
    if(busy||pendingApply)return;
    if(conflict){await load({manual:true,reset:true});if(conflict||problem)return;}
    else if(latest)acceptSnapshot(latest,{reset:true});else{draftCandidate=null;draftProof=null;draftEnabled=saved?.enabled??null;}
    $('reviewDialog').close();closeDialog();render();toast('Черновик отменён. Показаны последние прочитанные настройки сервера.');
  }
  async function control(action,extra={}) {
    if(controlBusy||!snapshot||problem)return;
    controlBusy=true;
    try {
      await api('/control',{action,...extra});
      toast(action==='stop'?'Команда остановки принята сервером.':action==='mute'?'Команда микрофона принята сервером.':'Режим выбран на сервере.');
    } catch(error){toast(humanError(error));}
    finally {controlBusy=false;await load({manual:true});}
  }
  function exportReport() {
    if(!snapshot)return;
    const proof=currentProof;
    const report={kind:'sophia_admin_safe_status',generated_at:new Date().toISOString(),observed_at:snapshot.observed_at,server_reachable:!problem,
      device_protocol_confirmed:device().device_protocol_confirmed===true,voice_ready:session().ready===true,mode:session().input_mode || device().mode || null,
      phase:device().voice_phase || session().state || null,voice:device().voice || session().voice || null,
      weather:{enabled:saved?.enabled===true,provider:saved?.provider || null,location_configured:!!saved?.location_name,check:proof?{verified:proof.verified===true,checked_at:proof.checked_at,expires_at:proof.expires_at,duration_ms:proof.duration_ms,data_age_seconds:proof.data_age_seconds}:null},
      measured_voice_latency:null,dma_underrun_measurement:'not_available',contains_dialogue:false,contains_location:false};
    const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='sophia-admin-status.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);toast('Скачан отчёт без ключей, города, координат и реплик.');
  }
  async function onAction(event) {
    const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
    const action=el.dataset.action;
    if(action==='go'){closeDialog();navigate(el.dataset.page);}
    if(action==='refresh')await load({manual:true});
    if(action==='about')about();if(action==='legend')legend();
    if(action==='skill')openSkill(el.dataset.id);
    if(action==='skill-tab'){openSkill(openedSkill,el.dataset.tab);$('skill-tab-'+el.dataset.tab)?.focus();}
    if(action==='close-dialog')closeDialog();if(action==='close-review')$('reviewDialog').close();
    if(action==='category'){category=el.dataset.category;$('skillResults').innerHTML=skillRows();document.querySelectorAll('[data-action="category"]').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.category===category)));announceFilters();}
    if(action==='reset-filters'){category='Все умения';filterStatus='';searchText='';render();$('skillSearch')?.focus();}
    if(action==='missing-skills'){filterStatus='missing';category='Все умения';searchText='';if(page==='skills')render();else navigate('skills');}
    if(action==='choose-city')openCity();if(action==='city-select')selectCity(el.dataset.id);
    if(action==='verify-city'&&selectedCity)await verifyWeather(selectedCity);
    if(action==='verify-weather')await verifyWeather();
    if(action==='review')await openReview();
    if(action==='review-verify'){$('reviewDialog').close();reviewAfterVerify=true;await verifyWeather();}
    if(action==='save-settings')await saveSettings();
    if(action==='resolve-apply')await resolveApply();
    if(action==='retry-apply'){closeDialog();await saveSettings(true);}
    if(action==='discard')await discardDraft();if(action==='conflict')showConflict();
    if(action==='mode')await control('mode',{mode:el.dataset.mode});
    if(action==='mute')await control('mute',{muted:session().muted!==true});
    if(action==='stop')await control('stop');
    if(action==='export-report')exportReport();
  }
  function announceFilters(){if($('filterResultStatus'))$('filterResultStatus').textContent=`Найдено умений: ${filteredSkills().length}`;}
  document.addEventListener('click',event=>{onAction(event).catch(()=>toast('Не удалось выполнить действие. Обновите состояние и повторите.'));});
  document.addEventListener('submit',event=>{if(event.target.id==='citySearchForm'){event.preventDefault();searchCity();}});
  document.addEventListener('input',event=>{
    const el=event.target;
    if(el.id==='skillSearch'){searchText=el.value;$('skillResults').innerHTML=skillRows();announceFilters();}
    if(el.id==='citySearch'&&$('citySearchButton'))$('citySearchButton').disabled=busy||el.value.trim().length<2;
  });
  document.addEventListener('change',event=>{
    const el=event.target;if(el.id==='statusFilter'){filterStatus=el.value;$('skillResults').innerHTML=skillRows();announceFilters();}
    if(el.dataset.field==='weather.enabled'&&canEdit()){
      draftEnabled=el.checked;
      if(!draftEnabled&&draftCandidate){draftCandidate=null;draftProof=null;}
      updateHeader();if(!$('settingsDialog').open)render();
    }
  });
  document.addEventListener('keydown',event=>{
    if(event.target.matches('.dialog-tab')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      event.preventDefault();const tabs=['overview','settings','checks'];let i=tabs.indexOf(skillTab);i=event.key==='Home'?0:event.key==='End'?2:(i+(event.key==='ArrowRight'?1:2))%3;openSkill(openedSkill,tabs[i]);$('skill-tab-'+tabs[i]).focus();
    }
    if($('sidebar').classList.contains('open')){
      if(event.key==='Escape')closeMobile(true);
      if(event.key==='Tab'){
        const focusable=[...$('sidebar').querySelectorAll('button,a[href]')].filter(e=>e.offsetParent!==null),first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      }
    }
  });
  $('settingsDialog').addEventListener('cancel',()=>{dialogSequence++;cityRequest++;});
  $('reviewButton').addEventListener('click',()=>openReview());
  $('menuButton').addEventListener('click',openMobile);$('mobileNavClose').addEventListener('click',()=>closeMobile(true));$('mobileBackdrop').addEventListener('click',()=>closeMobile(true));
  $('sidebar').addEventListener('click',event=>{if(narrowScreen.matches&&event.target.closest('a')){closeMobile();$('main').focus({preventScroll:true});}});
  window.addEventListener('hashchange',()=>{closeMobile();render();window.scrollTo(0,0);$('main').focus({preventScroll:true});});
  window.addEventListener('beforeunload',event=>{if(hasChanges()||pendingApply){event.preventDefault();event.returnValue='';}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  render();closeMobile();load({manual:true});
  setInterval(()=>{if(!document.hidden&&!busy&&!loading&&!pendingApply)load();},15000);
})();
