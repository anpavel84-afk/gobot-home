# Матрица фактического состояния — v0.3 DRAFT, Realtime/Family дополнения

| Spotpear, 12.11.2026 | Проверено | Открыто |
|---|---|---|
| touch_ui | 0.2.0 на LCD, реальное касание и состояния проверены владельцем. Для 0.2.1 подготовлено сравнение восьми кадров с атласом | Приёмка остальных жестов, сети и скинов на LCD |
| real_voice | Отдельный аппаратный допуск C, гостевой профиль, потоковый Opus/WebRTC. На 0.2.1 подтверждены ответ и завершённый таймер. На 0.2.2 владелец подтвердил погоду сегодня и завтра для дома | На 100 стало громче по оценке владельца. Физический тест паузы не прошёл. Остаются последние слоги, отсчёт на LCD, дуплекс и окончание фразы |
| wake_word | 0.3.0-dev-mww-probe прошла flash verify и обрабатывает ES8311 через 16 кГц microWakeWord. Фронтенд на S3 прошёл проверку. Диагностические срабатывания локальны | Доля верных на людях, ложные в быту, допуск к созданию сессий и проверка wake → Brain |
| duplex/AEC | 0.4.0 на плате, MIC/REF и AFE работают одновременно с локальным playback, речь поверх звука подтверждена владельцем | Текст, ERLE в контролируемых условиях и GPT-Live barge-in |
| LiveKit | Локальный PLAN Server 1.13.11, реальное двустороннее media в loopback и непрерывный Brain fixture | 0.4.2 прошла физический WSS/LiveKit прогон 161/150 пакетов с playback ACK. Две модельные пробы не дали слышимого ответа; повтор требует нового допуска |
| Recovery | Проверенные образы приложения и общих assets, полный приватный снимок перед записью, запись только ota_0 | Практический откат |
| Разделение данных | Гостевой scope, RAM, отдельный идентификатор, явные допуски | Семейный сценарий на физическом устройстве |

Источник требований: [GOBOT_HOME_TARGET_SYSTEM.md](GOBOT_HOME_TARGET_SYSTEM.md), v0.2 `96e0f3d` и новые решения владельца §36–40.
До синхронизации: чистая master `bd487ff`; после docs-only fast-forward `96e0f3d`.
Это evidence, не новая спецификация. Обновление стабилизации 10 ноября: baseline 2f0eefc; прежние строки без новых проверок не считаются повторно принятыми.
Пути к Python-модулям ниже относительно services/brain/gobot; tests — относительно tests/.

