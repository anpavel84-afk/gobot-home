# Измерения mock-контура

Актуальные результаты 10 ноября: context-evaluation.json, router-evaluation.json,
openai-speech-probes.json, browser-free-e2e.json и CONTEXT_EVALUATION.md.
Таблицы ниже — исторические mock-измерения, не характеристики реальных моделей.

Network E2E Windows host: 20 последовательных запросов, loopback SSE, SQLite WAL, mock deltas
с искусственным asyncio sleep. Это fixture throughput, не скорость реальной LLM/речи. Raw: e2e-results.json.

| Метрика | p50 ms | p95 ms | n |
|---|---:|---:|---:|
| Первый mock delta от HTTP запроса | 22.15 | 23.83 | 20 |
| Полный mock текст от HTTP запроса | 146.81 | 149.55 | 20 |

| Реальный этап | Статус |
|---|---|
| VAD | Не измерен |
| STT | Только константная ASR fixture |
| LLM first token | Только mock delta |
| TTS first chunk | Только silence/comfort fixture |
| First Opus playback | Нет устройства/ACK, неизвестно |
| Speech e2e p50/p95 | Не измерено |

StageMetrics поддерживает все стадии; неизвестные остаются null. Brain final содержит
llm_first_token_ms/total_ms. При hardware test привязать стадии к correlation/device/turn,
измерять конец PTT и настоящее начало playback. Получение WS frame не равно звуку.
<800 ms — гипотеза исследования. Half-duplex/PTT сначала, wake word/full-duplex позже.

46 unit tests passed на момент документации; один Starlette TestClient/httpx deprecation warning.
reliability-results.json: host restart, SQLite survival, SSE disconnect passed.
Docker restart, GPU inference и реальные API/CLI не проверялись.
# Дополнение browser voice 2026-11-09

Один бесплатный HTTPS probe, синтетическая WAV длительностью 3.019 s (не микрофон): Whisper Small CPU int8
распознал русский текст за 1139 ms без включения model load в STT timer. Полный запрос STT -> mock LLM ->
реальный явно выбранный резерв Piper Denis дал первый PCM chunk через 4115 ms от начала HTTP STT запроса;
полный server stream завершился за 4332 ms, 22 чанка по порядку. Browser playback latency не измерялась.
Это n=1, p50/p95 для реального голоса не оцениваются. Результат docs/browser-free-e2e.json.
OpenAI TTS, live CLI first token, микрофон iPhone, first physical Opus playback остаются неизмеренными
до соответствующих разрешённых проб. Меньше 800 ms не заявляется. Исходные mock-метрики ниже отдельны.

## Визуальный слой — 10 ноября 2026

431 pytest, Node visual DOM/microphone units; 240 synthetic router cases,
200-turn synthetic context day. Реальные бесплатные public-image HTTPS проверки
в visual-e2e.json: 12 сценариев + повторный cache hit. Это HTTP/контрактная
проверка, не подтверждение рендера/аудио на физическом iPhone.

60 warm-cache обращений VisualService без сети/моделей: p50 4.67 мс,
p95 8.85 мс. Учитывается локальный cache lookup + DTO; не download,
не TTS и не end-to-end время до звука. Проверенные фото device JPEG: 9804–12988 байт,
240×240 baseline, browser 600×449 без увеличения оригинала. Схема — 5425 байт device.

Private HTTPS полный visual response на прогретых фото в последнем прогоне:
- oxheart: 841.6 мс.
- labrador: 191.7 мс.
- raspberry-pi: 185.6 мс.
- repeat_oxheart: 189.8 мс.

Это единичные наблюдения, не p95 сети и не cold-source benchmark. Первый запрос
после рестарта также включает инициализацию процесса. Новых платных вызовов,
CLI-квоты или speech API в этих проверках: 0. Openverse anonymous source не требует
ключа; сетевые обращения ограничены локальным бюджетом. Общий image retrieval
не проходил representative quality eval; исходная ошибка HTTP 406 исправлена, кратер/подсолнух загружены; см. VISUAL_PIPELINE.md.
