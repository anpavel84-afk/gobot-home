'use strict';
const $ = (id) => document.getElementById(id);
let stream = null, answer = '', started = 0, deltas = 0;
function busy(on) {
  document.querySelectorAll('[data-scenario]').forEach((button) => button.disabled = on);
  $('stop').disabled = !on;
  $('speak').disabled = on || !answer || !('speechSynthesis' in window);
  $('orb').classList.toggle('busy', on);
}
function finish(label) {
  if (stream) stream.close();
  stream = null;
  busy(false);
  $('result-badge').textContent = label;
  $('robot-label').textContent = label === 'Проверено · mock' ? 'Программный контур ответил' : label;
}
function run(scenario) {
  if (stream) stream.close();
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  answer = ''; deltas = 0; started = performance.now();
  $('answer').textContent = 'Ждём ответ…';
  $('timer').hidden = true;
  $('events').replaceChildren();
  $('result-badge').textContent = 'Получаем поток';
  $('robot-label').textContent = 'GoBot отвечает…';
  busy(true);
  stream = new EventSource('/api/demo/' + scenario);
  stream.onmessage = (message) => {
    const item = JSON.parse(message.data), data = item.data || {};
    if (item.type === 'text_delta') {
      answer += data.text; deltas++;
      $('answer').textContent = answer;
    } else if (item.type === 'widget_command') {
      $('timer').hidden = false;
    } else if (item.type === 'final') {
      answer = data.text; $('answer').textContent = answer;
      const entry = document.createElement('li');
      entry.textContent = deltas + ' частей · ' + Math.round(performance.now() - started) + ' мс · ' + data.provider;
      $('events').append(entry);
      finish('Проверено · mock');
    } else if (item.type === 'error' || item.type === 'cancelled') {
      finish('Тест прерван');
      if (!answer) $('answer').textContent = 'Тест сейчас недоступен. Обнови состояние системы и попробуй снова.';
    }
  };
  stream.onerror = () => {
    finish('Нет соединения');
    if (!answer) $('answer').textContent = 'Не удалось получить ответ. Проверь Wi-Fi и нажми «Обновить».';
  };
}
async function refresh() {
  $('refresh').disabled = true;
  try {
    const response = await fetch('/api/status', {cache: 'no-store'});
    if (!response.ok) throw new Error('Unavailable');
    const data = await response.json();
    $('services').replaceChildren();
    data.services.forEach((service) => {
      const row = document.createElement('div'), label = document.createElement('span'), result = document.createElement('span');
      row.className = 'service'; label.textContent = service.name;
      result.className = service.ok ? 'online' : 'offline';
      result.textContent = service.ok ? 'На связи' : 'Недоступен';
      row.append(label, result); $('services').append(row);
    });
    $('tests-status').textContent = (data.unit_tests_passed || '—') + ' автоматических тестов пройдено на компьютере · режим mock';
    $('expiry').textContent = data.remaining_seconds === null ? 'Доступ работает до команды владельца об остановке.' : 'Доступ закроется примерно через ' + Math.ceil(data.remaining_seconds / 60) + ' мин.';
  } catch (error) {
    $('services').textContent = 'Компьютер не отвечает или время доступа истекло.';
  } finally { $('refresh').disabled = false; }
}
document.querySelectorAll('[data-scenario]').forEach((button) => button.addEventListener('click', () => run(button.dataset.scenario)));
$('refresh').addEventListener('click', refresh);
$('stop').addEventListener('click', () => finish('Остановлено'));
$('speak').addEventListener('click', () => {
  if (!answer || !('speechSynthesis' in window)) return;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(answer);
  utterance.lang = 'ru-RU';
  const russian = speechSynthesis.getVoices().find((voice) => voice.lang.toLowerCase().startsWith('ru'));
  if (russian) utterance.voice = russian;
  speechSynthesis.speak(utterance);
});
window.addEventListener('pagehide', () => { if (stream) stream.close(); });
refresh();