| ID | Требование | Фактический статус | Код | Проверка | Пробел |
|---|---|---|---|---|---|
| R-001 | Единый Brain для браузера и ESP32 | частично | brain.py Service / voice_mock.py | test_security_ui_protocol.py | ESP32/upstream только fixtures |
| R-002 | Заменено §36: Realtime Mini — целевой обычный разговор; CLI — legacy и подтверждаемые эксперты | native candidate fixtures + model metadata HTTP 200; default legacy до приёмки | realtime.py / realtime_provider.py / expert_jobs.py / routing.py | test_realtime_native.py / test_realtime_experts.py | Реальные native audio/iPhone и допуск default не проверены |
| R-003 | Gemini CLI/API не используются | fixture + прежние реальные CLI наблюдения | routing.py SmartRouter.choose / quality.py | test_quality_router.py | Новое качество/скорость реальных моделей не измерены |
| R-004 | Native Realtime input; OpenAI STT основной в legacy, Whisper только вручную | частично, реальные speech пробы предыдущей фазы | stt.py OpenAIRecognition / audio.py Speech | test_live_audio.py / openai-speech-probes.json | Новый полный iPhone E2E не принят |
| R-005 | Native Realtime output; OpenAI TTS основной в legacy, локальный голос только явно | частично, реальные speech пробы предыдущей фазы | stt.py OpenAIRecognition / audio.py Speech | test_live_audio.py / openai-speech-probes.json | Новый полный iPhone E2E не принят |
| R-006 | Отдельные согласия на расходы и доступ | fixture + прежние реальные CLI наблюдения | routing.py SmartRouter.choose / quality.py | test_quality_router.py | Новое качество/скорость реальных моделей не измерены |
| R-007 | Админка отделена от режима устройства | fixture, HTTP проверка | device.js DeviceApp / device-renderer.js / device_store.py | test_device_and_composer.py / device-e2e.json | Реальная читаемость/касание Safari не приняты |
| R-008 | Круглый логический дисплей и safe area | fixture, HTTP проверка | device.js DeviceApp / device-renderer.js / device_store.py | test_device_and_composer.py / device-e2e.json | Реальная читаемость/касание Safari не приняты |
| R-009 | Скины/заставка сохраняются на сервере | fixture, HTTP проверка | device.js DeviceApp / device-renderer.js / device_store.py | test_device_and_composer.py / device-e2e.json | Реальная читаемость/касание Safari не приняты |
| R-010 | Состояния лица связаны с фактическим состоянием | fixture, HTTP проверка | device.js DeviceApp / device-renderer.js / device_store.py | test_device_and_composer.py / device-e2e.json | Реальная читаемость/касание Safari не приняты |
| R-011 | Удержание/отпускание автоматически отправляет речь | fixture, HTTP проверка | device.js DeviceApp / device-renderer.js / device_store.py | test_device_and_composer.py / device-e2e.json | Реальная читаемость/касание Safari не приняты |
| R-012 | Локальное wake-word ожидание | blocker | activation.py WakeWordActivationService | test_device_and_composer.py | Нет проверенной русской GoBot KWS-модели |
| R-013 | Нет платной фоновой транскрипции | fixture | capture.js / browser.js / device.js / pipeline.py | test_browser_regressions.py / test_live_audio.py | Нужна проверка на физическом iPhone |
| R-014 | Честная обработка фоновых ограничений телефона | fixture | capture.js / browser.js / device.js / pipeline.py | test_browser_regressions.py / test_live_audio.py | Нужна проверка на физическом iPhone |
| R-015 | Финальная транскрипция фиксируется один раз | fixture | capture.js / browser.js / device.js / pipeline.py | test_browser_regressions.py / test_live_audio.py | Нужна проверка на физическом iPhone |
| R-016 | Частичный STT не запускает опасное действие | fixture | capture.js / browser.js / device.js / pipeline.py | test_browser_regressions.py / test_live_audio.py | Нужна проверка на физическом iPhone |
| R-017 | Speech Formatter сохраняет факты и убирает дубли | fixture + обратная связь владельца | speech_formatter.py SpeechFormatter / providers.py SentenceBuffer | test_speech_formatting.py | Универсальная смысловая редактура не реализована |
| R-018 | Потоковое воспроизведение без повторного final | fixture + desktop Web Audio | browser.js / turn-trace.js / pipeline.py | test_dialogue_stabilization.py / opening_connection.cjs / dialogue-stabilization-checks.json | Вызов настоящего BufferSource.start проверен; iPhone не принят |
| R-019 | Сквозная отмена и очистка аудио | fixture + desktop Web Audio | browser.js / device.js / turn-trace.js | opening_connection.cjs / device_ui.cjs | Отмена, voice/mute/epoch и скрытие; физический телефон не проверен |
| R-020 | Права не определяются только голосом | частично | family.py Family / speaker.py SpeakerIdentity / browser.py subject | test_family_stt.py | ECAPA локально есть; калибровка семьи отсутствует, independent auth UX неполон |
| R-021 | Голосовые шаблоны локальны и удаляемы | частично | family.py Family / speaker.py SpeakerIdentity / browser.py subject | test_family_stt.py | ECAPA локально есть; калибровка семьи отсутствует, independent auth UX неполон |
| R-022 | Unknown/ambiguous/insufficient_audio поддерживаются | частично | family.py Family / speaker.py SpeakerIdentity / browser.py subject | test_family_stt.py | ECAPA локально есть; калибровка семьи отсутствует, independent auth UX неполон |
| R-023 | Speaker Identity не блокирует общий ответ | частично | family.py Family / speaker.py SpeakerIdentity / browser.py subject | test_family_stt.py | ECAPA локально есть; калибровка семьи отсутствует, independent auth UX неполон |
| R-024 | Router различает сложность, факты и последствия | fixture + прежние реальные CLI наблюдения | routing.py SmartRouter.choose / quality.py | test_quality_router.py | Новое качество/скорость реальных моделей не измерены |
| R-025 | Нет обязательной LLM-классификации каждой реплики | детерминированная полная цепочка | quick_intents.py / routing.py / local_tools.py | test_dialogue_stabilization.py | Проверены параметры, запрет legacy обхода и локальная unavailable; не универсальное NLU |
| R-026 | Автоматическая дорогая эскалация ограничена | fixture + прежние реальные CLI наблюдения | routing.py SmartRouter.choose / quality.py | test_quality_router.py | Новое качество/скорость реальных моделей не измерены |
| R-027 | Проверка по источникам/инструментам, не самооценке | частично | quality.py SelectiveVerifier / local_tools.py | test_quality_router.py | Общего web verifier нет; безопасный отказ |
| R-028 | Обязательные проверки завершаются до TTS утверждения | fixture + прежние реальные CLI наблюдения | routing.py SmartRouter.choose / quality.py | test_quality_router.py | Новое качество/скорость реальных моделей не измерены |
| R-029 | История, память и ContextPacket разделены | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-030 | ContextPacket имеет явный токен-бюджет | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-031 | Скрытая CLI-история не растёт бесконечно | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-032 | Темы поддерживают продолжение и возвращение | fixture + SQLite/RAM | brain.py text_done / memory.py | test_completed_text_survives_cancel_of_optional_visual | Завершённый текст переживает поздний optional visual; качество summaries отдельно |
| R-033 | Факты и summaries имеют происхождение | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-034 | Удаление распространяется на производные данные | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-035 | Mock/test изолированы от личной памяти | fixture + локальная персистентность | context_manager.py ContextManager / archive.py / memory.py | test_context_archive.py / context-evaluation.json | FTS ограничен, semantic retrieval не подключён; качество summaries не принято |
| R-036 | Каждый turn имеет Visual Presentation Plan | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-037 | Визуал не ограничен командой «покажи» | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-038 | Фото, схемы, виджеты и лицо — разные стратегии | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-039 | Внешняя картинка не задерживает обычную речь | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-040 | Поздняя сцена старого turn не перекрывает новый | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-041 | Поисковый словарь не ограничивает объекты | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-042 | Источник/тип изображения и атрибуция сохраняются | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-043 | Генерация не имитируется локальным SVG | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-044 | Ассеты проверяются и кэш ограничен | частично | response_composer.py / visual.py VisualService / visual_images.py | test_presentation_planner.py / test_visual_pipeline.py | Нет universal relevance gate; точность фото и Safari не подтверждены |
| R-045 | Tool Executor отделён от текста LLM | fixture, fail-closed | quick_intents.py / routing.py / local_tools.py | test_dialogue_stabilization.py | HA/Music не подключены; action slots проверены до executor |
| R-046 | Таймеры и напоминания персистентны | fixture + локальное серверное состояние | local_tools.py / memory.py | test_dialogue_stabilization.py / test_timer_duration.py | Целевая отмена проверена на отдельной БД; scheduler напоминаний отсутствует |
| R-047 | Результат действия подтверждается инструментом | частично, fail-closed | local_tools.py LocalTools / integrations.py | test_quality_router.py | Внешние HA/Music не подключены, опасные действия запрещены |
| R-048 | Музыка может воспроизводиться внешним плеером | отсутствует реальная интеграция | integrations.py / visual.py music fallback | test_additional.py | Нужен разрешённый реальный Music Assistant/player |
| R-049 | Умный дом ограничен whitelist и правами | частично, fail-closed | local_tools.py LocalTools / integrations.py | test_quality_router.py | Внешние HA/Music не подключены, опасные действия запрещены |
| R-050 | Host Bridge не является сетевым shell | локальный аудит + fixture | security.py / processes.py / live_agents.py / antigravity.py | test_security_ui_protocol.py / scripts/audit_agents.py / scripts/audit_agy.py | Adversarial native testing ограничено; секреты/сессии не копируются |
| R-051 | Реальные model/executable/usage видны в диагностике | частично | brain.py final / browser.js / telemetry.py | test_latency_v02.py / test_agents.py | Usage только доступный от CLI; полного биллинга STT/TTS нет |
| R-052 | API/события версионированы и идемпотентны | fixture, идемпотентность действия | memory.py / brain.py | test_duplicate_delivery_does_not_repeat_tool | Повтор request_id не создаёт второй таймер; намеренный новый request_id допускается |
| R-053 | Ключи и биометрия не попадают в Git/логи/клиент | локальный аудит + fixture | security.py / processes.py / live_agents.py / antigravity.py | test_security_ui_protocol.py / scripts/audit_agents.py / scripts/audit_agy.py | Adversarial native testing ограничено; секреты/сессии не копируются |
| R-054 | Временный режим не индексируется постоянно | fixture, RAM pending | memory.py transient_pending / conversation_control.py | test_pending_decline_is_scoped_and_does_not_close_session | Pending с TTL и owner/epoch работает без архива; не переживает restart |
| R-055 | Восстановление не повторяет опасные действия | fixture + прежний restart test | memory.py recover / scripts/manage.py | test_brain.py / reliability-results.json | Нет нового soak/hardware restart |
| R-056 | Прошивка только после backup и проверки профиля | blocker физического устройства | firmware/ / docs/HARDWARE_CHECKLIST.md | test_security_ui_protocol.py | Нет платы; backup/firmware/hardware не выполнялись |
| R-057 | Совместимость XiaoZhi проверяется по версии | blocker физического устройства | firmware/ / docs/HARDWARE_CHECKLIST.md | test_security_ui_protocol.py | Нет платы; backup/firmware/hardware не выполнялись |
| R-058 | Browser renderer не выдаётся за LVGL-эмулятор | blocker физического устройства | firmware/ / docs/HARDWARE_CHECKLIST.md | test_security_ui_protocol.py | Нет платы; backup/firmware/hardware не выполнялись |
| R-059 | Offline/degraded режимы честно обозначены | частично | brain.py final / browser.js / telemetry.py | test_latency_v02.py / test_agents.py | Usage только доступный от CLI; полного биллинга STT/TTS нет |
| R-060 | Реальные задержки отделены от mock | частично | brain.py final / browser.js / telemetry.py | test_latency_v02.py / test_agents.py | Usage только доступный от CLI; полного биллинга STT/TTS нет |
| R-061 | Стоимость всей цепочки учитывается раздельно | частично | brain.py final / browser.js / telemetry.py | test_latency_v02.py / test_agents.py | Usage только доступный от CLI; полного биллинга STT/TTS нет |
| R-062 | Установка не меняет чужие проекты/авторизации | локальный аудит + fixture | security.py / processes.py / live_agents.py / antigravity.py | test_security_ui_protocol.py / scripts/audit_agents.py / scripts/audit_agy.py | Adversarial native testing ограничено; секреты/сессии не копируются |
| R-063 | Несколько клиентов не смешивают контексты | fixture | memory.py owner scopes / browser.py subject | test_context_archive.py | Нет реального многокомнатного испытания |
| R-064 | Мультирум и арбитраж активации | отсутствует | activation.py guard / device.js PTT | test_device_and_composer.py | Мультирум/акустический barge-in отдельная фаза |
| R-065 | Голосовое перебивание при TTS | отсутствует | activation.py guard / device.js PTT | test_device_and_composer.py | Мультирум/акустический barge-in отдельная фаза |
| R-066 | Серийный продукт требует отдельной readiness-проверки | не принято | GOBOT_HOME_TARGET_SYSTEM.md M7 | отдельная readiness-проверка | Серийная готовность не заявляется |
| R-067 | Сквозной monotonic trace от input_closed до полезного playback | реализовано, fixture | telemetry.py / browser.js / pipeline.py / bridge.py | test_latency_v02.py | Реальные provider spans и physical audible output требуют проб |
| R-068 | Немедленный локальный waiting/earcon менее 150 мс | fixtures + прежние реальные trace | browser.js / turn-trace.js | feedback_timing.cjs / opening_connection.cjs | Earcon не равен полезному ответу; новая акустическая проверка iPhone отсутствует |
| R-069 | Однократный локальный филлер 2,0–2,5 с без API на turn | fixture + desktop cached Web Audio | speech_openings.py / browser.js / turn-trace.js | opening_connection.cjs / dialogue-stabilization-checks.json | Denis ожидания удалён; 100 marin сохранены; actual BufferSource.start и ended в IAB, не iPhone |
| R-070 | Feedback не входит в содержательный TTFA и память | реализовано, fixture | telemetry.py / browser.js / pipeline.py / bridge.py | test_latency_v02.py | Реальные provider spans и physical audible output требуют проб |
| R-071 | Прогретый CLI только при реальной поддержке и чистой истории | эксперимент выключен, native deny blocker | antigravity_acp.py / bridge.py / router-policy.json | test_acp_candidate.py / antigravity-acp-candidate.json | Свежие native sessions подтверждены без prompt; effective deny в ACP workers не доказан, допуск закрыт |
| R-072 | Prefetch запускается по финальному STT параллельно LLM | частично, следующий M3 | presentation_planner.py / visual.py / visual_images.py / image_query.py | test_presentation_planner.py / test_image_query.py | Ранний STT prefetch, entity epoch gate и PageImages hybrid ещё не реализованы; сохранён существующий pipeline |
| R-073 | Кандидат проходит entity/epoch/license gate до показа | частично, следующий M3 | presentation_planner.py / visual.py / visual_images.py / image_query.py | test_presentation_planner.py / test_image_query.py | Ранний STT prefetch, entity epoch gate и PageImages hybrid ещё не реализованы; сохранён существующий pipeline |
| R-074 | Speculative search ограничен приватностью и ресурсами | частично, следующий M3 | presentation_planner.py / visual.py / visual_images.py / image_query.py | test_presentation_planner.py / test_image_query.py | Ранний STT prefetch, entity epoch gate и PageImages hybrid ещё не реализованы; сохранён существующий pipeline |
| R-075 | RU/EN и научные имена сохраняют точные qualifiers | частично, следующий M3 | presentation_planner.py / visual.py / visual_images.py / image_query.py | test_presentation_planner.py / test_image_query.py | Ранний STT prefetch, entity epoch gate и PageImages hybrid ещё не реализованы; сохранён существующий pipeline |
| R-076 | Wikimedia entity/PageImages + imageinfo и Openverse как дополнение | частично, следующий M3 | presentation_planner.py / visual.py / visual_images.py / image_query.py | test_presentation_planner.py / test_image_query.py | Ранний STT prefetch, entity epoch gate и PageImages hybrid ещё не реализованы; сохранён существующий pipeline |
| R-077 | Личный/общий browser profile работают без биометрии | частично / открытый P0 | family.py / browser.py / family.js | test_family_stt.py / test_browser_regressions.py | Нет серверного child latch/компактного нового UX; M1 только отменяет feedback при storage scope change и сохраняет remember setting |
| R-078 | Голосовая самопрезентация не повышает права | частично / открытый P0 | family.py / browser.py / family.js | test_family_stt.py / test_browser_regressions.py | Нет серверного child latch/компактного нового UX; M1 только отменяет feedback при storage scope change и сохраняет remember setting |
| R-079 | Компактный профильный UX и серверный child lock | частично / открытый P0 | family.py / browser.py / family.js | test_family_stt.py / test_browser_regressions.py | Нет серверного child latch/компактного нового UX; M1 только отменяет feedback при storage scope change и сохраняет remember setting |
| R-080 | Profile epoch отменяет старые turn/audio/visual и сохраняет privacy mode | частично / открытый P0 | family.py / browser.py / family.js | test_family_stt.py / test_browser_regressions.py | Нет серверного child latch/компактного нового UX; M1 только отменяет feedback при storage scope change и сохраняет remember setting |
| R-081 | Синхронизация спецификации не меняет дерево кода bd487ff | проверено Git | 35.2 fast-forward bd487ff → 96e0f3d | test_ac36_docs_only_sync_preserves_code_base | Только целевой MD, нет reset/stash/merge main/restart |
| R-082 | Сокращение реальной задержки подтверждено сопоставимыми пробами | новое ускорение не измерено | telemetry.py / antigravity_acp.py | antigravity-acp-candidate.json / real-latency-probes-20261110.json | Metadata latency не является TTFA; новые платные сравнения не разрешены, сначала native isolation proof |

