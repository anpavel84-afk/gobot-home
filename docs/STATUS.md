# Фактический результат

| Требование | Факт |
|---|---|
| Новый git / .venv / lock / запуск | Созданы, только GoBotHome |
| Health / русский SSE / SQLite | Unit + network mock E2E passed |
| Host Bridge | Запущен loopback, HMAC в обе стороны, mock task E2E passed |
| Upstream voice | SHA закреплён, старт blocked aioconsole/Torch 2.2.2 на Python 3.14 |
| CLI adapters | Codex lifecycle, Cursor/Gemini parser, subprocess fixtures реализованы; live admission закрыт |
| Fast cloud | Guarded OpenAI-compatible streaming код, без реальных calls |
| Русская речь | ASR fixture → router → stream → silence TTS fixture, порядок предложений проверен |
| ASR/TTS/VAD | Upstream interfaces изучены; RU async/mock overlays подготовлены; real models не проверены |
| Framing | v1/v2/v3 fixture tests; physical/upstream interop неизвестен, initial production target v1 |
| UI / Images | JSON contract/mock GUI queue и capability/user permission/SSRF policy tested |
| Firmware | Profile/pins проверены source, candidate patch apply-check; ESP-IDF build/device не проверены |
| HA / Music | Только read-only interfaces/mocks, опасные команды запрещены |
| Reliability | Cancel/timeout/fixture descendants/concurrent sessions/restart memory/network disconnect passed |
| Docker | Отсутствует; контейнеров GoBot нет, Docker restart не проверен |

Блокеры: физическая плата, совместимый upstream Python/Torch, voice models/API permission,
проверенный OS containment для live CLI, Docker/topology при выборе контейнеров.
Полного подтверждения production voice MVP нет; доступная программная mock-часть создана и запущена.
