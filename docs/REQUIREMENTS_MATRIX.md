# Матрица фактического состояния — v0.3 DRAFT, Realtime/Family дополнения

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
