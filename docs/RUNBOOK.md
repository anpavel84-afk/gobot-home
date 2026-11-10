# Запуск Windows native

Для владельца с iPhone добавлен отдельный временный mock gateway: см. PHONE.md.
Запуск: .venv/Scripts/python.exe -X utf8 scripts/phone.py start --host 192.168.3.15 --prefix 24 --minutes 120
Остановка: .venv/Scripts/python.exe -X utf8 scripts/phone.py stop
Gateway не запускается вместе с основным стеком и автоматически завершается по истечении срока.

Каталог C:\Users\PLAN\gobot\GoBotHome. PowerShell, venv activation/изменение ExecutionPolicy не нужны.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/manage.py start
Invoke-RestMethod http://127.0.0.1:18781/healthz
.venv\Scripts\python.exe -X utf8 scripts/chat.py Привет GoBot
.venv\Scripts\python.exe -X utf8 scripts/manage.py status
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -X utf8 scripts/e2e.py
.venv\Scripts\python.exe -X utf8 scripts/manage.py stop
```

start проверяет четыре порта, чужие процессы не завершает. Повторный start проверяет свой supervisor.
Background через CREATE_NO_WINDOW, OS autostart отсутствует. stop пишет приватный stop.request;
supervisor завершает только своих детей/потомков, включая Windows venv redirector.
run/processes.json содержит PID/create_time, run/*.log — диагностика без access logs.
Restart budget: 4 запуска worker за жизнь supervisor, затем явные stop/start.

## Воспроизведение в новой копии

```powershell
python -X utf8 -m venv .venv
.venv\Scripts\python.exe -X utf8 -m pip install -r requirements.lock.txt
.venv\Scripts\python.exe -X utf8 scripts/manage.py init
.venv\Scripts\python.exe -X utf8 scripts/restore_sources.py
.venv\Scripts\python.exe -X utf8 scripts/prepare_upstream.py
$runUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls run /inheritance:r /grant:r "${runUser}:(OI)(CI)F"
.venv\Scripts\python.exe -X utf8 scripts/manage.py start
```

Lock закрепляет host graph. Restore не меняет existing checkout с другим SHA. Prepare проверяет SHA,
применяет отдельный strict-auth patch, копирует providers, генерирует sanitized base и секретный override
только внутри vendor. Upstream не стартует до совместимых зависимостей/ASR/TTS/device provisioning.
Точный blocker: из main/xiaozhi-server cwd `python app.py` → missing aioconsole;
`python -m pip install --dry-run --only-binary=:all: torch==2.2.2` под 3.14 → no distribution.
Подробности docs/upstream-*.txt. Нужна отдельная Python 3.10 среда, глобальный Python менять нельзя.

## Конфигурация и память

При необходимости .env.example копируется в .env этого проекта. Parser принимает только известные
GOBOT_* без shell evaluation; process env приоритетнее. Default — mock. Реальный Fast API требует
GOBOT_FAST_PROVIDER=openai, HTTPS base/model/key и GOBOT_ALLOW_PAID=1. Разрешения на платные пробы
в этой сессии нет; они не выполнялись. CLI admission остаётся закрытым независимо от этого флага.
ASR/TTS/VAD names валидируются, но наличие имени не означает установленную модель. Voice runtime — fixture-only.

SQLite: data/gobot.sqlite. Для backup остановить стек и сохранить SQLite + остаточные WAL/SHM или
использовать SQLite backup API; не копировать живую БД отдельно. Очистка явного scope:

```powershell
.venv\Scripts\python.exe -X utf8 scripts/memory.py --conversation CONVERSATION_ID --confirm
.venv\Scripts\python.exe -X utf8 scripts/memory.py --forget-facts-for-device DEVICE_ID --confirm
```

Restart переводит running в cancelled; replay final не повторяет TTS. reliability.py прерывает только
свой Brain worker и проверяет restart/SQLite/SSE disconnect; запуск временно прервёт активные ходы GoBot.

## Docker и LAN

Docker/Compose отсутствуют. compose.yaml проверен только YAML/contract tests. Optional mock-container
требует отдельные container keys, доступ uid10001 к bind-mounted data/keys, свободный Brain port и
фактическую сетевую/health/restart проверку на Docker. Не запускать одновременно с host Brain на 18781.
CLI auth homes не монтируются; host Bridge connection отсутствует. host.docker.internal не применяется.
Все текущие endpoints loopback: ESP32 до них не достучится. До доставки firewall/router не менять.

Реальный голос сначала half-duplex/PTT. Silero/русские ASR/TTS требуют моделей или разрешённых ключей.
faster-whisper/sherpa-onnx — CPU-кандидаты после проверки моделей; GPU inference на Radeon не проверен.
Piper — опционально после проверки GPL/лицензии голоса. Full-duplex/wake word — следующая измеряемая фаза.
