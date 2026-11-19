# GoBot: аудит единого разговорного и экспертного тракта

**Дата:** 18 ноября 2026, America/Sao_Paulo. **Назначение:** доказательная основа задания HOST-INTEGRATOR. **Статус:** аудит исходников, официальных протоколов и прежнего аппаратного отчёта; новая объединённая архитектура этим документом не объявляется установленной.

## 1. Уровни доказательств и исходная точка

| Метка | Значение |
| --- | --- |
| CODE_PRESENT | Механизм найден в опубликованных исходниках. Его работа в текущей приватной установке отдельно не подтверждена. |
| HARDWARE_REPORT | Операция или измерение зафиксированы прежним аппаратным отчётом; это не новый аппаратный прогон данного аудита. |
| OWNER_REPORTED | Владелец сообщил результат личной проверки. Это ценный пользовательский результат, но без автоматически приписанных статистических метрик. |
| PROPOSED | Целевая доработка или критерий проверки; реализации и аппаратного результата пока не заявлено. |

Проверяемые опубликованные точки:

| Источник | SHA / база |
| --- | --- |
| Default branch master | fcbfeaa5271bf0fb9e1e2488faea5003ded9166b |
| HOST-A, PR #8 | 4b51e8b1b881855372479cad6c9f8a721a0877be; base feat/host-wake-streaming |
| HOST-B Sophia, PR #12 | 410bbd7365ca670c619efb0b3df926c47ff39e3d; base feat/host-wake-lab-public |

На PLAN существует более новая незакоммиченная работа HOST-A. В частности, Issue #5 содержит сообщения о browser follow-up и metered accounting v2 [G1–G2]. Поэтому опубликованный PR #8 — источник доказательств, **не разрешение заменить им рабочую директорию**. Исполнитель сначала сопоставляет реальные файлы, процессы, настройки и версии. Документационная ветка от master служит публикации задания, а не выбору базы интеграции.

Репозиторий публичный. Секреты, персональное аудио, полные пользовательские транскрипты, дампы Flash, приватные бинарники и официальные модельные веса в него не добавляются. После реализации обновляется единственный фактический паспорт проекта — `docs/CURRENT_STATUS.md`; отдельная конкурирующая система статусов не вводится. Порядок реализации и развёртывания задан в [EXECUTOR_PROMPT.md](EXECUTOR_PROMPT.md).

## 2. Подтверждённая аппаратная база Sophia

**HARDWARE_REPORT:** отчёт от 17 ноября фиксирует реальную установку версии **0.4.13-dev-host-b-sophia-active-v3**, ESP-IDF 6.0.1, ESP-SR 2.6.2. Использована официальная английская модель WakeNet10 **wn10_sophia**, встроенная в APP; это не обученные русские веса «Моника» [C1].

| Параметр V3 | Значение из отчёта |
| --- | --- |
| Размер приложения | 3 668 224 байта |
| SHA-256 | 0d7bd0f65ff4a649eff16660f8bd1ee441a16314ca5bb4ecf7135e0dbd22fadd |
| Ёмкость app-раздела | 4 128 768 байт |
| Номинальный остаток | **460 544 байта** |
| Размещение | Существующий OTA0; дополнительный model-раздел не потребовался |

Отчёт описывает app-only запись, последующую проверку Flash и сохранение разметки, NVS, assets и OTA-метаданных. Прежняя оценка свободного места RC1-r3 около 1 МиБ для текущего V3 уже неприменима. Эти значения нужно сверить с реально установленным образом перед следующей записью.

**OWNER_REPORTED:** позднее владелец сообщил, что «София» уверенно активирует колонку тихо, громко и издалека. Это обновляет пользовательское свидетельство после старого отчётного HUMAN_ACCEPTED=NO. Однако recall, false wakes/hour, p50/p95 и нагрузка новой объединённой схемы не измерены.

**CODE_PRESENT:** V3 использует тот же микрофонный PCM и локальную очередь с **2 секундами pre-roll**. Это отличается от планируемого pre-roll PLAN 0,5–1 с. Нельзя последовательно добавлять оба окна и тем самым повторять звук. В опубликованном патче HOST_ON отключает локальную Софию; совместный непрерывный HOST-поток требует изменения этого переключателя [C2].

