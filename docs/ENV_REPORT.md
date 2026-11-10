# Обследование среды

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
| Gemini | CLI не обнаружен |

Codex status: authenticated; Cursor: unconfirmed.
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
