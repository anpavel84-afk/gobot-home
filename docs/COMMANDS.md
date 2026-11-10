# Выполненные команды и проверки

Изменения только в GoBotHome. Однократные project-local генераторы исходников удалены после записи
итоговых файлов. Полные here-strings авторинга не нужны для запуска; runtime source сохранён в git.

- Get-CimInstance OS/CPU/ComputerSystem/VideoController; Get-PSDrive; Get-NetIPAddress; Get-NetTCPConnection.
- Get-Command tools; python --version; pip --version; git --version; ffmpeg -version; node --version.
- codex --version; codex app-server --help; codex exec --help; codex app-server generate-json-schema --out vendor/references/codex-schema.
- cursor-agent --version/--help; agent --version/--help (это Grok).
- codex login status; cursor-agent status, сохранён только очищенный state.
- git clone --depth 1 --filter=blob:none --sparse для двух upstream; sparse-checkout set; rev-parse HEAD.
- Read-only pinned GitHub source/commit metadata, без выполнения сторонних install scripts.
- python -m venv .venv; .venv/Scripts/python.exe -m pip install --cache-dir data/pip-cache -r requirements.txt.
- pip freeze → requirements.lock.txt; python -X utf8 -m compileall -q services/brain scripts.
- python app.py из upstream cwd → missing aioconsole; pip install --dry-run --no-cache-dir --only-binary=:all: torch==2.2.2 → incompatible.
- scripts/manage.py init; icacls run /inheritance:r /grant:r CURRENT_USER:(OI)(CI)F, только новый run.
- scripts/prepare_upstream.py; git apply --check/apply/--reverse --check для source security patch.
- git -C vendor/xiaozhi-firmware apply --check ../../firmware/custom-ui-card.patch, без применения.
- .venv/Scripts/python.exe -X utf8 -m pytest -q --tb=short; полный последний вывод tests-output.txt.
- scripts/manage.py start/status/stop/start; scripts/chat.py Привет GoBot.
- scripts/e2e.py: HTTP/SSE/signed Bridge/fake WS v1-v3/abort/lost connection/reconnect.
- scripts/reliability.py: только собственный Brain worker прерван, supervisor восстановил его, SQLite/SSE cleanup passed.
- git init/add/local commit/status в отдельном репозитории, без push/global git config.

Не выполнялись: model inference/paid API/CLI task, firmware flash/OTA/NVS, Docker install/up,
firewall/router change, global packages, HA/Music ecosystem install или реальные домашние команды.
