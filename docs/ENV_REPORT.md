# Обследование среды

Обновление 10 ноября: private Tailscale HTTPS 100.90.228.125:18786, точный allowlist
iPhone. Официальный project-local agy 1.5.3 и существующий Codex 0.159.2 авторизованы.
SpeechBrain 1.1.2 / Torch и Torchaudio 2.11.0 работают в .venv-speaker.
Global PATH/Python, firewall/router не менялись. Основные STT/TTS теперь OpenAI.
Ниже — снимок исходного preflight, не текущие значения свободного диска.

Windows native, Microsoft Windows 11 Home 10.0.26300, AMD64. CPU Ryzen 7 7840HS, 8 ядер/16 потоков;
RAM 13.68 GiB. Radeon 780M, CIM AdapterRAM 2 GiB — отчёт драйвера, не подтверждение выделенной VRAM.
Свободно на C: 81.09 GiB при первом preflight. GPU inference не проверялся.
Wi-Fi 192.168.3.15; также видны Tailscale и виртуальные интерфейсы. Сеть не менялась.
Очищенные snapshots: preflight.json и system-evidence.json; второй содержит полный доступный CIM/TCP список.

| Инструмент | Факт |
|---|---|
| Python / pip | 3.14.4 / 26.0.1, WindowsApps launcher |
| Git | 2.54.0.windows.1 |
| Node | v24.17.0 |
| ffmpeg | 2025-08-20 git-4d7c609be3 essentials |
| Docker / Compose / uv | Не обнаружены в PATH, контейнеров GoBot нет |
| ESP-IDF / esptool | Не обнаружены |
| Codex | 0.159.2, app-server --help и локальная JSON Schema проверены |
| Cursor | cursor-agent.cmd 2026.10.01-14929f9, ask/sandbox enabled доступны |
| agent.exe | Grok 1.0.30, исключён из Cursor route |
| Gemini | Официальный @google/gemini-cli 0.67.0 установлен project-local, OAuth ещё не выполнен |

Codex status: authenticated; Cursor: unconfirmed.
Актуализация 2026-11-09: account/read Codex подтвердил ChatGPT auth без model call;
offline tool audit пуст для Codex/Gemini. Gemini CLI stream-json проверен по help и исходникам пакета.
GEMINI_API_KEY/GOOGLE_API_KEY отсутствуют в Process/User/Machine; child environment всё равно их исключает.
Tailscale IP хоста 100.90.228.125, iPhone 100.120.201.115. HTTPS :18786 привязан только к Tailscale IP;
обычная TLS validation проходит. HTTP mock :18785 работает без TTL по просьбе владельца.
Whisper Small CPU int8 и Piper 1.8.0 Denis установлены только в .venv; модели data/models сохранены.
OpenAI ключ сохранён через HTTPS в DPAPI, выводится только bool наличия. API ещё не вызывался.
Каталоги .codex/.cursor видимы, .gemini отсутствует. Наличие каталога не доказывает авторизацию.
Сессии не копировались; status-команды не запускали модель. Cursor .ps1 через Windows PowerShell
упёрся в ExecutionPolicy, для диагностических --help/status использован существующий .cmd. Политика не менялась.

| Служба | Адрес | Режим |
|---|---|---|
| Brain | 127.0.0.1:18781 | mock HTTP/SSE |
| Host Bridge | 127.0.0.1:18782 | подписанный mock NDJSON |
| Fake XiaoZhi | 127.0.0.1:18783 | fixture WS, не upstream |
| Image origin | 127.0.0.1:18784 | локальный HTTP |

Все порты проверены bind до старта. Чужие listeners не останавливались. Ограниченный CIM сначала
был недоступен; повторное read-only обследование вне sandbox дало сведения. Создание файлов, .venv
и запуск project-local процессов выполнялись с одобрением вне read-only sandbox. PATH, глобальные
пакеты, SSH, Docker, firewall, домашняя сеть и существующие аккаунты не изменялись.

Windows TCP collector местами возвращает PID=0/неполные строки. Все четыре /healthz проверены
по loopback; binding также явно задан в исходниках. См. runtime-status.json и final-listeners.json.
