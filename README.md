# GoBot Home

**[Единый паспорт проекта: что сделано, архитектура, проверки и ограничения](docs/CURRENT_STATUS.md).**
[Целевая спецификация](docs/GOBOT_HOME_TARGET_SYSTEM.md) описывает требования; паспорт — фактическую реализацию.

**[Демо 2 · A/B](https://plan.tailffc57c.ts.net:18786/demo2)**: A — сохранённый
интерфейс a71b71e и legacy STT/CLI/Speech Formatter/TTS; B — нативный
`gpt-realtime-2.1-mini` через audio-only WebRTC и серверный sideband.
Оба используют общий Brain. Полный старый код/настройки/базы/клипы сохранены локально
до обновления; это не публичный архив данных и не второй независимый сервер.
Новое решение владельца: **[основной GoBot C ↔ A](https://plan.tailffc57c.ts.net:18786/device)**.
Новый разговор начинается в C (`gpt-live-1`, не 1.1, прежний разрешённый backend Luna).
«Экспертный режим»/«давай разберём подробно» закрывает Live и включает существующий A.
«Живой разговор» возвращает C; «стоп» или10s тишины после ответа завершает разговор
и сбрасывает выбор на C, не открывая платное соединение. A использует прежний AUTO
Antigravity Flash Low/Medium и Speech Formatter. Sol Medium не подставлен молча.
Локальное пробуждение «ГоБот» пока не настроено: для проверки используйте Start.
[Фактические проверки и ограничения](docs/CURRENT_STATUS.md#35-исправления-после-телефонных-замечаний-нет-картинки-и-переход-a).
Сравнительные A/B/C сохранены.
Старые ссылки C также поддерживают общий переход C↔A. При отсутствии картинки
основной экран сохраняет говорящее лицо; причины поиска доступны в диагностике.
Открытие страницы не запускает платную сессию: нужны явное включение и серверный допуск.
Для владельца на его iPhone включено постоянное
ручное тестирование B без лимита числа запусков/ответов и без 90-секундного отсечения.
Автоматические платные developer tests, CLI и ImageGen требуют отдельных согласий; старые бюджеты не переиспользуются.
11 ноября отдельно разрешён OpenAI Image API fallback на телефоне владельца:
Wikimedia first, максимум 20 попыток/UTC-day, 1024×1024 low, без автоматических
повторов. Developer paid trials этим не разрешены; [статус включения](docs/CURRENT_STATUS.md#27-включение-image-fallback-по-разрешению-владельца-11-ноября).
SpeakerIdentity подключён локальным PCM mirror к прежнему ECAPA worker; нужны
добровольные образцы и калибровка. Семейные голоса/характеры — в существующем разделе
«Семья». Нативная личная память пока закрыта, default-контекст — гостевой RAM.

В B добавлена панель «Экспертные задачи»: точный model/effort, причины блокировки,
согласие и полный результат. Sol High / Astra Medium доступны в каталоге; запуск
требует конечного CLI grant и подтверждения задачи. В Owner Full Test публичные
задачи разрешены без доступа к личному архиву; детские/приватные ACL сохраняются.
Настоящий Sol High handoff проверен текстовым B-вводом; голос/iPhone отдельно.
Native-derived общий контекст C↔A пока guest/RAM-only;
[границы проверки](docs/CURRENT_STATUS.md#34-единый-разговор-c--a--11-ноября).
При закрытом допуске предложение больше не выдаётся за ожидающий запуск:
панель показывает «Задача в CLI не передана». A/B настройки и согласия разделены;
[разбор случая и проверки](docs/CURRENT_STATUS.md#28-разбор-несостоявшейся-передачи-b--cli-и-восстановление-a).

**Основной браузерный GoBot:** [приватный HTTPS через Tailscale](https://plan.tailffc57c.ts.net:18786).
Текст/запись микрофона, общая память, выбор CLI и серверного голоса. Фактические проверки и ограничения:
[BROWSER_VOICE.md](docs/BROWSER_VOICE.md). Реальные платные/CLI пробы требуют отдельного согласия.
**[Режим устройства](https://plan.tailffc57c.ts.net:18786/device)** — отдельный круглый
экран 240×240 с удержанием для вопроса и автоматической отправкой через тот же Brain.
Classic/Soft/Minimal и экранные настройки сохраняются сервером в панели управления.
Проверки и незавершённая голосовая активация: [DEVICE_MODE.md](docs/DEVICE_MODE.md).
Wi-Fi [mock-диагностика](http://192.168.3.15:18785) работает до остановки владельцем; [PHONE.md](docs/PHONE.md).

На Windows запущены Brain, защищённый Host Agent Bridge, browser transport и XiaoZhi fixture-device.
Основные STT и TTS — OpenAI; Whisper Small и Piper Denis только явный ручной резерв.
Реальные пробы CLI и OpenAI speech описаны в паспорте с расходом и ограничениями.
В распознавании имени «Гобот» были ошибки. Физической платы нет.
Upstream voice server имеет воспроизводимый blocker Python/Torch; см. docs/DEPENDENCIES.md.

```powershell
cd C:\Users\PLAN\gobot\GoBotHome
.venv\Scripts\python.exe -X utf8 scripts/manage.py start
.venv\Scripts\python.exe -X utf8 scripts/web.py start
.venv\Scripts\python.exe -X utf8 scripts/chat.py Привет GoBot
.venv\Scripts\python.exe -X utf8 scripts/e2e.py
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -X utf8 scripts/manage.py stop
.venv\Scripts\python.exe -X utf8 scripts/web.py stop
```

Health: http://127.0.0.1:18781/healthz . Ключи генерируются в игнорируемом run/keys.json, не печатаются.
Автозапуска Windows нет. AUTO/FAST: Antigravity gemini-3.8-flash-low; REASONING:
gemini-3.8-flash-medium. Argon и Codex — явно вручную. Gemini CLI/API исключены.
Admission CLI проверяется offline; доступ требует согласия на квоту. Прошивки не было.

Контекст ограничен, архив принадлежит GoBot. Актуальные проверки, расходы и статус развёртывания приведены в едином паспорте. Mocks не подтверждают качество LLM или семейной биометрии.
[Контекст](docs/CONTEXT_POLICY.md) · [Память](docs/MEMORY_ARCHITECTURE.md) ·
[Оценка](docs/CONTEXT_EVALUATION.md) · [Speech Formatter](docs/SPEECH_FORMATTING.md).

[Runbook](docs/RUNBOOK.md) · [Архитектура](docs/ARCHITECTURE.md) · [Среда](docs/ENV_REPORT.md) ·
[Безопасность](docs/SECURITY.md) · [Протокол](docs/PROTOCOL.md) · [Измерения](docs/BENCHMARKS.md) ·
[Железо](docs/HARDWARE_CHECKLIST.md) · [Фактический статус](docs/CURRENT_STATUS.md)

Визуальные ответы: [реализация и ограничения](docs/VISUAL_PIPELINE.md).
AUTO показывает реальные фото/галерею, локальную схему, карточки состояния и таймер.
Примеры: «Покажи, как выглядит лабрадор», «Покажи картинку Raspberry Pi»,
«Покажи, как выглядят помидоры Бычье сердце». Openverse без ключа, локальный TTL/LRU
кэш; погода использует Open-Meteo после подтверждения города, музыкальный источник пока не подключён.
Visual Response Composer выбирает сцену для каждого product-ответа, включая лицо,
иконку, фото, процедурную схему или виджет. Не вызывает отдельную модель ради выбора
визуала. [Multimodal Responses](docs/MULTIMODAL_RESPONSES.md).
Проверки HTTPS/image/voice разделены по типам доказательств в паспорте; физический iPhone отдельно не подтверждён.

Публичный исходный код: [anpavel84-afk/gobot-home](https://github.com/anpavel84-afk/gobot-home),
ветка master. GitHub connector подключён; Actions выключены. Правила публикации:
[GITHUB_PUBLICATION.md](docs/GITHUB_PUBLICATION.md). Runtime data и ключи не публикуются.

Текущий приоритет M1 по [целевой v0.2](docs/GOBOT_HOME_TARGET_SYSTEM.md):
[сквозная телеметрия](docs/LATENCY_V02.md) и [матрица требований](docs/REQUIREMENTS_MATRIX.md).
Earcon/filler отделены от полезного ответа; реальное сокращение iPhone TTFA пока не подтверждено.

В текущем B короткое касание лица во время речи сохраняет ответ; для нового вопроса
удерживайте 0,5 s либо используйте Stop. Показанная авторасшифровка — отдельный ASR,
а не доказательство понимания native-аудио. «Ответить по этой расшифровке» — явное
уточнение текстом в ту же Realtime-беседу. Детали и ограничения — паспорт §20.

Демо 2 сохраняет A (legacy), B (Realtime Mini, прежние настройки) и добавляет C
(GPT-Live 1, explicit candidate). API 1.1 пока не подтверждён. C использует тот же
Brain, инструменты, Visual Pipeline и ExpertJobs, отдельный Live protocol и duration
ledger. Владелец отдельно разрешил быстрый backend gpt-6-luna: 2048 input / 512 output,
один запрос одновременно, без tools/retries, общий Owner Full Test. Реализация и
реальные этапы приёмки разделены в паспорте §30–32; B не заменяется молча.
Открыть: `/demo2/a/device` — прежний путь, `/demo2/b/device` — Realtime Mini,
`/demo2/c/device` — GPT-Live 1 + gpt-6-luna. Код9e6d0bb опубликован и запущен;
приёмка на физическом iPhone и доступ API Live1.1 остаются отдельными этапами.