## 3. Главные технические расхождения

**CODE_PRESENT:** нынешний B передаёт звук через LocalMediaRelay/LiveKit и WebRTC; облачный WS, присоединённый по call_id, является управляющим. Входной трек выдаёт PCM с темпом 1×. Поэтому новый **B_WS** должен быть прямым аудиотранспортом Realtime, а не переименованием существующего sideband [C3]. Утверждение относится к нашему коду, а не ко всем возможным реализациям WebRTC.

**CODE_PRESENT:** Opus-пакет Gateway имеет длительность **60 мс**. Два–три таких пакета составляют 120–180 мс. В проверенном upstream XiaoZhi output task начинает работу при первом готовом блоке; максимальная ёмкость очереди сама по себе не доказывает накопление полусекунды перед стартом [C4]. Частная установленная прошивка требует отдельной сверки.

**PROPOSED:** сначала измерить фактический decoder/output/DMA тракт. Не добавлять обязательное ожидание двух–трёх пакетов. Переход на 20 мс — отдельное согласованное изменение обеих сторон, если замеры покажут пользу; не условие первого прототипа.

## 4. Совместимость облачных протоколов

### Realtime: ожидание, burst и endpointing

Документация разговорного Realtime не тарифицирует само соединение и сеть; затраты возникают при Responses, отдельно учитывается транскрипция. В ожидании не отправляем аудио, включая нулевые PCM-кадры, не создаём ответы и отключаем автоматические idle-реплики [O1]. Это не тариф разговорного GPT-Live, где оплачивается активная длительность с молчанием и ожиданием backend.

Предел Realtime-сессии — 60 минут; обновление на 50–55-й минуте является нашей политикой с запасом. Готовность означает подтверждённую конфигурацию session.updated, а не гарантию заранее выделенного вычислительного ресурса [O2].

input_audio_buffer.append допускает порционную быструю отправку записанного звука; отдельный append ограничен 15 МиБ. Подтверждения каждого append нет. Поэтому pre_roll_flushed означает завершение клиентской отправки диапазона, **не обработку этого диапазона сервером**. Короткий burst допустим протоколом; реальная скорость обработки проверяется измерениями. После pre-roll не отправляется commit: живая часть продолжает ту же реплику [O3].

semantic_vad регулируется eagerness. high не гарантирует отсечку за 300–500 мс: при неопределённости возможен timeout до 2 с. silence_duration_ms относится к server_vad [O3–O4]. Предлагается сравнить semantic high и server VAD 400–500 мс на одинаковых коротких вопросах; не складывать ожидания ESP, Gateway и облака.

### Live Transcribe

gpt-live-transcribe использует WS с intent=transcription, session.type=transcription, PCM16 mono 24 кГц и turn_detection=null. Серверные semantic_vad/server_vad этой моделью не поддерживаются: конец реплики определяет наш контроллер, затем отправляет commit и получает финальный текст по item_id [O5].

Тариф на дату проверки — **$0,017 за минуту входного аудио**. Usage duration описывает длительность входа; нельзя автоматически считать каждую секунду пустого сокета платной транскрипцией [O6–O7]. В проектируемом тракте STT всё равно закрывается после final. Длинные экспертные диктовки требуют своего endpointing и пересмотра локального лимита адаптера 60 с.

### Единый голос и диктор

marin присутствует в Realtime и gpt-4o-mini-tts. Один voice ID не доказывает неразличимость тембра и интонации между моделями; требуется прослушивание [O2, O8]. gpt-4o-mini-tts и его snapshots отключаются **6 января 2027**; официальный переход — gpt-realtime-2.1-mini через Realtime API, не через старый /audio/speech [O8–O9].

**CODE_PRESENT:** GoBot уже использует именно Realtime-mini narrator: отдельный текстовый input, conversation=none, инструменты отключены, инструкция читать текст, выход PCM24k [C5]. Его следует переиспользовать. Старый Speech API стримит выходное аудио, но получает целиком текст каждого запроса; он не принимает будущие токены Codex в уже начатый запрос [O10].