## Новые критерии приёмки

| AC | Статус этого прохода |
|---|---|
| AC-23–25 | Feedback/controller/shared playback fixtures проходят; реальный iPhone ещё не проверен |
| AC-26 | File STT → gateway → Brain → TTS trace fixture и client scheduling; real provider profiling pending |
| AC-27–30 | Существующий parallel visual не заменён; новые prefetch/hybrid/gates пока не приняты |
| AC-31–34 | Неполно: старый PIN/scopes есть; child latch и новый profile UX не реализованы. Полная server epoch cancellation не заявляется |
| AC-35 | Локальные metadata измерения отделены от useful TTFA; реальное сокращение 9–10 секунд не заявляется |
| AC-36 | Docs-only Git diff проверен тестом |

M2/M3 сохраняются в очереди; отсутствие child lock означает, что безопасный семейный child-mode продукт ещё не принят.


## Стабилизация после 2f0eefc

Подтверждены исправления контрактов вступлений, неоднозначных длительностей,
целевой отмены таймеров и локального decline/end. Проверка включает реальные
функции browser.js, desktop Web Audio с готовым WAV и изолированные SQLite/RAM.
Следует читать вместе с [CURRENT_STATUS.md](CURRENT_STATUS.md), раздел 11,
и [обезличенным отчётом](dialogue-stabilization-checks.json).
Новый бюджет API/CLI не расходован; ACP/useful TTFA/iPhone не приняты этими тестами.


