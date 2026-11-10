# Зависимости

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