### Soniox: исследованная альтернатива, не обязательная реализация

FAQ Soniox рекомендует накопить звук до подключения и немедленно отправить накопленные фрагменты после конфигурации. Одновременно требования cadence допускают короткое накопление, но предупреждают об отключении при продолжительных bursts/отставании [S1–S2]. Разрешение короткого pre-roll нельзя переносить на минутный буфер с произвольной скоростью.

Soniox позволяет заранее авторизовать WS до start, поддерживая keepalive и занимая connection slot. Документация тарифицирует полную длительность активного потока; однозначной гарантии бесплатности стадии до start в проверенных материалах нет [S3–S4]. Подключать Soniox, создавать учётную запись или вводить дополнительный сервис в данный прототип не требуется.

## 5. Что уже реализовано в экспертном тракте

| Компонент, CODE_PRESENT | Что найдено | Разрыв до целевого поведения |
| --- | --- | --- |
| stt.py | Live Transcribe, deltas/final, commit | Подключение общего PCM и экспертного endpointing; локальный лимит 60 с |
| bridge.py | Локальный подписанный NDJSON text_delta | Сохранить phase, item_id, job_id вместо потери семантики |
| live_agents.py / agents.py | Codex app-server через stdio, ephemeral thread, дельты | Проверить установленную версию, фильтровать пользовательский ответ по фазе |
| expert_jobs.py | Приём, квота, контекст, отмена, usage | execute собирает **весь** текст; ранняя озвучка отсутствует |
| pipeline.py / SpeechFormatter | Очереди предложений и аудио, произношение, отмена | Подключить поток эксперта к существующему pipeline |
| audio.py | Realtime-mini, marin, одна WS на несколько предложений ответа | Подготавливать параллельно Codex, унифицировать стиль |
| speech_openings.py / voice_library.py | Кеш, метаданные, SHA, без генерации при cache miss | Проверить наличие конкретного клипа на PLAN и доставку на ESP |
| memory.py / expert_store.py | Временный контекст и условное постоянное сохранение | Синхронизировать внешний экспертный ответ с новым/живым Realtime |

Исходники: [C5–C10]. Наличие инвентаря кеша не подтверждает наличие WAV-файла. Наличие streaming адаптера не доказывает сквозную потоковую озвучку: текущий ExpertJobs её блокирует накоплением результата.

**Критический lifecycle:** RealtimeManager.close вызывает experts.close; это отменяет queued/running задачи. Проверка владельца также отвергает закрытую сессию. Схема «начать эксперта, закрыть B и ждать ответ» в этом пути не работает [C3, C7]. Задача должна принадлежать логическому разговору Brain независимо от транспорта.

## 6. Целевая интеграция, PROPOSED

### Захват и точная граница аудио

Один I2S/PCM producer обслуживает локальную Софию и Opus. Ограниченные очереди не позволяют сети задержать детектор. Кадры несут stream_epoch, frame_id, sample_start, sample_count; wake содержит позицию детектора и идентификатор события. Нужна явная привязка между capture clock, AFE и пакетизацией, а не номер последнего отправленного пакета. Позиция срабатывания детектора не равна точной акустической границе имени; достаточность выбранного pre-roll проверяется на слитных фразах.

PLAN декодирует Opus последовательно, хранит PCM-кольцо 10 с с настройкой до 60 с. Один cursor передаёт выбранный pre-roll, накопившийся хвост и живое продолжение без повторов и пропусков. Начальная настройка pre-roll — 1 с; 0,5 с проверяется отдельно. Переподключение меняет эпоху; отсутствие диапазона не скрывается склейкой чужих фрагментов. Кольцо не является ограничением длительности вопроса.

### Вход к эксперту и ожидание

Обычная фраза «София, спроси у Кодекса…» сначала понимается быстрым Realtime. Уже принятую задачу не нужно повторно транскрибировать. Для прямого дешёвого длинного ввода пользователь заранее выбирает эксперта командой или интерфейсом; следующая реплика поступает в Live Transcribe. WakeNet сам по себе не распознаёт выбор исполнителя.

