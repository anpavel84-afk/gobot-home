# GoBot Home: read-only аудит перед библиотекой бытовых сценариев

Проверка: 11 ноября 2026 по клиентскому времени America/Sao_Paulo.
Снимок GitHub master: `effd1ff7be7150683ffacb0fa69934fd46142e87`, авторское время 2026-11-12T00:03:32Z.
Это снимок **опубликованного исходного кода**, не подтверждение развёртывания на PLAN.

## 1. Что уже существует и нельзя переизобрести

- Фактический проект: `anpavel84-afk/gobot-home`; локальное расположение из CURRENT_STATUS: `C:\Users\PLAN\gobot\GoBotHome`. PLAN — Windows-пользователь/домашний хост, не обозначение текущего режима ChatGPT.
- CURRENT_STATUS на проверенном снимке указывает последний подтверждённый runtime `faa41869fd40adf624edad562ff7c86eaeed6b0c`; §40 описывает новый журнал, но завершается обещанием отдельно зафиксировать deployment. Нельзя объявлять, что effd1ff уже запущен.
- C = GPT Live через client delegation + утверждённый Luna text backend. A = существующий STT/CLI/SpeechFormatter/TTS экспертный разговор; B сохранённый Realtime baseline. Переключение всего разговора в A и разовая expert job в C — разные операции.
- Обычные инструменты исполняются Brain и возвращают Live данные. Новая библиотека не даёт ACL, квоты, доступ к памяти или разрешение платных действий.
- Погода уже умеет configured home без повторного запроса города, scoped продолжения о периоде, исправление «нет, завтра» во время получения источника; это нельзя описывать как полностью отсутствующую функцию.
- В §39 задокументированы 134 home cases и 1942 full checks; в §40 1960 full checks +81 targeted. Это заявления status/evidence в репозитории, не прогоны, выполненные в данном аудите; новые Live/iPhone акустические прогоны не подтверждены.
- 192 макета/72 лица/109 иконок уже импортированы в существующий renderer; demo values не являются функциями или фактическими результатами.

## 2. Реальный каталог

`services/brain/assistant-skills.json`, version=1:
`dialogue_rules` (10), `sources`, `note`, `scenarios` (400).

Поля scenario:
`id, category, request, path, readiness, executor, intent, requirements, acoustic_verified, competitor_reference_scope`.

Разбивка:

| path | Строк |
|---|---:|
| native |100|
| conversation |200|
| visual |20|
| expert |20|
| integration |60|

Readiness: `local_path`, `conditional_path`, `not_connected_or_restricted`.

20 категорий по20: timers, weather, local_utilities, device_settings, time_and_control, language, learning, science, cooking, gardening, home_advice, technical_explanations, writing, games, planning, visuals, experts, smart_home, connected_services, private_and_scheduled.

Важное: `local_path` означает доступный обработчик запроса, включая честный отказ; например «погода на месяц» и Weather.com имеют local_path, но исполнитель сообщает ограничения. Это не успешная поддержка заявленного действия.

В каталоге отсутствуют предусловия, история ходов, ожидаемые slots, canonical result fixture, варианты ответа, негативные проверки, expected side effects и доказательства приёмки каждого сценария. 10 dialogue_rules уже читаются `dialogue_instructions()` и добавляются в Live instructions.

`test_skill_catalogue.py` проверяет:
- для native: наличие любого quick/mode/closing route;
- для integration: exact route в unavailable и текст отказа;
- 400 уникальных IDs/requests.
Он не проверяет содержательное качество 200 conversation-ответов и не доказывает, что все 400 работают в живом диалоге.

## 3. Узкие доказанные пробелы

### 3.1 Отсутствующие интеграции распознаются слишком узко

`skill_catalogue.unavailable_request(value, context)` сравнивает exact нормализованную фразу с полем request. Набор синонимов/смысловой класс операции не реализован этим методом. Некоторые planned entries имеют свои регулярные шаблоны (например будильник), другие — пустые patterns (reminder/calendar/light).

