# GoBot Home MVP

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
Реальные Codex и Antigravity проверялись ранее; три разрешённые speech API пробы выполнены.
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

Контекст ограничен, архив принадлежит GoBot. Проверки: 519 pytest, 240 synthetic
router cases, 200-turn day. Это не подтверждает качество LLM или семейной биометрии.
[Контекст](docs/CONTEXT_POLICY.md) · [Память](docs/MEMORY_ARCHITECTURE.md) ·
[Оценка](docs/CONTEXT_EVALUATION.md) · [Speech Formatter](docs/SPEECH_FORMATTING.md).

[Runbook](docs/RUNBOOK.md) · [Архитектура](docs/ARCHITECTURE.md) · [Среда](docs/ENV_REPORT.md) ·
[Безопасность](docs/SECURITY.md) · [Протокол](docs/PROTOCOL.md) · [Измерения](docs/BENCHMARKS.md) ·
[Железо](docs/HARDWARE_CHECKLIST.md) · [Фактический статус](docs/CURRENT_STATUS.md)

Визуальные ответы: [реализация и ограничения](docs/VISUAL_PIPELINE.md).
AUTO показывает реальные фото/галерею, локальную схему, карточки состояния и таймер.
Примеры: «Покажи, как выглядит лабрадор», «Покажи картинку Raspberry Pi»,
«Покажи, как выглядят помидоры Бычье сердце». Openverse без ключа, локальный TTL/LRU
кэш; погода и музыка пока честно сообщают об отсутствии источника.
Visual Response Composer выбирает сцену для каждого product-ответа, включая лицо,
иконку, фото, процедурную схему или виджет. Не вызывает отдельную модель ради выбора
визуала. [Multimodal Responses](docs/MULTIMODAL_RESPONSES.md).
Проверены отдельный HTTPS image E2E и 519 бесплатных pytest; реальный Safari
layout и новый платный TTS smoke этой фазы не проверялись.

Публичный исходный код: [anpavel84-afk/gobot-home](https://github.com/anpavel84-afk/gobot-home),
ветка master. GitHub connector подключён; Actions выключены. Правила публикации:
[GITHUB_PUBLICATION.md](docs/GITHUB_PUBLICATION.md). Runtime data и ключи не публикуются.