Автоделегирование использует существующие серверные инструменты Brain и разрешённый профиль анализа. Идемпотентный job_id предотвращает повторный запуск. Приём задачи, исходные ограничения и полномочия определяет Brain; модель не расширяет права CLI.

После завершения пользовательской реплики и принятия задачи воспроизводится готовый marin-клип. Codex и диктор готовятся параллельно; разговорный WS остаётся пустым. Служебная фраза не генерируется заново при каждом обращении. Окончание клипа не переводит устройство в follow-up, пока эксперт ещё работает.

### Ответ по частям и возврат

Codex App Server различает agentMessage phases commentary, partial_answer и final_answer; phase может отсутствовать. partial_answer обозначает устойчивый текст ответа [O11]. Адаптер обязан сохранить item lifecycle и озвучивать только проверенный пользовательский ответ. Служебный stdout, инструментальные события и reasoning исключаются.

Первая законченная речевая часть проходит Speech Formatter и диктор; полный ответ параллельно собирается в Brain. Одна очередь вывода объединяет native audio, клипы и narrator, исключая наложение и поздние чанки отменённого ответа. Генерация, конец отдельного чанка и физическое завершение всего ответа — разные события.

Следующее окно 6–8 с тишины открывается после playback_finished всего ответа и защитной паузы. Начало его допустимого аудиодиапазона исключает звук колонки. Начавшаяся вовремя речь не обрезается истечением этого таймера.

## 7. Контекст, память и однократность результата

Канонический контекст хранит Brain: conversation_id, turn_id, job_id, профиль, исходную задачу, результат эксперта, речевую версию и фактически проигранную часть. Смена сокета не меняет идентичность разговора. При отмене незвучавшая часть не помечается как услышанная.

remember=false уже означает временную историю RAM, а не немедленное забывание. В проверенной реализации выбираются последние шесть завершённых реплик того же разговора возрастом до часа; постоянный ExpertStore требует remember и подтверждённый профиль [C10]. Итог эксперта должен явно попасть в этот контекст; универсальная синхронизация любого нового Realtime сейчас не реализована.

Если expert_start уже получил accepted как function_call_output, нельзя отправлять второй и третий output на тот же call_id. Завершение оформляется уведомлением соответствующего job_id и обновлением контекста. После внешней озвучки не создаётся ещё один Realtime Response с тем же ответом. Новая сессия восстанавливается из Brain, а не получает неизвестный ей старый call_id. Разговор продолжает следующая пользовательская реплика.

Временность распространяется на Codex thread, журналы и кеш пользовательского TTS. Публичные служебные клипы сохраняются отдельно. remember=false не является обещанием отсутствия хранения у облачного провайдера. CLI запускается локально, но это не утверждение об офлайн-инференсе или бесплатной модели.

## 8. Измерения и ограничения развёртывания

Обязательные точки: wake_detected, pre_roll_flushed, end_of_speech, endpoint_decided, first_audio_packet, speaker_sound_started. Дополнительно: cloud_ready, ui_visible, playback_finished, expert_job_accepted, cached_cue_started, codex_first_answer_delta, first_speakable_chunk, narrator_first_audio, expert_context_synced.

Главная задержка — конец речи → первый слышимый содержательный ответ, с p50/p95 и количеством испытаний. Клип не заменяет этот результат. I2S write не объявляется акустическим стартом без калибровки; часы ESP/PLAN не вычитаются без сопоставления [C11]. Порог UI <50 мс и endpointing 300–500 мс — цели, не измеренные достижения. География и RTT сохраняют свой вклад.

Проверяются слитное имя с вопросом, имя с паузой, длинная диктовка, отмена, reconnect/rotation во время эксперта, отсутствие повторного ответа, remember=false и переход между голосами. Новая схема должна иметь rollback на проверенную рабочую базу, а не требовать изменения partition table по умолчанию.

Конечный B-grant от 17 ноября 3×60 с / $1 estimated / 2 часа исторический и истёк; он не даёт текущего разрешения на расход. Оценка в интерфейсе, в том числе $60, сама по себе не бюджетное разрешение. Старые C-запуски с неподтверждённой финализацией остаются учтёнными и блокированными; новый тракт их не требует [C1]. Аудит не менял лимиты, не запускал платные модели и не прошивал устройство.

