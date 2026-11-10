# Протокол и JSON UI v1

Точные SHAs и первичные ссылки: DEPENDENCIES.md. JSON events и Opus binary — разные типы WS сообщений.
JPEG/PCM не передаются как XiaoZhi audio frames.

| Framing | Header перед Opus | Проверка |
|---|---|---|
| v1 | Нет | Raw Opus packet |
| v2 | >HHIII: version=2,type=0,reserved=0,timestamp_ms,payload_size | 16 bytes, network endian |
| v3 | >BBH: type=0,reserved=0,payload_size | 4 bytes, network endian |

gobot/protocol.py — codec для fixture-device. Tests v1/v2/v3 не доказывают все эти режимы в upstream
Python server: полной negotiation этих версий в проверенном voice path не обнаружено. Начальный
production target — v1. MQTT gateway header из sendAudioHandle.py — отдельная схема, не firmware v2.
hello: transport=websocket, audio_params.format=opus, sample_rate/channels/frame_duration.
Board input/output — 24000 Hz. Fake явно использует 20 ms comfort packet; upstream default hello — 60 ms.
Production PCM/resample/Opus сохраняет реальные upstream ASR/TTS artifacts/codec и согласованные параметры.
Fake не проверяет декодирование микрофона. listen start/stop manual/PTT, tts start/sentence_start/stop,
abort, lost connection/reconnect покрыты mock E2E. Comfort packet — тишина; это не синтез русской речи.
abort закрывает Brain SSE и посылает tts stop.

## JSON UI contract

```json
{"type":"custom","payload":{"namespace":"gobot.ui","version":1,"command":"timer.start","duration_ms":300000}}
```

| Command | Поля |
|---|---|
| timer.start | duration_ms, integer 1..86400000 |
| weather.show | text, <=400 символов |
| status.show | text, <=400 символов |
| music.now_playing | text, <=400 символов |
| notification.show | text, <=400 символов |

Namespace/version/command/extra fields/duration валидируются. MockUIRenderer.enqueue ставит команду
в очередь <=16; gui_tick применяет состояние. Firmware callback уже использует Application::Schedule;
LVGL widgets надо обновлять в GUI/display task с DisplayLockGuard, не в network callback.
Upstream custom handler показывает JSON как system chat text. Candidate firmware patch показывает
простую текстовую карточку через тот же Schedule; полноценные timer ticks/native widgets ещё не реализованы.

## Images / MCP

self.screen.preview_image в main/mcp_server.cc — user-only, внутри HAVE_LVGL + CONFIG_LV_USE_SNAPSHOT.
По умолчанию скрыт из tools/list; params.withUserTools=true включает user tools. Это не заменяет consent.

```json
{"type":"mcp","payload":{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"self.screen.preview_image","arguments":{"url":"http://127.0.0.1:18784/images/<capability>"}}}}}
```

ImageStore строит такой вызов только при capability/permission и minted URL. Baseline JPEG 240x240,
<=65536 bytes, image/jpeg, точный Content-Length, TTL <=60 s, origin/SSRF guards. Произвольные внешние
URL не скачиваются. Loopback URL применим только для host tests: ESP32 его на хосте не получит.
LAN origin/firewall включаются отдельно после доставки; control plane остаётся loopback.
Текущий firmware preview аллоцирует HTTP тело: до physical test нужны его дополнительные size/MIME/
origin/redirect guards. Полосовое декодирование пока не требуется измерениями; JPEGDEC/esp-iot-solution
не внедрялись. Отдельного JPEG binary WS канала нет.

Host image API: POST http://127.0.0.1:18784/api/v1/images с локальным Bearer и Content-Type: image/jpeg,
raw baseline JPEG body. Возвращает capability URL на 30 s; GET проверен network E2E с точным MIME/Length.
Это не даёт ESP32 доступа к loopback и не выполняет MCP на физической плате.
