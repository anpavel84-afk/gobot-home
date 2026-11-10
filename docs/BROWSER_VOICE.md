# Браузерный GoBot

**Актуальное состояние 10 ноября: [CURRENT_STATUS.md](CURRENT_STATUS.md).**
STT/TTS — OpenAI основные; Whisper/Denis только вручную. AUTO/FAST — Flash Low
через Antigravity, REASONING — Flash Medium; Argon/Codex явно вручную. Gemini CLI/API
не используются. Конкретная модель видна под ответом. Speech API пробы выполнены.
Темы, факты, «не запоминать» и context diagnostics доступны в текущем интерфейсе.
[Прослушать разрешённый OpenAI образец](https://plan.tailffc57c.ts.net:18786/audio/voice-check.wav).

Ниже — историческое описание 9 ноября; при расхождении применяйте CURRENT_STATUS.md.

Основной адрес: https://plan.tailffc57c.ts.net:18786 . Включить Tailscale на iPhone.
Доступны только разрешённые Tailscale IP компьютера и iPhone; общий интернет и Wi-Fi не публикуются.
Сертификат доверенный, выдан после включения HTTPS Certificates владельцем. Root CA на iPhone не устанавливался.
Адрес HTTP :18785 остаётся отдельной диагностикой mock без микрофона и реальных CLI.

## Использование

1. Открыть HTTPS-адрес в Safari. Выбрать AUTO, Codex, Gemini или явно диагностический Mock.
2. Для реальных CLI отметить согласие на расход квоты. AUTO выбирает доступного Gemini, затем Codex;
   если доступных нет, выводится ошибка. Автоматического mock fallback нет.
3. Нажать и удерживать микрофон либо «Начать запись» / «Закончить запись». Разрешить микрофон в Safari.
   Запись ограничена 60 s и 8 MB. После распознавания исправить текст и нажать «Отправить».
4. По умолчанию голос OpenAI / marin. Для него отдельно отметить разрешение платного API-синтеза.
   Denis выбирается только явно как offline резерв. Ошибки OpenAI не меняют провайдера.
5. Кнопка остановки прерывает fetch/SSE, серверную задачу, CLI Job и очередь аудио. Громкость регулируется.
   Отключение озвучивания во время ответа останавливает текущий ответ; следующий можно отправить без звука.

Ключ вводится только в /settings/openai. Windows DPAPI шифрует его для текущей Windows-учётной записи.
GET возвращает лишь configured. Ключ не передаётся CLI, не хранится в localStorage и не попадает в git.
Сохранение ключа не делает платный вызов и не подтверждает его валидность/баланс/доступ к модели.

## Общий сервер

HTTPS transport -> loopback Brain -> Service / SQLite / router -> HMAC loopback Bridge -> официальный CLI.
Браузерный transport не создаёт своей памяти или LLM. История принадлежит Brain; conversation UUID хранится
в localStorage, ownership привязан к разрешённому Tailscale peer. Новый разговор не удаляет старую историю.
Будущий XiaoZhi provider использует тот же Brain, но transport/audio фрейминг остаются отдельными.

MediaRecorder выбирает поддерживаемый MIME: Chrome обычно WebM/Opus, Safari может MP4/AAC.
На сервере ffmpeg принимает только bounded pipe input, без file/http протоколов, приводит к mono 16 kHz s16le.
Whisper Small CPU int8 / faster-whisper распознаёт сегмент после окончания записи; Silero — фильтр сегмента.
Это не token-streaming STT и не automatic live end-of-speech. Live VAD/wake word/acoustic barge-in отложены.

LLM typed iterator -> SentenceBuffer -> очередь 4 предложения -> серверный TTS -> bounded SSE audio_chunk
(base64 PCM s16le, sample_rate, audio_id, seq) -> AudioContext/GainNode/AudioBufferSourceNode браузера.
Клиент разблокирует AudioContext нажатием, дедуплицирует seq, ограничивает планирование вперёд 4 секундами,
очищает источники при отмене. Реальные ограничения autoplay и акустика iPhone требуют проверки владельцем.
PCM браузерного transport никогда не посылается как XiaoZhi binary Opus frame.

## Голос OpenAI

Основной: gpt-realtime-2.1-mini, Realtime WebSocket server-to-server, PCM mono 24 kHz, marin по умолчанию.
Доступны 10 встроенных голосов. Инструкции требуют дословного русского чтения с естественной интонацией;
это генеративный диктор, идентичность голосовому режиму ChatGPT не обещается.
Одна Realtime сессия на предложение, tools=[], tool_choice=none, без истории беседы в TTS.
session.updated проверяется до response.create; аудио берётся только из response.output_audio.delta.
Закрытие отправляет response.cancel и закрывает WS. Timeout 45 s, лимит текста/аудио; без retries и fallback.
Сессия на предложение проста и отменяема, но добавляет handshake latency; reuse — дальнейшая оптимизация после замеров.

Причина выбора: официальный /audio/speech рекомендует новым интеграциям Realtime; gpt-4o-mini-tts,
tts-1 и tts-1-hd объявлены deprecated с shutdown 2027-01-06. Исходный адаптер Speech API заменён до live теста.
Источники: [TTS](https://developers.openai.com/api/docs/guides/text-to-speech),
[Realtime WebSockets](https://developers.openai.com/api/docs/guides/voice-websockets),
[client events](https://developers.openai.com/api/reference/resources/realtime/client-events),
[server events](https://developers.openai.com/api/reference/resources/realtime/server-events).

## Что реально проверено

67 pytest, JS syntax, TLS с обычной проверкой доверия, key form perimeter, DPAPI на временном тестовом ключе.
Бесплатный HTTPS E2E: синтетическая русская WAV -> реальный Whisper Small -> явно mock LLM -> реальный
Piper Denis -> 22 последовательных PCM чанка -> SQLite. См. browser-free-e2e.json.
Это не подтверждение живого микрофона, Safari playback, real LLM или OpenAI TTS.
Codex offline App Server probe отправлен только в локальный HTTP fixture; tools=[] и account/read authenticated.
Gemini установлен, tool registry пуст, wildcard deny проверен. OAuth пока отсутствует.
Реальные Codex/OpenAI пробы ждут отдельного разрешения владельца. Статусы обновляются при actual test.

## Управление

В PowerShell из GoBotHome:

    .venv\Scripts\python.exe scripts/manage.py start
    .venv\Scripts\python.exe scripts/web.py start
    .venv\Scripts\python.exe scripts/web.py status
    .venv\Scripts\python.exe scripts/web.py stop
    .venv\Scripts\python.exe scripts/manage.py stop

HTTP диагностика останавливается отдельно: .venv\Scripts\python.exe scripts/phone.py stop.
Нет auto-expiry или OS autostart. При перезагрузке ПК запуск повторяется вручную.
Сертификат Tailscale имеет срок действия: перед истечением обновить командой tailscale cert с теми же
project-local путями run/tls/gobot.crt и run/tls/gobot.key и перезапустить только scripts/web.py.
Funnel/Serve/firewall/router не менялись. Смена Tailscale IP требует явного обновления allowlist.

## Воспроизведение и probes

    .venv\Scripts\python.exe -m pip install -r requirements-audio.txt
    .venv\Scripts\python.exe scripts/download_audio_models.py
    npm ci --prefix services/agent-bridge/gemini-cli --ignore-scripts --no-audit --no-fund
    .venv\Scripts\python.exe scripts/audit_agents.py
    node scripts/audit_gemini.mjs
    .venv\Scripts\python.exe -m pytest -q

Codex audit требует установленную native CLI и metadata cache/schema указанной версии. Изменение бинарника
или policy/code инвалидирует evidence. Не переносить чужие auth-сессии. Gemini 0.67.0 установлен локально;
его OAuth должен выполняться официальным Login with Google с GEMINI_CLI_HOME=run/gemini-home и settings policy.
Без OAuth Gemini не запускается. API keys Gemini удалены из child env; на Process/User/Machine их не обнаружено.
Cursor live не подключён; сторонний proxy не устанавливался.

Вход с телефона: /settings/gemini -> «Начать вход» -> официальная Google ссылка -> одноразовый код
в password-поле на этой же HTTPS странице. scripts/gemini_oauth_only.mjs вызывает только официальный
getOauthClient из pinned пакета 0.67.0, без model inference. Это version-specific shim к проверенному
экспорту пакета, не сторонний OAuth-клиент. Официальный cacheCredentials сохраняет сессию в run/gemini-home.
Ссылка с PKCE/state доступна только разрешённым peer через HTTPS, не логируется. Terminal stdout/stderr,
включая возможный echo кода, отбрасываются; браузеру возвращается лишь consent URL и status.
Ограничение 330 s и Job cleanup; отмена завершает процесс. В тесте получена official URL без входа и model call,
сам Google login выполняет владелец. При обновлении CLI этот auth shim требует повторной проверки.

scripts/e2e_live.py codex|gemini|openai-voice --owner-approved — только после явного разрешения владельца.
Флаг фиксирует уже полученное согласие, не является заменой запроса разрешения. Автотесты эту команду не вызывают.