Следствие: гарантированный честный отказ покрывает точные фразы, но для произвольных перефраз он не доказан. Нельзя делать вывод, что каждый такой запрос обязательно завершится ложным действием; это риск маршрутизации, требующий fixture.

### 3.2 Запрос погоды другого города смешан с настройкой home

`weather_query` возвращает `weather_other_place` при чужом месте, не возвращая slot city.
`SettingsTools.execute` для этой операции создаёт `weather_location` pending и говорит:
«Для этого места назовите город и регион... прежде чем менять основное место...»

Нужен отдельный informational lookup: «А в другом городе?» должен использовать временные place slots без изменения home, повторного запроса уже названного города и прав на изменение настроек.

### 3.3 Weather slots не содержат запрошенную характеристику

`weather_followup` и `LiveSession.weather_last_request` сохраняют только operation/offset/days/weekday.
«А ветер?» наследует дату, но возвращает полный current/forecast запрос; `forecast_result` формирует общий длинный ответ. Нужны requested_metric и краткий targeted response с тем же source result, не новая LLM-проверка.

### 3.4 Таймеры: ограниченный lifecycle

Реальный executor поддерживает start 1..86400 секунд, remaining/list, cancel (один/все/номер из свежего списка/ID), missing-duration pending.
SQL-таблица: id/device_id/conversation_id/deadline/status. Имена, pause/resume, extend, restart, repeated intervals, absolute alarm, persistent reminders не реализованы. Данные scenario о них обязаны иметь future/blocked readiness до появления исполнителя.

### 3.5 Часы привязаны к серверу

`LocalTools.execute('clock')` использует `datetime.now().astimezone()` и честно говорит «По времени домашнего сервера». Это не capability произвольного города/IANA timezone. Международное «который час дома/там» требует явной timezone policy.

### 3.6 Generic text backend не исполнитель

`live_backend.py`: Luna получает tools=[], tool_choice=none, reasoning=none; верхняя граница2048 input tokens,512 output, один вызов за раз, нет retries. Простое помещение 400+ строк в prompt превысит бюджет или вытеснит полезный контекст. Нужен компактный отобранный contract/state, не весь каталог.

### 3.7 Данные каталога и разрешения должны оставаться раздельны

Текущий каталог не является allowlist. `execute_quick` проверяет can_configure_device; экспертный admission отдельный; C guest/RAM по умолчанию. Scenario match не должен обходить это.

## 4. Mapping внедрения

| Существующий путь | Что сохранить | Где добавить контракт |
|---|---|---|
| assistant-skills.json | Все existing IDs, category/path/readiness meanings,10 rules | Companion cases или обратно совместимое version2; поля acceptance отдельно от capability |
| skill_catalogue.py | catalogue cache, dialogue_instructions, summary | Loader/validator, компактный selection по активному домену, без grants |
| quick_intents.py + quick-intents.json | QuickIntent(intent,executor,slots,status,reason); full-command validation | Только проверенные read-only aliases; action grammar/slot validation остаются строгими |
| weather_queries.py | configured home followups, correction, date horizon | temporary place/metric slots; отрицания/quoted text; locale and date fixtures |
| settings_tools.py | source validation, verified home change, is_current | Одноразовый other-city read отдельно от setup; formatting по requested_metric |
| local_tools.py | timer storage/cancel, trusted local calculators | Новые timer operations только вместе с реальным state machine/migration; catalogue не включает их сам |
| live.py | route,execute_quick,tool_context,schedule_input_action,operation claim | Dialogue case/state policy до generic backend; concise result contract; preserve replay/race guards |
| live_backend.py | token/budget limits, no tools/retries | Tiny relevant response policy + permitted state only, без всего каталога |
| conversation_modes.py / expert_jobs.py | Mode switch vs one expert job | Scenario semantics distinctions; no extra consent for already-authorized nonpaid actions, existing expert admission preserved |
| device-renderer.js / presentation contracts | Actual timer/weather frames + face fallback | UI expectations из тех же executor results, не demo fixture как prod |
| tests/test_home_dialogue.py, test_live_native_tools.py | real Brain + mocked IO, no paid calls | Stateful case harness + held-out phrasings/side-effect/source/ACL assertions |
| docs/CURRENT_STATUS.md / REQUIREMENTS_MATRIX.md | Один паспорт и одна матрица | Actual implementation/evidence separately; no second competing status file |