Текущий проверенный runtime стабилизации — a71b71e; 965 regression tests,
приватный HTTPS и desktop Web Audio проверены отдельно от iPhone.
Подтверждение: [dialogue-stabilization-runtime.json](dialogue-stabilization-runtime.json).
ACP выключен и fail-closed; новая скорость inference не измерялась.


## Приёмка стабилизации / ACP после 6bf40d4

| Требования | Дополнительная проверка | Статус |
| --- | --- | --- |
| R-018, R-019, R-068–070 | 350 целевых проверок из pinned a71b71e; phone_acceptance.py и 4 guard/report tests | Бесплатные проверки пройдены; физический iPhone ожидает владельца, не принят |
| R-052, R-054 | One-time budget, no automatic retry/refund, enforced remember=false | Ограничитель проверен на временных ledgers; содержимое разговоров не используется в отчёте |
| R-071 | audit_acp_worker.py: argv, parent/worker PID, wire/session metadata, supported config/commands | Вывод D: native behavioral deny ещё не доказан; отдельные 4 canary-пробы ожидают разрешения |
| R-082 | Только metadata-время; исторические 16 мс не перенесены | Нового сопоставимого inference/useful TTFA нет; stream-json сохранён |

Фактические результаты и лимиты — [CURRENT_STATUS.md](CURRENT_STATUS.md), раздел 14.
Незавершённые голосовые настройки сохранены в рабочем дереве и в этот этап не включены.


## Новые дополнения владельца §36–40: Realtime, Identity, Speech и A/B

| Область / критерии | Реализация и проверки | Фактический статус / блокер |
| --- | --- | --- |
| R-001/002/004/005/071, native ordinary path | realtime_contract/provider/api.py, realtime.js; test_realtime_native.py, test_realtime_browser.py | Protocol/component fixtures; exact model metadata HTTP200. Нет live native audio/iPhone, default legacy |
| Нативные consent/budget/cleanup/usage | realtime_budget.py; persistent cancellation/call ledger, one owner; native tests | Free fixtures; новая iPhone-проба отдельно разрешена (1 call/90s/4×384), client-bound, CLI/ImageGen OFF; живой результат ожидается, dollar hard cap не обещается |
| Expert proposal/actual effort/one call/cancel | expert_profiles/jobs.py, Bridge; test_realtime_experts.py | Metadata model/list, offline Codex tools=[]; реальные эксперты и faithful voice пересказ не приняты |
| Visual native parallel/old turn rejection | прежние Composer/SpeculativePhoto + native transcript events | Реальная native задержка показа относительно голоса не измерена; source/fact gate ещё blocker |
| FI-02/03/04/06/08/11, память без биометрических полномочий | family_access.py, existing Family/Memory; native and family preference tests | Native guest RAM-only, PIN/false match не загружают private archive. FI-01 private retrieval ещё закрыт |
| FI-05/12, speaker смена и поздние результаты | realtime_speaker.py, nonce/revision, expert job ownership | Mock segment/job tests; реальные смены людей/iPhone не приняты |
| SpeakerIdentity WebRTC | existing ECAPA + local PCM16 mirror; test_realtime_speaker.py, realtime-speaker-local-check.json | Модель реально запускается, 192 components. 0 семейных профилей и нет calibration, точность неизвестна |
| Family personality/voice/CAS/privacy | family_preferences.py, existing family API/UI; test_family_preferences.py | Хранение/ручной PIN UX/reset/delete проверены fixtures. Auto voice rotation и parental edit grant не готовы |
| Russian Speech Quality | realtime_russian.py, 100 curated examples; test_realtime_russian.py | 90 deterministic cases + prompt/schema checks. 10 stress cases ждут реального звука; acoustic claim=false |
| Рабочая legacy версия и A/B | private source/SQLite/config/audio backup; demo2.py; test_demo2.py | Backup создан до restart, Formatter/audio совпадают с a71; A/B разделяют общий Brain |

Исторические строки выше остаются evidence соответствующего этапа; они не доказывают
приёмку новых native путей. Актуальный runtime и итог полного набора — CURRENT_STATUS.md.

Допуск B и исправление DOM круглого экрана — CURRENT_STATUS.md §16.2. Полный suite: 1116 passed; native subset после отдельного client-bound test: 28 passed. Числовые stage/usage reports не сохраняют содержимое домашних разговоров. Физический iPhone ещё не принят.

Код B загружен: 384c552; новая ограниченная phone policy включена, резервирований при допуске 0. Подтверждение: realtime-phone-trial-admission.json. Это admission, не результат акустической/iPhone приёмки.

## Первый iPhone native trial и исправление остановки

R-018/019/068–070/082: реальная одна сессия/3 responses зафиксирована в realtime-phone-first-trial.json; первые два ответа достигли output cap 384. Обработка incomplete/followup/close reason исправлена и проверена fixtures; точная старая terminal reason неизвестна, акустика и повторный iPhone не приняты. Старый бюджет не переоткрывается. Подробности — паспорт §17.


## Owner §41 — Wikimedia-first → Generate-if-missing

| Критерий | Код / evidence | Статус |
| --- | --- | --- |
| 1–3 Encyclopedia/plant/space | VisualService.images/wiki_candidates; test_visual_source_policy.py; visual-wikimedia-first-check.json | 3 synthetic subject cases; 2 реальные бесплатные Wikimedia изображения, device JPEG decoded |
| 4 Missing/weak → generation | generate_if_missing/generated, metadata gate | Empty/irrelevant/logo/tiny/corrupt fixtures; paid Image API probe не разрешён/не выполнен |
| 5 Budget denied → response survives | ScreenPreferences + generation_attempts/lineage | Policy/consent/limit/medical denial fixtures; native trial ImageGen OFF |
| 6 Cache | прежний ImageCache, style/model generation key | Mock generated cache; реальный повтор Wiki без HTTP, 22.51 ms |
| 7 Late/cancelled turn | SpeculativePhoto + NativeSession turn guards | Прежние stale-turn fixtures; новое cancel_unknown без автоматического повторного расхода |
| 8–9 Synthetic provenance | VisualMetadata, browser/device renderer, private lineage | AI label, источник/лицензия/consent snapshot; анатомическая генерация закрыта |
| 10 Parallel voice | прежний speculative worker, native transcript events | Fixtures; на физическом iPhone новый visual timing ещё не принят |
| 11–12 Display/shared contract | ImageCache variants, Presentation v2, esp32_projection | JPEG 240×240 реально декодирован; работа LVGL/платы не заявляется |

