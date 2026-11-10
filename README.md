# GoBot Home MVP

На Windows запущен **mock-контур**: русский текстовый streaming, SQLite, защищённый Host Agent Bridge
и XiaoZhi fixture-device. Реальное распознавание/синтез речи и физическая плата ещё не проверены.
Upstream voice server имеет воспроизводимый blocker Python/Torch; см. docs/DEPENDENCIES.md.

```powershell
cd C:\Users\PLAN\gobot\GoBotHome
.venv\Scripts\python.exe -X utf8 scripts/manage.py start
.venv\Scripts\python.exe -X utf8 scripts/chat.py Привет GoBot
.venv\Scripts\python.exe -X utf8 scripts/e2e.py
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -X utf8 scripts/manage.py stop
```

Health: http://127.0.0.1:18781/healthz . Ключи генерируются в игнорируемом run/keys.json, не печатаются.
Автозапуска при входе в Windows нет. Модельные вызовы и прошивка не выполнялись. Live CLI admission закрыт.

[Runbook](docs/RUNBOOK.md) · [Архитектура](docs/ARCHITECTURE.md) · [Среда](docs/ENV_REPORT.md) ·
[Безопасность](docs/SECURITY.md) · [Протокол](docs/PROTOCOL.md) · [Измерения](docs/BENCHMARKS.md) ·
[Железо](docs/HARDWARE_CHECKLIST.md) · [Фактический статус](docs/STATUS.md)
