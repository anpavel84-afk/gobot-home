# M1: измерение задержки по спецификации v0.2

Продуктовый источник — [GOBOT_HOME_TARGET_SYSTEM.md](GOBOT_HOME_TARGET_SYSTEM.md),
96e0f3d. Это evidence текущего M1, не новая концепция. Полная короткая матрица:
[REQUIREMENTS_MATRIX.md](REQUIREMENTS_MATRIX.md).

## База и путь запроса

Начало: чистая master bd487ff. Docs-only fast-forward до 96e0f3d сохранил дерево
рабочего кода; службы ради Markdown не перезапускались.

Capture stop → MediaRecorder finalization → gateway upload → OpenAI file STT или
отдельный live WS → финальная транскрипция → chat gateway/profile → Brain queue,
memory, context/router → подписанный Bridge → CLI spawn/init/prompt/raw/assistant
delta → SentenceBuffer → SpeechFormatter → SpeechTurn → PCM SSE → browser decode,
schedule → estimated nonzero output → playback end.

Раньше file STT и chat измерялись отдельно. llm_first_token_ms включает подготовку
Brain; first_audio_server начинается после STT. Исторический
voice-latency-baseline.json сохранён: это не текущая сборка и не iPhone TTFA/p95.

Теперь trace_id связывает utterance/request/turn и отдельные clock domains:
gateway-stt, gateway-chat, Brain, Bridge и client_monotonic. Часы разных процессов
не вычитаются. Параллельные этапы не суммируются. Code/config fingerprint и
исходный Git HEAD закрепляются при запуске процесса. Route/model/context estimate,
concurrency, voice/transport и доступные usage отделены от неизвестных inference,
file-STT TLS и физического звука.

Трассы без текстов, stdout, токенов и аудио: data/telemetry.sqlite, до 2000 записей,
live registry до 128. Owner фильтруется до чтения. Client events — числовой allowlist
с revision против поздней доставки. Это недоверенная диагностическая телеметрия,
не авторизация и не акустическое доказательство. Подробности спрятаны в диагностике.

## Измеренное исправление

Четыре свежих процесса кода bb4a804: metadata/hash admission 522–551 мс;
повторная обязательная проверка после прогрева 7.4–7.9 мс. Brain и Bridge прогревают локальные
метаданные в lifespan до readiness. Проверка каждого запроса и invalidation по
изменению файлов сохранены. [Raw](admission-profile-v02.json). Ноль model calls и
CLI spawns в benchmark. Это локальный overhead первого запроса, не доказательство
устранения основной паузы. При n=4 репрезентативный p95 не заявляется.

agy help подтверждает несколько turns в stream-json, но безопасный reset истории
не подтверждён. Процесс не объединяет независимые вопросы. Codex сохраняет новые
ephemeral threads; новый process pool без измеренного основания не введён.
Offline isolation audits не вызывали реальных моделей; tool deny сохранён.

## Локальный фидбек

В /device принятый stop включает waiting и предвычисленный 80-мс earcon. Через
2250 мс ожидания допустим один предзагруженный «Секунду…». Порог 2000–2500 мс,
quiet/mute/volume и выключение сохраняются в профиле сервера. Основной голос —
OpenAI. Static Piper Denis sample используется только как служебный filler.
Происхождение, CC0 dataset/output и hash: [feedback-asset.json](feedback-asset.json),
[model card](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/denis/medium/MODEL_CARD),
[Piper engine](https://github.com/OHF-Voice/piper1-gpl). Платного создания клипа нет.

Готовый полезный PCM отменяет pending filler; звучащий затухает за 40 мс.
Cancel/error/hidden/new recording/storage scope change очищают его. Прогресс
«подбираю визуал» больше не вызывает отдельный TTS. Нулевые PCM, earcon и filler
не закрывают полезный TTFA. AudioContext timeline/onended оценивают output,
но не заменяют физическое измерение первого слова в комнате.

## Проверки и блокеры

528 pytest, включая девять M1-тестов. Node fixtures проверяют threshold/ready race,
preemption, quiet, silent first payload, отмену, bounded ACKs. Полный локальный
transport fixture связывает file STT, gateway, Brain и TTS. Новый HTTPS smoke:
[latency-fixture-v02.json](latency-fixture-v02.json), STT/LLM mock и TTS off;
ноль постоянных тестовых сообщений и платных запросов. HTTP driver — не iPhone.

- Реальный input_closed → heard speech текущего кода: не измерен.
- Реальные waiting/earcon менее 150 мс на iPhone: не измерены.
- Главный вклад в реальную долгую паузу: пока не установлен.
- Provider warm/cold comparison: не выполнен без нового profiling budget.

Филлер не закрывает R-082/AC-35. Запрошены два коротких реальных цикла для
диагностики и подтверждения исправления. Подготовлен scripts/profile_voice_once.py:
без отдельного явно разрешённого remaining budget он не делает платных вызовов;
один запуск — один цикл без retries и heavy fallback, с short response cap.
Новые real probes этого прохода: 0. API key/UI consent не подменяют test budget.

Бесплатно: pytest; node tests/feedback_timing.cjs; node tests/client_playback_timing.cjs;
scripts/profile_admission.py; scripts/e2e_latency.py. На iPhone открыть прежний
private HTTPS /device, обновить страницу и включить GoBot. Собственные обычные
запросы используют выбранные владельцем consent flags; trace виден в диагностике.

M2 child lock/profile ACL и M3 PageImages/prefetch/relevance остаются открытыми.
Этот проход не выдаётся за выполнение AC-27…34 или всей спецификации v0.2.

Идемпотентность: смена диагностического trace_id не меняет смысл request и не
создаёт повторного вызова. Nullable profile_epoch не ломает прежний payload digest;
содержательно другой запрос с тем же идентификатором по-прежнему отклоняется.
