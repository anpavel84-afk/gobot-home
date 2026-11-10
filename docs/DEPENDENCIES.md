# Зависимости

Актуализация 10 ноября: project-local Antigravity 1.5.3 (antigravity.lock.json),
Codex 0.159.2. Gemini CLI ниже — архив попытки, не активный провайдер; Gemini API
не используется. num2words 0.5.14, pymorphy3 2.0.6, tiktoken 0.14.0 — Speech/Context.
SpeechBrain 1.1.2 и парные Torch/Torchaudio 2.11.0 в .venv-speaker.
OpenAI speech probes уже выполнены: openai-speech-probes.json.

Актуализация browser voice: официальный npm @google/gemini-cli **0.67.0**, package-lock.json
в services/agent-bridge/gemini-cli; установлен --ignore-scripts, без global/npm auth изменений.
Codex native **0.159.2** из существующей установки, schema tag rust-v0.159.2. Runtime binary/policy SHA
проверяются по локальному run/agent-isolation.json. Remote HEAD ниже не подменяет runtime release.
faster-whisper 1.2.1 / CTranslate2 4.8.5 / Piper 1.8.0; requirements-audio.txt и audio-models.lock.json.
Sherpa-onnx 2.0.1 сохранён, но его TTS frontend на этом Windows не дал samples; рабочий Denis — Piper.
Основной OpenAI TTS: gpt-realtime-2.1-mini по текущей официальной документации; paid probe ещё не выполнен.

| Репозиторий | Commit SHA | Проверка |
|---|---|---|
| xinnan-tech/xiaozhi-esp32-server | `4b1a54a41c28112bc06b1ab605d2ba723f678ad3` | source checkout + inspection |
| 78/xiaozhi-esp32 | `a73e9a7e266e3196d1368ba46c30bee0d81f0a64` | source checkout + inspection |
| openai/codex | `caae161dd0c82f2e04e57e6f9d738fafbce503ba` | README/protocol/schema |
| google-gemini/gemini-cli | `1930f25394c4b6338b64ffdb43083fca41614798` | README/protocol/schema |
| anyrobert/cursor-api-proxy | `38a5c91bca54947bc4df049d9b2a943f969a0c3c` | partial source/README |
| Adolanium/hermes-gadget-sdk | `56941f79cce112c3a05f2d93015b64f51f9a19e7` | partial source/README |
| BerriAI/litellm | `c76a95fc7e83f5e0a326ec9a60d138ca821711ff` | remote metadata only; not installed |
| espressif/esp-iot-solution | `90fcf2170c3ea1c7f8a19b49d58a8557781e5457` | remote metadata only; not installed |
| bitbank2/JPEGDEC | `32132971bcc032b5b14f1e1e968c242d8d986854` | remote metadata only; not installed |

Машиночитаемый lock: dependencies.lock.json. Host graph: requirements.lock.txt, отдельный Python 3.14.4 venv.
Vendor исключён из git; restore_sources.py восстанавливает точные SHA. Локальный Codex 0.159.2 имеет
сгенерированную schema в vendor/references/codex-schema; remote HEAD не считается его binary release.

## Первичные ссылки