Актуальное развертывание/лимиты — CURRENT_STATUS.md §§17–18. Новый документ-паспорт не создаётся.

Runtime 9b78a1c загружен; 1139 regression tests passed. Desktop UI source policy/default gen OFF подтверждён. Повторный iPhone с новым лимитом ожидает согласия; exact terminal reason первой сессии не восстановлен. См. realtime-visual-fix-deployment.json и паспорт §18.1.


## Owner §42 — постоянное ручное тестирование B

| Проверка | Реализация | Статус |
| --- | --- | --- |
| Нет одноразового session/response/time cap или expiry у owner | RealtimePolicy owner-only nullable limits, RealtimeBudget | >100 sessions/>50 responses fixtures; developer/unbound null отвергнуты |
| Повторный ручной Start без renewal | native browser null-safe admission | Production JS fixture, страница не создаёт call автоматически |
| Count cap не маскируется под RAM capacity | lifecycle pruning + durable command/cancellation ledger | Старый ID/чужой scope/replayed command запрещены после eviction |
| Costs/consent/ACL/cleanup сохранены | existing budget, session expiry/Stop and typed gateway | Revocation/client/consent fixtures; CLI/ImageGen отдельны и OFF |

См. CURRENT_STATUS.md §19. Старые one-time trials остаются историческими фактами и не переоткрываются.

Owner manual admission включён на runtime 4f23908: limits/expiry=null, allowed phone client, CLI/ImageGen OFF. Реальный status/HTTP подтверждены в realtime-owner-manual-admission.json. Full suite: 1143 passed / 35.01 s; повторный звук на iPhone не подменяется этими проверками.


## Owner §43 — touch guard и native interpretation alignment

| Проверка | Реализация / evidence | Статус |
| --- | --- | --- |
| Случайное касание не обрывает речь | DeviceApp tap guard; production device_ui.cjs | Short/release/cancel/stale timer fixtures; deliberate hold=500 ms; iPhone feel pending |
| UI label не доказывает native interpretation | NativeSession.visual loading avatar; existing SpeculativePhoto | Initial scenes fixtures; metadata grounding, без задержки аудио |
| «паук»/«плод», иные существительные | response_alignment.py; test_response_alignment.py/native tests | 12 grammar cases + оба порядка ASR/output + partial-word case; не универсальный semantic/ASR verifier |
| User-confirmed correction | realtime.js current-turn review / sendText; realtime_device_settings.cjs | Нет auto call; click-only existing native text path, double click/stale turn guarded |
| Privacy/cost | content-free alignment_counts, clearReview, uncapped owner policy unchanged | Full suite 1158 passed; no new paid developer calls; real iPhone retest pending |

Подробности и границы достоверности — CURRENT_STATUS.md §20. Legacy A и первоначальный backup сохранены.

Runtime 528c866 загружен; A/B HTTP200, owner manual uncapped сохранён. Deployment evidence: realtime-touch-alignment-deployment.json. Реальная речь после исправления на iPhone не принималась по fixtures.


## Owner §§44–45 — круглый cover и two-stage visuals

| Требование | Реализация / проверка | Статус |
| --- | --- | --- |
| Фото заполняет круг; схемы целиком | DeviceRenderer preview cover / semantic image_fit; device_image_fit.cjs | Production Canvas fixtures + browser с реальным cached фото; iPhone pending |
| Question-first provisional | NativeSession.visual / TwoStageVisual / Composer | Topic scene + metadata-labelled candidate; native mock до response.done |
| Answer-driven refinement | stable_visual_chunk / answer_entity, общий attachment | Пауки→Phoneutria; Луна→Тихо; сердце→схема; local relations, не universal verifier |
| Unknown/mismatch | Existing response_alignment + bound affirmative clause | Неизвестная связь сохраняет Stage 1; паук/плод даёт neutral UI, no auto repair |
| Wikimedia → generation-if-missing | Existing VisualService; deferred aligned fallback | Wikimedia/cache реально; генератор только fixtures, native admission OFF |
| Cost/consent | Stage 1 generation denied; max one paid fallback admission; existing daily ledger | No-photo/consent/mismatch/source tests; новых paid calls 0 |
| Не больше двух уточнений | Revision cap, asset/topic dedupe, stale-turn gates | Slow Stage 1/old turn/cancel/update cap fixtures; browser visible replacement |
| Управляемость | Existing DeviceStore + экранный select | 3 стратегии; default question_then_refine; persistence regression |
| Общий browser/device контракт | VisualMetadata stage/revision/image_fit, compact projection | Оба production renderer проверены; LVGL не объявлен реализованным |
| Телеметрия | Native visual timing allowlist + validated client presented command | Wrong turn/frame игнорируются; content-free report; не физическая приёмка |

Полный набор 1176 passed / 36.31 s. Evidence: two-stage-wikimedia-check.json;
подробности, ограничения и фактическое развёртывание — CURRENT_STATUS.md §21.


## Owner §§46–47 — silence close и owner style

| Проверка | Реализация | Приёмка |
| --- | --- | --- |
| VAD ack full effective object | input_settings_applied | Extra defaults разрешены; safety controls не ослаблены; native fixture |
| Тишина завершает без error/response | followup expiry + explicit idle_timeout_ms=null | Mock normal close; новых response.create нет |
| WebRTC close раньше SSE | NativeVoice.transportEnded + scoped terminal status | Production JS mic OFF сразу; normal reason не error; реальный network failure остаётся error |
| Status не раскрывает сессию другому | Existing owned device/client/epoch | HTTP ASGI 404 для foreign; только closed/reason, no-store |
| Нужная диагностика | Content-free control_failure + followup timings | Только allowlisted action/exception kind; без домашнего transcript |
| Локально сохранённый характер владельца | Existing AssistantPreferences in bound owner policy | Synthetic user-level prompt fixture, guest/private ACL и голос неизменны |
| Чужие семейные настройки | Explicit Family preferences precedence | Family DB не дублируется; style не означает identity; physical retest pending |

Подробности расследования и границы подтверждения: CURRENT_STATUS.md §22.

Runtime 2c276a6 опубликован и запущен; 1180 regression tests и 50 targeted native/family checks. Deployment evidence: two-stage-silence-deployment.json. Owner style private, marin/ACL/uncapped owner admission сохранены; физический iPhone retest pending.

Bootstrap owner/family preferences: generated item IDs now 32 characters, production socket fixture enforces bound; 50 targeted tests. Real startup retest pending; CURRENT_STATUS.md §23.