Сохраняемые intents: timer_start,timer_remaining,timer_cancel,settings,clock_time,clock_date,clock_weekday,utility_*.
Weather actions — slots внутри settings: weather_current,weather_forecast,weather_status,weather_location,weather_find,weather_confirm,weather_cancel,weather_unsupported,weather_provider_unavailable,weather_other_place.
Новые action IDs в документе помечать proposed с mapping; не подменять реальные enum-функции.

## 5. Приёмка: что действительно проверять

1. Поддерживаемая команда исполняется ровно1раз даже при native transcript +late delegation/race.
2. «Поставь таймер» → одно уточнение → «на пять минут» → ровно1 timer,300s,widget с тем же ID.
3. Несколько таймеров → list → ordinal cancel на snapshot; без list нельзя угадать.
4. «Стоп» завершает разговор; таймер продолжает существовать согласно его собственному lifecycle.
5. Названная duration change не создаёт вторую запись молча; пока unsupported — честное ограничение.
6. Погода без города использует configured home; нет повторного geocode/configuration.
7. Current → tomorrow → wind сохраняет place/date; output содержит requested metric и источник.
8. «Нет, завтра» во время загрузки не позволяет late today result заговорить поверх.
9. Other-city query не меняет home; subsequent «а завтра там?» сохраняет временное место.
10. «Измени домашний город» отдельно проходит существующий setup/confirmation/source validation.
11. Tomorrow/week/weekend определяются по IANA timezone места; boundary midnight/future16days явно проверяются.
12. Weather source timeout/rate-limit/stale/incomplete различаются; не превращаются в «нет интернета» и не дают invented values.
13. Subject change/profile epoch invalidates scoped ellipsis.
14. Unavailable domain: exact+held-out paraphrases честно не исполняют; no invented success.
15. Общий вопрос об устройстве/цитата/отрицание не становится командой устройству.
16. Voice stop/decline_pending/expert_cancel/timer_cancel имеют разные scope.
17. Routine/alarm/reminder/calendar/music shopping source требуют readiness и identity; placeholder не считается connector.
18. Expert offer/confirm/start/result соблюдают one authorization→one job и no stale result transfer.
19. A↔C switch ждёт actual Live close; библиотека не меняет B/default model.
20. UI expected: same factual result, accepted widget/decoded image; sending scene недостаточно.
21. Русские числительные, «полторы», единицы, not/нет corrections — отдельные test cases.
22. Character count/model quota/budget не меняются; весь scenario inventory не добавляется в prompt.
23. Encrypted opt-in journal собирает достаточный synthetic trace; no actual household text в публичном repo.
24. Изолированно считать coverage: routing,executor,state,voice,screen,acoustic/hardware. Pass pytest не равно iPhone acceptance.

## 6. Точные источники

Все source URLs ниже закреплены на проверенном commit:

- AGENTS: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/AGENTS.md
- CURRENT_STATUS: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/docs/CURRENT_STATUS.md
- Каталог: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/assistant-skills.json
- Catalogue runtime: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/skill_catalogue.py
- Quick parser: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/quick_intents.py
- Weather slots: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/weather_queries.py
- Settings/executor: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/settings_tools.py
- Local timers/clock: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/local_tools.py
- Live routing: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/live.py
- Luna contract: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/services/brain/gobot/live_backend.py
- Inventory test: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/tests/test_skill_catalogue.py
- Existing stateful home tests: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/tests/test_home_dialogue.py
- Native tool race tests: https://github.com/anpavel84-afk/gobot-home/blob/effd1ff7be7150683ffacb0fa69934fd46142e87/tests/test_live_native_tools.py

Аудит статический; production runtime/домашний журнал/личные данные не читались; платные/Live/CLI вызовы не выполнялись; репозиторий не менялся.

