"use strict";
const $ = id => document.getElementById(id);
let current = null, browserStatus = null, selected = 'spotpear', pending = 0, errorText = '';
const messages = {
  board_budget_inactive: 'Срок разрешения на разговор B истёк. София остаётся включённой; платный разговор заблокирован.',
  realtime_budget_or_consent_required: 'Нет действующего разрешения на платный разговор для этого источника. София работает локально; Stop, Mute и выбор режима доступны.',
  realtime_policy_disabled: 'Разговор пока не разрешён текущей политикой расходов.',
  realtime_budget_missing_or_expired: 'Для этого источника нет действующего разрешения на платный разговор.',
  realtime_session_budget_exhausted: 'Все разрешённые новые запуски использованы. Уже допущенный разговор можно продолжить, пока действует его лимит.',
  owner_realtime_daily_limit: 'Сегодня использованы разрешённые ответы. Новая генерация закрыта.',
  owner_api_estimate_limit: 'Достигнут текущий лимит оценки расходов. Новая генерация закрыта.',
  owner_test_not_authorized: 'Для этого источника нет действующего разрешения на расход.',
  voice_device_not_connected: 'Источник ещё не подключён к разговору.',
  mode_change_requires_idle: 'Дождитесь окончания реплики или нажмите «Остановить ответ».',
  microphone_source_change_requires_idle: 'Сменить микрофон можно после ответа или после Stop.',
  microphone_source_state_unavailable: 'Не удалось проверить состояние колонки. Смена источника пока недоступна.',
  brain_or_gateway_unavailable: 'Не удалось связаться с сервером. Состояние проверяется автоматически.',
  browser_binding_missing: 'У этого браузера нет существующей привязки к основному Brain. Допуск прежнего Browser Lab сюда не переносится.',
  browser_binding_unavailable: 'Существующую привязку браузера не удалось проверить.',
  browser_voice_status_unavailable: 'Не удалось проверить доступ браузера к разговору.',
  exact_authorized_client_required: 'Разрешение основного разговорного сервера выдано другому устройству. Для этого браузера разговор закрыт.',
  browser_admission_unavailable: 'Для этого браузера нет действующего допуска к разговору.',
  browser_expert_not_authorized: 'Для эксперта у этого браузера нет действующего допуска.',
  narrator_budget_unavailable: 'Для озвучивания ответа эксперта нет действующего допуска.',
  microphone_source_already_attached: 'Этот микрофон уже используется в другой вкладке. Закройте её разговор.',
  realtime_audio_session_already_active: 'Для этой привязки уже открыт другой разговор. Остановите его перед новым подключением.',
  browser_voice_connection_lost: 'Связь браузера прервалась. Для восстановления нажмите «Начать разговор»; платный запрос автоматически не повторяется.',
  browser_voice_transport_failed: 'Разговор браузера не удалось подключить. Проверьте доступ и повторите подключение кнопкой.',
  browser_microphone_requires_https: 'Для микрофона нужен доверенный HTTPS и браузер с AudioWorklet.',
  browser_microphone_ended: 'Браузер отключил микрофон. Подключите его и нажмите «Начать разговор».',
  browser_microphone_suspended: 'Браузер приостановил микрофон. Вернитесь на страницу и начните разговор кнопкой.',
  browser_audio_suspended: 'Браузер приостановил звук. Нажмите «Начать разговор», чтобы разрешить воспроизведение.',
  browser_microphone_queue_overflow: 'Передача звука задержалась. Ввод остановлен; повтор начнётся только по вашей команде.',
  browser_capture_queue_overflow: 'Браузер задержал обработку микрофона. Ввод остановлен, чтобы не накапливать звук. Начните вопрос кнопкой.',
  browser_playback_progress_timeout: 'Браузер не подтвердил воспроизведение звука. Передача ответа остановлена; восстановите звук и подключитесь кнопкой.',
  browser_output_queue_overflow: 'Воспроизведение отстало от потока. Ответ остановлен, чтобы не накапливать звук.',
  previous_provider_finalization_unconfirmed: 'Сначала нужно завершить учёт предыдущего соединения. Новый расход заблокирован.',
  conversation_busy: 'Сейчас идёт реплика. Дождитесь ответа или нажмите Stop.',
  logical_conversation_closed: 'Прежний разговор завершён. Для нового разговора нажмите кнопку ещё раз; доступ будет проверен заново.',
  openai_key_missing: 'На сервере не настроен ключ OpenAI. Голосовой разговор пока недоступен.',
  realtime_configuration_rejected: 'Облачный сервис не принял настройки разговора. Готовность не подтверждена.',
  realtime_settings_not_acknowledged: 'Подтверждение настроек от облачного сервиса не получено. Разговор не запущен.',
  realtime_transport_disconnected: 'Связь с голосовым сервисом прервалась. Новая реплика автоматически не отправляется.',
  realtime_network_error: 'Сервер не смог соединиться с голосовым сервисом. Повторите подключение кнопкой.',
  expert_transcription_budget_unavailable: 'Для распознавания задачи эксперту нет действующего разрешения на расходы.',
  expert_transcription_failed: 'Задачу не удалось распознать. Автоматического повтора не было; продиктуйте её заново после проверки доступа.',
  native_experts_disabled: 'Эксперт не включён в разрешение этого разговора.',
  expert_budget_missing_or_expired: 'Срок отдельного допуска к эксперту истёк или допуск отсутствует.',
  expert_budget_exhausted: 'Разрешённое число задач эксперту использовано.',
  expert_budget_other_device: 'Допуск к эксперту выдан другому устройству.',
  expert_quota_consent_required: 'Передача задачи эксперту требует отдельного согласия на его квоту.',
  confirmed_adult_profile_required: 'Для этой задачи требуется подтверждённый взрослый профиль или отдельный допуск устройства.',
  owner_expert_daily_limit: 'Сегодня использовано разрешённое число задач эксперту.',
  not_installed: 'Программа эксперта не установлена на сервере.',
  codex_not_installed: 'Codex не установлен на сервере.',
  isolation_not_verified: 'Проверка изоляции эксперта ещё не подтверждена. Запуск закрыт.',
  oauth_login_required: 'На сервере требуется вход в учётную запись эксперта.',
  quota_consent_required: 'Использование квоты эксперта ещё не разрешено.',
  empty_setup_retry_rate_limited: 'Слишком много попыток подключения подряд. Подождите минуту и нажмите кнопку снова.',
};
function human(code) {
  if (code === 'NotAllowedError') return 'Доступ к микрофону не предоставлен. Разрешите его в настройках браузера и нажмите «Начать разговор».';
  if (String(code).startsWith('expert_unavailable:'))
    return 'Эксперт недоступен. '+String(code).slice('expert_unavailable:'.length).split(',').map(reason => human(reason)).join(' ');
  return messages[code] || ('Причина: '+String(code || 'неизвестная ошибка').replaceAll('_', ' '));
}
function alertText(text) { $('alert').textContent = text || ''; $('alert').hidden = !text; }
const browser = new GoBotSophiaAudio.BrowserVoice({
  onState: () => render(),
  onError: code => { errorText = human(code); render(); },
  onText: (text, kind) => {
    if (selected !== 'browser') return;
    $('transcriptCard').hidden = !text;
    $('transcriptTitle').textContent = kind.startsWith('expert_') ? 'Ответ эксперта' : 'Ваш вопрос';
    $('transcript').textContent = kind === 'expert_text_delta'
      ? ($('transcript').dataset.kind === kind ? $('transcript').textContent + text : text).slice(-12000)
      : text.slice(0, kind === 'expert_result' ? 12000 : 4000);
    $('transcript').dataset.kind = kind;
  },
});
function boardSession() { return current?.brain?.sessions?.[0]; }
function idle(state) { return !state || ['ready', 'blocked', 'muted', 'closed', 'disconnected', 'idle'].includes(state); }
function render() {
  const dev = current?.device || {}, board = boardSession(), usingBrowser = selected === 'browser';
  const browserAdmission = browser.eligibility(browserStatus);
  const session = usingBrowser ? browser.state() : board;
  const active = usingBrowser ? (browser.connected || browser.startRequested || !!browser.capture?.stream || !!browserStatus?.brain?.sessions?.length) : !!board;
  const ready = session?.ready === true;
  const muted = usingBrowser && !browser.connected && browserAdmission.existing
    ? browserAdmission.existing.muted === true : session?.muted === true;
  const allowed = usingBrowser ? (browserAdmission.input && (!ready || session.generation_allowed)) : board?.generation_allowed === true;
  const phase = muted ? 'muted' : usingBrowser ? session.state : dev.voice_phase || (dev.input_open ? 'listening' : session?.state || 'ready');
  let title, description;
  if (usingBrowser && browserStatus && !browserAdmission.allowed && !ready) {
    title = 'Браузер пока недоступен'; description = human(browserAdmission.code);
  } else if (usingBrowser && browserAdmission.subscriber && !ready) {
    title = 'Эксперт продолжает работу'; description = 'Можно вернуться к ответу. Микрофон при таком подключении не включается.';
  } else if (usingBrowser && !ready && phase !== 'connecting') {
    title = 'Микрофон браузера'; description = 'Нажмите «Начать разговор». Подключение и доступ к микрофону проверяются перед вводом.';
  } else if (!usingBrowser && current?.status === 'unavailable') {
    title = 'Нет связи с сервером'; description = 'София на колонке продолжает работать локально.';
  } else if (!usingBrowser && !dev.device_protocol_confirmed) {
    title = 'Жду колонку'; description = 'Новый разговорный тракт ещё не подтвердил подключение.';
  } else if (muted) {
    title = 'Микрофон выключен'; description = usingBrowser ? 'Включите микрофон, затем начните разговор кнопкой.' : 'Включите микрофон, чтобы снова обратиться к Софии.';
  } else if (phase === 'listening') {
    title = 'Слушаю'; description = session?.input_mode === 'expert' ? 'Продиктуйте задачу целиком. Можно завершить ввод кнопкой.' : 'Говорите. Продолжение фразы не ограничено окном ожидания.';
  } else if (phase === 'speaking') {
    title = 'Отвечаю'; description = 'После полного окончания ответа можно продолжить без имени.';
  } else if (phase === 'thinking' || phase === 'closing_input') {
    title = 'Обдумываю ответ'; description = session?.input_mode === 'expert' ? 'Эксперт работает над задачей. Готовые части ответа прозвучат по порядку.' : 'Ожидаю ответ на ваш вопрос.';
  } else if (phase === 'waiting') {
    title = 'Ответ прозвучал'; description = 'Ожидаю подтверждения продолжения разговора от сервера.';
  } else if (phase === 'stopping') {
    title = 'Останавливаю разговор'; description = 'Микрофон и звук уже выключены. Ожидаю подтверждения остановки от сервера.';
  } else if (!ready) {
    title = usingBrowser ? 'Подключаю браузер' : 'Подключаю разговор'; description = 'Готовность появится после подтверждения облачной конфигурации.';
  } else {
    title = usingBrowser ? 'Разговор подключён' : 'София на связи';
    description = allowed ? (usingBrowser ? 'Начните вопрос кнопкой. Во время ожидания звук в облако не передаётся.' : 'Скажите «София» и задайте вопрос.') : 'Локальный источник подключён. Допуск к платному разговору закрыт.';
  }
  $('sourceLabel').textContent = usingBrowser ? 'МИКРОФОН БРАУЗЕРА' : 'ВАША КОЛОНКА';
  $('title').textContent = title; $('description').textContent = description; $('orb').className = 'orb '+phase;
  $('deviceConnection').textContent = 'Колонка: '+(dev.device_protocol_confirmed ? 'подключена' : 'ожидается');
  $('sourceAdmission').textContent = 'Разговор '+(usingBrowser ? 'браузера' : 'колонки')+': '+(allowed ? 'допуск есть' : 'допуск закрыт');
  $('cloud').textContent = ready ? 'Конфигурация подтверждена' : 'Не подтверждено';
  $('admission').textContent = allowed ? 'Да' : 'Закрыт'; $('voice').textContent = 'marin';
  for (const name of ['fast', 'expert']) {
    $(name).disabled = pending > 0 || (usingBrowser ? !idle(phase) : !board);
    $(name).setAttribute('aria-pressed', String(session?.input_mode === name));
  }
  // Financial readiness never disables cleanup of an already attached source.
  $('stop').disabled = !active; $('mute').disabled = !active;
  $('mute').textContent = muted ? 'Включить микрофон' : 'Выключить микрофон';
  $('mute').setAttribute('aria-pressed', String(muted));
  $('browserActions').hidden = !usingBrowser;
  $('browserStart').disabled = pending > 0 || !usingBrowser || !browserAdmission.allowed || !idle(phase) || browser.startRequested || browser.stopPending || (muted && !browserAdmission.subscriber);
  $('browserStart').textContent = browserAdmission.subscriber && !ready ? 'Вернуться к ответу' : ready ? 'Начать новый вопрос' : 'Начать разговор';
  $('browserFinish').hidden = !usingBrowser || !browser.inputOpen || browser.mode !== 'expert';
  $('modeHint').textContent = usingBrowser
    ? 'Браузер использует свою существующую привязку. Смена микрофона доступна между репликами.'
    : 'Режим меняется между репликами. Stop и Mute доступны и при закрытом допуске к расходам.';
  $('exampleFast').textContent = usingBrowser ? '«Сколько сейчас времени?»' : '«София, сколько сейчас времени?»';
  $('exampleExpert').textContent = usingBrowser ? '«Спроси у эксперта…»' : '«София, спроси у эксперта…»';
  const reason = usingBrowser ? (!browserAdmission.allowed && browserAdmission.code) : dev.last_error || current?.code;
  alertText(errorText || (reason ? human(reason) : ready && !allowed ? 'Текущий допуск не разрешает новый расход. Stop, Mute и выбор следующего режима остаются доступны.' : ''));
  $('details').textContent = JSON.stringify({source: selected, browser: usingBrowser ? {availability: browserStatus, session} : undefined,
    transport: current?.brain?.status?.transport, budget: current?.brain?.status?.budget, device: dev}, null, 2);
  $('updated').textContent = 'Обновлено '+new Date().toLocaleTimeString('ru-RU');
}
async function refresh() {
  const results = await Promise.allSettled([
    fetch('/api/sophia/status', {cache: 'no-store'}).then(r => r.json()),
    fetch('/api/sophia/browser/status', {cache: 'no-store'}).then(r => r.json()),
  ]);
  current = results[0].status === 'fulfilled' ? results[0].value : {status: 'unavailable', code: 'brain_or_gateway_unavailable'};
  browserStatus = results[1].status === 'fulfilled' ? results[1].value : {available: false, code: 'browser_voice_status_unavailable'};
  render();
}
async function control(body, source = selected) {
  pending++; render();
  try {
    const response = await fetch(source === 'browser' ? '/api/sophia/browser/control' : '/api/sophia/control', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) { errorText = human(data.detail || data.code); return false; }
    errorText = ''; await refresh(); return true;
  } catch { errorText = human('brain_or_gateway_unavailable'); return false; }
  finally { pending--; render(); }
}
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
  errorText = '';
  if (selected === 'browser') {
    try { browser.selectMode(button.dataset.mode); } catch (error) { errorText = human(error.message); render(); }
  } else control({action: 'mode', mode: button.dataset.mode});
}));
$('browserStart').addEventListener('click', async () => {
  errorText = ''; $('transcriptCard').hidden = true; $('transcript').textContent = '';
  try { await browser.start(browser.mode); } catch (error) { errorText = human(error.name === 'NotAllowedError' ? error.name : error.message); render(); }
});
$('browserFinish').addEventListener('click', async () => {
  try { await browser.finishInput(); } catch (error) { browser.failure(error.message); }
});
$('stop').addEventListener('click', () => {
  errorText = '';
  if (selected === 'browser') {
    browser.stop(); control({action: 'stop'}, 'browser'); // HTTP cleanup can overtake queued WebSocket PCM.
  }
  else control({action: 'stop'}, 'spotpear');
});
$('mute').addEventListener('click', () => {
  errorText = '';
  if (selected === 'browser') {
    const muted = browser.connected ? browser.muted : browser.eligibility(browserStatus).existing?.muted ?? browser.muted;
    browser.mute(!muted); control({action: 'mute', muted: !muted}, 'browser');
  }
  else control({action: 'mute', muted: !boardSession()?.muted}, 'spotpear');
});
$('source').addEventListener('change', () => {
  const target = $('source').value;
  const state = selected === 'browser' ? (browser.eligibility(browserStatus).existing?.expert_active ? 'thinking' : browser.phase)
    : current?.device?.voice_phase || boardSession()?.state;
  if (!idle(state)) { $('source').value = selected; errorText = human('microphone_source_change_requires_idle'); render(); return; }
  if (selected === 'browser') browser.detach();
  selected = target; errorText = ''; $('transcriptCard').hidden = true; $('transcript').textContent = ''; render();
});
window.addEventListener('pagehide', () => browser.detach());
window.addEventListener('offline', () => { browser.detach(); errorText = human('browser_voice_connection_lost'); render(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) browser.detach(); });
refresh(); setInterval(() => { if (!document.hidden && !pending) refresh(); }, 2000);