## Owner §48 — подтверждённый Realtime → Expert CLI handoff

| Требование | Реализация / проверка | Статус |
| --- | --- | --- |
| Обычный B без CLI | Existing native engine; experts OFF exposes readonly propose/cancel, not start | Владелец принял обычный разговор; новый expert E2E не выполнен |
| Точная модель и effort | ExpertProfileName, registry, installed model/list | Sol High/xhigh, Astra medium/high metadata; Argon Antigravity; неизвестный Gemini 1 не подменяется |
| Согласие после async ASR | NativeTurn.consent_ready + ExpertJobs.observe/start | Late transcript/отказ/изменение области; одно согласие не переиспользуется |
| Отдельная квота, один эксперт | ExpertBudget finite client/profile/expiry/count + lock | Fixtures; live OFF, grant отсутствует |
| Безопасный reserve/spawn | Post-reservation owner/epoch/revision/closed guard | Закрытие, revoke и новый turn во время reservation не запускают CLI |
| Не блокировать Mini, один output | accepted tool result + distinct data notice + central response | Mock same provider session/voice; real audio pending |
| Результат после нового вопроса | Deferred card + ExpertStore in existing SQLite | Не перебивает; собственный profile/epoch/conversation; remember=false RAM |
| Ошибки/отмена/квота | Structured status, timeout and no retry | Native conversation остаётся; чужой/детский профиль не получает данные |
| Followup и job разные сроки | Mic closes while agreed bounded job continues | Native fixture; физический iPhone pending |
| B интерфейс | expert-ui.js existing page, authenticated status, no-store | DOM/mock integration; deployment/browser evidence в CURRENT_STATUS.md §25 |
| Изоляция / расходы | Matching offline Codex audit; private grant OFF | tools=[], 1 mock HTTP, 0 paid/model calls; entitlement/latency не измерены |

Текущие факты требуют источников: мнение эксперта само по себе не является проверкой.
Подробности, публикация и реальные блокеры — CURRENT_STATUS.md §25.

## Owner §49 — visual fulfillment

| Критерий | Код / проверка | Подтверждение |
| --- | --- | --- |
| Скорость орла → орёл | semantic_visual + extract_entity | Грамматический объект, не свойство; настоящий Wikimedia asset |
| Explicit show/find/generate | PresentationDecision + visual_request / gobot_tool alias | Shared task, late ASR, coalescing; без второго pipeline |
| Explicit независимо от auto visual | Composer / TwoStageVisual | OFF/Minimal/answer-only fixtures; policy/consent сохраняются |
| Badge не success | TwoStage result / diagnostics | Missing/error → fallback frame, asset_delivered=false |
| Wikimedia → permitted generation | Existing VisualService / generated | Source-first mocks + real Wikimedia; платная генерация только mocks, live OFF |
| Конкретные причины | generation_blocker + tool output | Отдельно policy/mode/consent/limit/provider/source; настройки не менялись |
| RU/EN/составное название | Common noun sense + article_title_matches | Eagle; кратер Луны/Лунный кратер; ambiguous meanings не угадываются |
| Показ и failure | Current visual_presented / visual_failed | Decode failure card, late/stale ack guards, no paid retry |
| Browser и circle | Production Node + desktop QA fixture | Реальные cached public фото и fallback; физический iPhone pending |

Полная регрессия 1251 passed; источники, тайминги и границы — CURRENT_STATUS.md §26.
Runtime 7b1d925 опубликован и запущен; A/B и оба cached device JPEG HTTP200,
декодирование 240×240 подтверждено через штатный HTTPS. iPhone/native audio pending.

## Owner §50 — разрешение image fallback

| Критерий | Реализация / приёмка |
| --- | --- |
| Разрешено 20/day на owner phone | Separate server cap + existing DeviceStore profile; activation evidence в CURRENT_STATUS §27 |
| Wikimedia не запирается после 80 HTTP | Private shared budget 60/min, 2000/24h; existing counters preserved |
| Remote limits сохраняются | 429/Retry-After unchanged; unit backoff survives local quota increase |
| Старый quota failure cache не мешает | Negative key includes policy revision, positive assets stable; integration fixture |
| «Сколько у человека волос» | Quantified possessor grammar, три порядка слов; real Wikimedia hair illustration decoded |
| Тишина не отменяет pending image | Mic closes; bounded worker stays; cancellation/profile/pagehide unchanged; native fixture |
| Подписка и API различаются | Codex image-only blocked; OpenAI metadata200, real paid generation не выполнялась |

Runtime eb4e4c8 опубликован и запущен. Owner phone generation ON, cap20;
native status/profile/client binding проверены, A/B и hair asset HTTP200.
Full 1263 + final targeted 87; paid output/iPhone generation pending.

## Owner §51 — фактический допуск expert handoff / сравнение A/B

| Критерий | Реализация / подтверждение |
| --- | --- |
| Проверка последнего случая B | Existing ledger: 4 turns, 6 completed responses, errors={}, expert reservations=0; точного текста/tool events нет |
| Не обещать выключенный CLI | Effective admission в instructions; start tool только при допуске; акустический ответ требует iPhone приёмки |
| Blocked не awaiting_confirmation | Tool integration: accepted/executed=false, state=blocked, jobs пуст; обычная сессия доступна |
| Видимый отказ на explicit просьбу | Final transcript diagnostic intent → expert_blocked → existing panel раскрыт; production DOM fixture |
| Аудит стадий без домашних разговоров | Allowlisted numeric counters; private keys/text исключены; исторические данные не выдумываются |
| Нет обхода согласий | Late transcript/decline/cancel/one CLI/one call output/profile ACL fixtures; реальный expert grant OFF |
| A/B настройки независимы | Scoped localStorage compatibility + bound readiness; local revocation сохраняется; immutable asset hash tests |
| Платные и аппаратные проверки | 1269 free tests passed; новых paid calls=0; phone expert E2E / A speech pending |

Runtime и публикация фиксируются в CURRENT_STATUS.md §28.

## Owner §52–53 — Full Test и C / GPT-Live

| Требование | Фактический этап |
| --- | --- |
| Unified owner expenses/readiness | Активирован d49b574; bound owner phone, CLI20/day, Image20/day, estimate$10/day |
| Mini/full | Два metadata200, requested ID/config ACK, новая session; voice comparison pending |
| Тихий PTT | Production JS: baseline и quiet на одном RMS .003; B default baseline |
| Private ACL отдельно | Public owner route не открывает личный архив; native private retrieval ещё отсутствует |
| A/B сохраняются | Immutable A + compat; B Realtime Mini; C в общем продукте |
| Live 1.1 | Не подтверждена; gpt-live-1 реально принят в двух voice sessions |
| Live protocol/timeline/full duplex | Отдельные protocol/API/ledger/client; real Live timer/audio/Close, C fixtures и production JS |
| Реальная приёмка | Live2/Luna4/CLI1/Image1 подтверждены на указанных путях; joint C voice/iPhone/ESP32 pending |

Текущий этап и runtime — CURRENT_STATUS.md §29–30.

