# Проверка GoBot с iPhone по домашнему Wi-Fi

В Safari открыть **http://192.168.3.15:18785**. Компьютер и телефон должны находиться в одной домашней
сети без изоляции клиентов гостевого Wi-Fi. На iPhone не нужен терминал или установка приложения.

Три кнопки запускают фиксированные бесплатные сценарии:

1. «Привет, GoBot» — настоящий HTTP/SSE mock-поток от Brain.
2. «Таймер на 5 минут» — русский mock-ответ и JSON-команда с демонстрацией экрана.
3. «Проверить Bridge» — подписанный host Bridge и MockAgentAdapter.

«Озвучить на iPhone» использует Web Speech speechSynthesis устройства по отдельному нажатию.
Это не проверка серверного TTS. Таймер показывает команду, обратный отсчёт пока не реализован.
Запись микрофона и произвольный ввод на странице не включены. Для getUserMedia нужен HTTPS secure context:
https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia .
Реальная речь и ESP32 пока не проверены.

## Границы

Gateway слушает конкретный Wi-Fi IPv4 на 18785; не wildcard. Клиенты только Wi-Fi subnet
192.168.3.0/24 и собственный loopback для tests. Host/Origin проверяются, proxy headers не доверяются,
CORS/frames запрещены. Максимум 2 параллельных сценария, 120 запусков, интервал 1 s на клиента.
Автоматическая остановка через 120 минут. В assets и ответах нет ключей.

У этой ограниченной демонстрации нет логина: она доступна другим клиентам разрешённого Wi-Fi subnet.
Только несекретные health-статусы и фиксированные mock-реплики. Brain/Bridge остаются 127.0.0.1,
credentials только на сервере. Нет общего proxy, терминала, CLI, чтения истории или произвольных команд.
Новые demo-turns сохраняются под device_id=phone-demo. Router/firewall/внешняя публикация не менялись.
Это узкое LAN-исключение по просьбе владельца проверить MVP с iPhone.

## Управление через Codex / компьютер

    .venv\Scripts\python.exe -X utf8 scripts/phone.py start --host 192.168.3.15 --prefix 24 --minutes 120
    .venv\Scripts\python.exe -X utf8 scripts/phone.py status
    .venv\Scripts\python.exe -X utf8 scripts/phone.py stop

Stop завершает только phone gateway. Основной стек GoBot работает дальше.
Если ссылка не открывается: проверить Wi-Fi/IP/guest isolation; отдельный узкий firewall rule согласовать
при необходимости. Не отключать защиту и не менять router автоматически.

Browser/API tests на компьютере не заменяют проверку на физическом iPhone — её подтверждает владелец.