## 9. Источники

Публичные ссылки ниже фиксируют доказательную базу. API-параметры и доступ аккаунта повторно сверяются исполнителем перед развёртыванием.

| ID | Первичный источник |
| --- | --- |
| G1 | [Issue #5: metered accounting v2](https://github.com/anpavel84-afk/gobot-home/issues/5#issuecomment-6966632817) |
| G2 | [Issue #5: browser follow-up](https://github.com/anpavel84-afk/gobot-home/issues/5#issuecomment-6957321046) |
| C1 | [Sophia V3 hardware report](https://github.com/anpavel84-afk/gobot-home/blob/410bbd7365ca670c619efb0b3df926c47ff39e3d/services/voice/host_wake_lab/sophia_embedded/HARDWARE_SOPHIA_V3_2026-11-17.md) |
| C2 | [Sophia integration patch](https://github.com/anpavel84-afk/gobot-home/blob/410bbd7365ca670c619efb0b3df926c47ff39e3d/services/voice/host_wake_lab/sophia_embedded/integration/sophia_v3_active_wake_SOURCE_ONLY.patch) |
| C3 | [Device Realtime transport](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/voice/spotpear_realtime.py), [paced input](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/voice/spotpear_live.py), [Realtime lifecycle](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/realtime.py) |
| C4 | [Gateway Opus](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/voice/gobot_device_gateway.py), [pinned XiaoZhi audio service](https://github.com/78/xiaozhi-esp32/blob/a73e9a7e266e3196d1368ba46c30bee0d81f0a64/main/audio/audio_service.cc) |
| C5 | [Narrator/audio.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/audio.py) |
| C6 | [stt.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/stt.py), [bridge.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/bridge.py), [live_agents.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/live_agents.py), [agents.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/agents.py) |
| C7 | [expert_jobs.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/expert_jobs.py) |
| C8 | [pipeline.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/pipeline.py), [speech_formatter.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/speech_formatter.py) |
| C9 | [speech_openings.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/speech_openings.py), [voice_library.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/voice_library.py) |
| C10 | [memory.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/memory.py), [expert_store.py](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/services/brain/gobot/expert_store.py) |
| C11 | [Latency probe](https://github.com/anpavel84-afk/gobot-home/blob/4b51e8b1b881855372479cad6c9f8a721a0877be/firmware/spotpear/host/latency_probe.h) |
| O1 | [Realtime / GPT-Live cost semantics](https://developers.openai.com/api/docs/guides/voice-latency-cost.md?voice-api=realtime) |
| O2 | [Realtime conversations: lifecycle and voices](https://developers.openai.com/api/docs/guides/realtime-conversations.md) |
| O3 | [Realtime client events: append and turn detection](https://developers.openai.com/api/reference/resources/realtime/client-events) |
| O4 | [VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad.md) |
| O5 | [Realtime transcription protocol](https://developers.openai.com/api/docs/guides/realtime-transcription.md) |
| O6 | [GPT Live Transcribe pricing](https://developers.openai.com/api/docs/models/gpt-live-transcribe) |
| O7 | [Realtime server events: transcription duration usage](https://developers.openai.com/api/reference/resources/realtime/server-events) |
| O8 | [Text to speech: voices and migration](https://developers.openai.com/api/docs/guides/text-to-speech.md) |
| O9 | [Deprecation schedule](https://developers.openai.com/api/docs/deprecations) |
| O10 | [Speech API request contract](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create) |
| O11 | [Codex App Server events and phases](https://learn.chatgpt.com/docs/app-server.md) |
| S1 | [Soniox startup buffering FAQ](https://docs.soniox.com/faq) |
| S2 | [Soniox cadence limitations](https://docs.soniox.com/stt/rt/error-handling) |
| S3 | [Soniox connection before start](https://docs.soniox.com/authentication/websocket-authentication) |
| S4 | [Soniox keepalive and stream billing](https://docs.soniox.com/stt/rt/connection-keepalive) |