| C приёмка | Фактическая граница |
| --- | --- |
| B сохраняется | Mini/baseline не меняются; C explicit route, общий Brain |
| Client delegation | Реальные delegation ID, acoustic Timeline, replay dedup; timer/ExpertJobs integration fixtures |
| Stop / Cancel / End | Отдельные действия, full-duplex JS fixture; iPhone interruption pending |
| Setup cancel / double Close | Known provider cleanup once, final cumulative usage; synthetic provider |
| Family isolation | Fail-closed identity cleanup, RAM erased, no provider-history transfer; no real calibrated profiles |
| Two-stage visual | Shared VoiceVisualSession, canonical UI scenes/render ACK; Live image E2E pending |
| Общий reasoning backend | Не подключён; отдельное решение владельца, не скрытый CLI или новая LLM |
| Private persistent memory | Пока отсутствует в native C; guest RAM не считается долговременной памятью |
| Real audio / iPhone | Не доказаны 1286 free tests; controlled canary и физическая приёмка отдельно |

C real: Live1/marin/SDP/sideband/decoded PCM/timer/Close подтверждены,
2 sessions final87s, estimate$0.0725. Voice expert synthetic input misrecognized,
CLI0; не принят. B typed expert proposal получена, start0/CLI0; исправлен canonical
consent scope и next_action, повторная проверка после deployment. iPhone pending.
Подробные условия и source/runtime — CURRENT_STATUS §31.

Owner §54: gpt-6-luna явно разрешена для C. Fixed Responses/token-count adapter,
2048/512, no tools/retries, concurrency1, scoped ContextPacket, отдельный usage и
developer4. Free backend + C route tests и реальные4 Luna responses прошли; joint voice pending.
B typed handoff после исправления: **одна настоящая SOL_HIGH completed**, карточка
и native PCM после результата; voice/iPhone не проверены. Shared Image fallback:
реальная генерация после Wikimedia miss, JPEG1024/480/240 decoded. Эти результаты
не объявляют C voice expert или физическое устройство принятыми.

Luna real4/4 прошли: exact counts164–268/output46–50, effortnone, tokens/usage,
непустые ответы и продолжение темы. First text1.23–2.81s включает count0.55–1.47s;
это не acoustic TTFA. Joint Luna→Live voice пока fixture, физический iPhone pending.
Полный free1293; код/публикация/runtime и оставшиеся ограничения — паспорт §32.

Финальный код9e6d0bb запущен, owner C/Luna ON, A/B сохранены, root default legacy.
Последний полный free1296 + финальные targeted68/52; selected expert profile C
проверен без выдачи согласия. Финансовые лимиты не сброшены; все real evidence,
условия сравнения, A/B rollback и физическая приёмка перечислены в паспорте §32.

### Новое решение §55: основной разговор C ↔ A

Эти строки заменяют конфликтующие прежние требования default legacy / explicit-C-only.

| Требование | Реализация и бесплатная проверка | Оставшаяся приёмка |
| --- | --- | --- |
| Один основной интерфейс, запуск C | root/device unified.js, HTTP fixtures; A/B/C comparison сохранены | iPhone Start |
| «Экспертный режим» → A | Server exact intent, mode lease, confirmed Live close → прежний legacy pipeline | Реальная голосовая команда и Safari autoplay |
| Возврат в C | Точная команда, новый provider session с разрешёнными RAM messages | Реальное A→C аудио |
| End/Stop/idle10 → C standby | Server/JS fixtures, без нового paid create; default selection reset | Физические10s после playback |
| Тишина не удерживается картинкой | Live idle_due не ждёт visual/expert cards; stale activity guard | Реальная комната/фоновый шум |
| Контекст без private leakage | Memory RAM scope + owner/client/epoch, remember=false, forbidden resume fixtures | Калиброванные голоса/семья остаются отдельной работой |
| Общие инструменты | Настройки на прежнем device owner; timer на том же client namespace; real local HTTP timer fixture | iPhone weather/timer |
| Локальное «ГоБот» | **Не готово**, readiness=false, честная подсказка и Start | Установка/проверка keyword detector, buffering, iPhone/ESP32 |
| Экспертная модель A | Существующий AUTO Flash Low/Medium, Speech Formatter сохранён | Sol Medium — отдельная настройка/приёмка, не заявлен включённым |
| Расходы | Owner policy восстановлена, hash checked; ledgers/caps не сброшены; paid developer0 | Реальный счёт/voice duration при ручной пробе |

Текущий code/runtime, backup и ограничения — CURRENT_STATUS.md §34.
Code `1de0cdf` опубликован и запущен. HTTP200 root/device/scripts/A/B/C, idle10,
Live unconfirmed0, frozen A hashes unchanged; desktop IAB показал новый общий
экран без Start/платного вызова. Реальные iPhone mode-switch/wake ещё не приняты.

### Приёмочные поправки §55.1 (заменяют image-failure card на основном экране)

| Требование | Проверка | Граница |
| --- | --- | --- |
| Нет asset/decode → говорящее лицо без ошибок/бейджа | production canvas + DOM fixtures, source diagnostics retained | iPhone raster/acoustics отдельно |
| Пригодное изображение появляется после decode | Canvas fit + DOM load/stage fixtures; valid Stage1 survives refinement failure | Новые real source/Image API calls не выполнялись |
| «Давай перейдём в экспертный режим A/А» | Parser + input/output protocol through real LiveManager, no delegation | Настоящее ASR/voice owner acceptance pending |
| Устное «давайте» не считается переходом | Production live.js→unified.js→A fixture checks closed/final confirmation | Safari autoplay hardware pending |
| Старые C ссылки имеют mode coordinator | HTTP C panel/device includes unified.js and unified flag | Не доказано, какой старый URL использовался ранее |
| Исправление/незавершённый ввод не переключают | Delayed/cancelled control fixture; no network-gap completion | Шум/перебивание на физическом телефоне отдельно |

Последний фактический runtime — CURRENT_STATUS.md §35.
Code7b4e7ee опубликован/запущен, HTTP200 и coordinator на root/C подтверждены,
A baseline hashes unchanged, unconfirmed Live0. Free1327/66s; desktop browser
в этом проходе не предоставлен, iPhone voice после исправления ожидает владельца.

### C: исполнение бытовых команд без delegation — CURRENT_STATUS §36

| Требование | Проверено в реализации | Граница доказательства |
| --- | --- | --- |
| Таймер не отправляет человека в приложение телефона | Native transcript → реальный SQLite timer + widget + commentary(null), даже после модельного отказа в fixture | Новый голосовой iPhone-прогон ожидается |
| Поздняя/конкурирующая delegation не повторяет действие | Общая operation claim; одна запись; реальный ID только от provider event | Модель/сеть подменены |
| Длительность уточняется в следующей реплике | Pending timer namespace → «на пять минут» → один таймер | Live ASR отдельно |
| Погода проверяется источником | Реальный Open-Meteo source check и сохранение ранее указанной точки телефона | Не акустический E2E; координаты приватны |
| Пошаговая настройка и ACL | Реальные SettingsTools, fake HTTP: permission→location→confirmation→ready, запрет без owner | Не новая семейная авторизация |
| Поправка/close/ошибка не создают скрытые повторы | Отмена pending task, profile invalidation, redacted failure и no retry fixtures | Сбой iPhone/Safari физически отдельно |
| Нет лишней LLM для быстрых действий | В fixture нет backend/ExpertJobs, используется прежний Quick Intents | Live duration платная; это не обещание бесплатного voice turn |