- [Firmware WS](https://github.com/78/xiaozhi-esp32/blob/a73e9a7e266e3196d1368ba46c30bee0d81f0a64/docs/websocket.md),
  [MCP](https://github.com/78/xiaozhi-esp32/blob/a73e9a7e266e3196d1368ba46c30bee0d81f0a64/docs/mcp-protocol.md),
  [Tools](https://github.com/78/xiaozhi-esp32/blob/a73e9a7e266e3196d1368ba46c30bee0d81f0a64/main/mcp_server.cc).
- [Server config](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/4b1a54a41c28112bc06b1ab605d2ba723f678ad3/main/xiaozhi-server/config.yaml),
  [WS](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/4b1a54a41c28112bc06b1ab605d2ba723f678ad3/main/xiaozhi-server/core/websocket_server.py),
  [Connection](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/4b1a54a41c28112bc06b1ab605d2ba723f678ad3/main/xiaozhi-server/core/connection.py).
- [Official Codex App Server](https://learn.chatgpt.com/docs/app-server),
  [Source](https://github.com/openai/codex/tree/caae161dd0c82f2e04e57e6f9d738fafbce503ba/codex-rs/app-server).
- [Gemini headless](https://github.com/google-gemini/gemini-cli/blob/1930f25394c4b6338b64ffdb43083fca41614798/docs/cli/headless.md),
  [Cursor output format](https://cursor.com/docs/cli/reference/output-format).
- [Cursor proxy](https://github.com/anyrobert/cursor-api-proxy/tree/38a5c91bca54947bc4df049d9b2a943f969a0c3c),
  [Hermes](https://github.com/Adolanium/hermes-gadget-sdk/tree/56941f79cce112c3a05f2d93015b64f51f9a19e7).

## Воспроизводимый blocker upstream

requirements.txt закрепляет torch==2.2.2, torchaudio==2.2.2, numpy==1.26.4, websockets==14.2,
рекомендует Python 3.10. На хосте 3.14.4. app.py завершается ModuleNotFoundError aioconsole;
pip install --dry-run --no-cache-dir --only-binary=:all: torch==2.2.2 не находит distribution для 3.14.
Очищенные stderr: upstream-import.txt и upstream-torch-check.txt. Одной установки aioconsole недостаточно.
Нужна отдельная совместимая Python 3.10 среда, dependency solve и voice models. Глобальный Python не менялся.
Docker отсутствует; контейнерное исправление не проверено.

LLM factory реально ищет core/providers/llm/<type>/<type>.py, LLMProvider.response(session_id,dialogue).
ASR async speech_to_text(opus_data,session_id,artifacts) получает upstream PCM artifacts 16 kHz;
TTS async text_to_speak(text,output_file), затем upstream resample/Opus. Silero VADProvider.is_vad(conn,data),
ONNX CPU. Plugins используют register_function/ToolType/ActionResponse. Их исполнение отключено:
Intent=nointent, plugins/внешний MCP/manager-api исключены из генерируемой базы.

Cursor proxy изучен частично: README, spawning/account/reset code paths. Есть optional force mode и
account management; полного аудита нет, пакет не установлен и авторизованные конфиги не подключались.
Hermes имеет experimental Spotpear profile и предупреждение о physical verification; ориентир для
карточек/привилегированных подтверждений, не доказательство работы платы. LiteLLM — optional direct API
router, не CLI adapter, не установлен. JPEGDEC/esp-iot-solution не внедрялись. faster-whisper/sherpa/Piper
и русские models не устанавливались; для Piper требуется проверка GPL/лицензии голоса. ASR по сегментам
не объявляется token streaming, sentence WAV TTS не объявляется проверенным streaming audio backend.
# Visual Pipeline — 10 ноября 2026

Новых Python/Node пакетов и глобальных установок нет. Используются закреплённые
Pillow, httpx, Pydantic и SQLite из существующего requirements.lock.txt.
Основной внешний источник — [Openverse API v1](https://api.openverse.org/v1/),
без OAuth/API ключа. Изображения каталога, авторы, лицензии, source URLs и SHA-256
миниатюр закреплены в services/brain/visual-catalog.json. Сервисный API — внешняя
зависимость без git SHA; отказ/изменение снимка даёт честный fallback. Прямой
Wikimedia адаптер подготовлен отдельно, на этом хосте получен HTTP 403.
Политика/проверки: VISUAL_PIPELINE.md, visual-e2e.json. Upstream SHAs не менялись.

## Device / Multimodal response — 10 ноября 2026

Новых runtime Python/Node пакетов нет. Device renderer — собственные canvas/CSS
примитивы; иконки PWA процедурно созданы в проекте, не семейные фотографии.
Процедурные схемы используют существующий Pillow. Neural imagegen не подключён.
Wake detector не установлен: English pretrained openWakeWord не подтверждает
русское «ГоБот»; sherpa_onnx сам по себе не предоставляет проверенную KWS-модель.

Опциональный русско-английский noun/adjective lexicon: FreeDict/WikDict rus-eng
2025.11.23, 33717 headwords, CC BY-SA 3.0. Source archive:
https://download.freedict.org/dictionaries/rus-eng/2025.11.23/freedict-rus-eng-2025.11.23.src.tar.xz
SHA512: `9adf7a5eda27ccfa3e496b86b2fd575fc0e4af7ac5626a219d44e4ebfd56280deaf67cefd995ab04e9d7ef415e88f8cf0f9cae3252da6221376fd6d0c39012ba`.
Программа scripts/prepare_visual_dictionary.py проверяет checksum, извлекает
только ограниченные TEI/COPYING members без tar extraction, записывает provenance,
license и описание преобразования. Archive/lexicon/license — ignored vendor/dictionaries.
Словарь помогает image query, не ограничивает поддержку только включёнными словами.
Без него исходный русский запрос остаётся best-effort путём Openverse.

TTS WS reuse: официальный out-of-band response.create с conversation:none и custom
input, https://developers.openai.com/api/docs/guides/realtime-conversations .
Новая оптимизация проверена fixtures, не новым платным API probe.