Runtime codef9b1f1e опубликован и запущен после idle0; HTTP подтверждает bridge v2,
clock/timer/weather, owner weather configured, A baseline unchanged. Free1337/84.25s.
Новый платный Live/iPhone-прогон не выполнялся; акустика и реальное срабатывание
виджета на телефоне остаются отдельной приёмкой. Исторический runtime §35 выше
сохранён как история, актуальный паспорт — CURRENT_STATUS.md §36.

### Прогноз и таймеры — CURRENT_STATUS §37

| Требование | Реализация/проверка | Оставшаяся граница |
| --- | --- | --- |
| Завтра/неделя/до16 дней | Validated Open-Meteo daily, IANA place timezone, реальный source check16 дней | Weather.com требует официальный API-доступ; hourly/month пока отсутствуют |
| Солнце/облака/осадки графически | Production canvas vector primitives, DOM icon/table,16day scene paging | Живой Chrome просмотр заблокирован Computer Use; iPhone отдельно |
| Естественная команда засечь таймер |250 формулировок + настоящие SQLite timer records; original duration guard preserved | ASR real canaries после отдельного допуска |
| Счётчик между вопросами и после idle | SceneManager timer state + small overlay; cloud idle не продлевается ради timer | Suspended/closed Safari не системный будильник |
| Отмена реально прекращает графику | Actual DB cancellation→timer_state IDs→DOM/Canvas | Phone network/acoustics отдельно |
|400 сценариев | Inventory+free routing checks:100 local/240conditional/60blocked; зависимости явные | Не400 независимых integrations и не доказательство полного parity |
| Расход новых trials конечный | Отдельное3Live/180s/10Luna/$2estimate; server grants preserve counters | Финальные фактические usage/результаты фиксируются после canaries |

Реальные canaries97d64be: timer5s/widget/expiry, tomorrow forecast card + начало
озвучки, одна Live-сессия timer→status→cancel прошли;3final usage confirmations.
10 отдельных Luna text calls completed. Общий developer estimate$0.04465207,
53provider seconds Live, новыхCLI/Image0, pending0. Это synthetic local Piper
input/decoded PCM, не акустическая iPhone-приёмка. Фикс ранней delegation после
canaries проверен targeted328; платные пробы не повторялись и scope не расширялся.
Финальный deployed code4931c49, HTTP200, bridge3/forecast/400 inventory и frozen A
проверены; unconfirmed Live0. Weather semantics307 дополнительно исключает неверную
маршрутизацию научных/медицинских вопросов в погоду. iPhone/реальный просмотр Canvas
после выпуска не подтверждены. Полный актуальный статус — CURRENT_STATUS §37.


### Графический комплект владельца — CURRENT_STATUS §38

| Требование | Фактическая привязка | Граница приёмки |
| --- | --- | --- |
|192 экрана/34layout, editable sources | Валидированный source archive,SVG/token registry, read-only atlas | Референсы с demo values, не192 работающих интеграции |
|72 лица/3скина, hearts/stars | Общая vector library, выбор24idle expressions в существующем appearance UI |53distinct source geometries; не распознавание личности |
|109 semantic icons | Shared Path2D/DOM SVG, weather/timer/status/scene icons | FA Free6.7.2 attribution/CC BY4.0 сохранены |
| Крупные значения и безопасный круг | Noto Sans local/OFL, safe36..204, photo cover/diagram contain | Старые настройки не сброшены; physical readability отдельно |
| Настоящая погода/таймер | Existing WeatherDisplay/deadline/duration;16day paging;expiry latch/dismiss | Нет фальшивых pause/+minute; не background alarm iOS |
| Рот/микрофон/личность разделены | Mouth actual playback RMS; separate actual microphone status | Сердечки/voice match не предоставляют ACL |
| Reduced motion/late result | Stable reduced raster; existing decode ACK/turn/profile guards | Skia offline + DOM fixtures; не hardware/Safari proof |
| Figma | Source native importer retained unexecuted | Файл в Figma и visual acceptance отсутствуют |
| Цена внедрения | Графика/шрифты локально; atlas не вызывает APIs | Новых платных вызовов0, прежние лимиты сохранены |

Выпуск04d8999 published/running;1814tests +8final source checks; IAB desktop
atlas/device проверены, HTTP200/A baseline unchanged. Новых платных вызовов0.
Saved non-null preferences сохранены; штатный bootstrap заполнил прежние
null voice defaults и добавил auto-expression. iPhone/ESP32/Figma отдельно.


### Домашние продолжения — CURRENT_STATUS §39

| Требование | Реализация | Граница |
| --- | --- | --- |
| Без города — домашнее место | Scoped saved DeviceStore + compact home_context | Не GPS телефона/не guessed IP; если нет настройки — Setup |
| «Хорошо…завтра», «там же», «а ветер?» | Weather-only wrapper parsing + last request slots | Только активная тема/сессия, не чужой профиль |
| Источник вместо догадки | Existing WeatherClient/SettingsTools, source-backed cards/voice text | Реальные2free HTTP, Live speech после фикса отдельно |
| Правила домашних разговоров |10reviewed rules в существующем400catalogue, используются Live | Не400working integrations, правила не заменяют ACL |
| Приватность истории | remember=false/RAM; old protocol не придуман | Новая постоянная запись не включена |

Финальный runtime faa4186 published/running, home_dialogue v1/10rules
подтверждён HTTP;1942full +161final affected tests. Реальный free Open-Meteo
current/tomorrow2calls; paid developer0. Все существующие policy/profile rows
сохранены по byte-сверке с WAL backup202742. Новые Live voice/iPhone trials
не выполнялись; прежние реальные canaries не названы проверкой нового prompt.

### Журнал отладки — Owner Direct, CURRENT_STATUS §40

| Требование | Реализация | Граница проверки |
| --- | --- | --- |
| Протокол A/B/C после Close | Единый DebugJournal, вопросы/ответы/события/результаты/usage | Текст транскрипта, не исходное аудио/не доказательство услышанного |
| Сохранение приватности | DPAPI payload, owner binding + principal/client/epoch scope | Не семейная память; epoch rotation не открывает прежнюю историю |
| Управление записью | Existing Owner Full Test, включение/1..7дней/удаление | Отдельное согласие владельца; remember=false не индексирует диалоги |
| Не задерживать голос | Bounded background writer, health/dropped events | Не lossless при сбое процесса/диска/переполнении |
| Разбор отказа погоды | Конкретный reason, verified=false, invalid-cache eviction | Старый незаписанный инцидент не реконструирован |
