# Происхождение решений и выверка ответа Gemini

Дата проверки публичных источников: 12 ноября 2026. Ни один внешний пример не подтверждает скорость, качество акустики или готовность GoBot автоматически.

## 1. Источники текущего проекта

- [P1: pinned CURRENT_STATUS](https://github.com/anpavel84-afk/gobot-home/blob/0eb36f775ab9a776b0490b93812cb1f3be612a91/docs/CURRENT_STATUS.md).
- [P2: draft hardware/voice PR #1](https://github.com/anpavel84-afk/gobot-home/pull/1), прочитан head `0eb36f775ab9a776b0490b93812cb1f3be612a91`.
- [P3: quick_intents.py](https://github.com/anpavel84-afk/gobot-home/blob/0eb36f775ab9a776b0490b93812cb1f3be612a91/services/brain/gobot/quick_intents.py) и [routing.py](https://github.com/anpavel84-afk/gobot-home/blob/0eb36f775ab9a776b0490b93812cb1f3be612a91/services/brain/gobot/routing.py) — точки для проверки и расширения исполнителем.
- [P4: существующая целевая спецификация](https://github.com/anpavel84-afk/gobot-home/blob/0eb36f775ab9a776b0490b93812cb1f3be612a91/docs/GOBOT_HOME_TARGET_SYSTEM.md). Её исторические разделы не заменяют текущую runtime-проверку.
- [P5: speech-openings build report](https://github.com/anpavel84-afk/gobot-home/blob/0eb36f775ab9a776b0490b93812cb1f3be612a91/docs/speech-openings-build.json) — ранее подготовленная библиотека, не готовность любых новых фраз.

Owner в текущем диалоге сообщил о локальном `032e4ea`, 53 бесплатных тестах, согласовал ограниченное восстановление C и затем разрешил новый web-first этап. Это **данные владельца**, не независимый аудит локального runtime. Публикуемый пакет не выполняет recovery/deployment/paid tests.

## 2. Что принято из ответа Gemini

Сценарная маршрутизация до оплачиваемой сессии; context-aware pending; LastActionFrame как краткоживущее состояние; candidate preselection; отдельные IntentCandidate/Policy Gate; общий Tool Executor; рассказчик с позицией; разделение протоколов B/C; честные unavailable; офлайн-корпус 150 кейсов. Эти положения включены как проектные требования, а не как уже существующие функции.

## 3. Исправления и ограничения

| ID | Положение исходного отзыва | Выверенное решение |
|---|---|---|
| ADR-01 | Локальный разбор Home Assistant «всегда» предшествует LLM | В документации это зависит от настройки/агента. Берём policy pattern, не универсальное свойство всех установок [S4]. |
| ADR-02 | `response.create` с audio и text одновременно для B | В актуальном Realtime выбирают одну output modality; audio уже сопровождается transcript. Использовать контракт реальной версии адаптера, не смешивать старые поля [S1]. |
| ADR-03 | Делить по союзам и сразу выполнять понятную первую часть | Только ограниченный структурный план с проверкой всей фразы и preflight. Цитаты, условия и неразобранный хвост не допускают молчаливого side effect. Это наш проектный safety decision. |
| ADR-04 | `hash(device+turn+tool+args)` как универсальная дедупликация | Логическая operation/action identity отделена от payload. Иначе два намеренно одинаковых действия ошибочно сливаются. Это вывод из предложенного ключа, не установленный баг GoBot. |
| ADR-05 | Глобальные Стоп/Отмена выполняются безусловно | Только проверенная управляющая реплика и явный scope. Отрицание/цитата не действие; Stop вывода не отмена всех таймеров. |
| ADR-06 | Полностью отключить внешнюю обработку в ACTIVE_B/C | Не дублировать STT/предсессионный classifier, но сохранить текущие native transcript/tool pathways и единый arbiter [P1]. |
| ADR-07 | LastActionFrame делает продолжение «за 0 ₽» | Он убирает необходимость отдельного LLM-вызова. Стоимость распознавания, озвучивания и сервера остаётся отдельной. |
| ADR-08 | Нет лексического маркера — обязательно открытый вопрос | Это эвристика, а не полнота языка. Косвенные task requests/ambiguity требуют отдельного тестирования и безопасного уточнения. |
| ADR-09 | 0% slot hallucination / 100% schema compliance как гарантия модели | Validator никогда не исполняет невалидные данные. Нулевая observed ошибка на корпусе не доказывает универсальную безошибочность. |
| ADR-10 | C audio replay или неизвестный start event обеспечивает бесшовный вход | Кандидаты остаются gated; не выдумывать protocol event и скорость replay. `session.input` и Realtime trigger различаются [S2,S3]. |
| ADR-11 | Карантин ограничивает реальное списание | Нет: локальное разрешение работы не прекращает provider billing. Finalization и release независимы [S2,S6]. |
| ADR-12 | Порог RMS отделяет близкого пользователя от ТВ | Ночной scope использует лишь bounded recording/control; ни идентичность, ни близость по энергии не обещаются. |
| ADR-13 | Любой story summary подходит для вопроса по сюжету | В handover только услышанная часть, иначе появляются спойлеры и ложное предположение о прослушивании. |
| ADR-14 | Успешный текстовый pipeline гарантирует «утром готов весь продукт» | Требуются реальные runtime/browser evidence. Provider/hardware/manual acceptance остаётся отдельно. |

## 4. Проверенные первичные источники

**S1 — OpenAI Realtime conversations:**
https://developers.openai.com/api/docs/guides/realtime-conversations

Подтверждает создание текстового user item и запрос ответа; выбирать один output modality, audio включает transcript. Это основание для B contract tests, не доказательство готовности аппаратного B.

**S2 — Managing GPT-Live sessions:**
https://developers.openai.com/api/docs/guides/live-conversations

Основание для раздельных session/context/lifecycle contract. Не переносить события B в C без адаптера.

**S3 — Migrate to GPT-Live:**
https://developers.openai.com/api/docs/guides/live-migration

Переходы и делегированные backend responses имеют иной смысл, чем Realtime manual response triggering. Implementer сверяет актуальный контракт перед изменением.

**S4 — Home Assistant sentence/conversation documentation:**
https://www.home-assistant.io/triggers/conversation/
https://contributors.home-assistant.io/core/entities/conversation/
https://www.home-assistant.io/integrations/conversation/

В документации отдельных LLM conversation agents sentence triggers зависят от включения Prefer handling commands locally. Это не основание ставить весь Home Assistant внутрь GoBot.

**S5 — Open-Meteo forecast documentation:**
https://open-meteo.com/en/docs

Использовать определения current/hourly/daily, единицы, timezone и интервалы. Этот пакет задаёт formatter/interpretation rules, а не делает живой прогноз. Коммерческие условия проверяются перед продажами; нынешняя интеграция не гарантирует бесплатную массовую эксплуатацию.

**S6 — Live primary WebSocket reference, session.closed:**
https://developers.openai.com/api/reference/resources/live/primary-websocket

Finalization event несёт итоговый cumulative usage; отсутствие события при закрытии соединения не подтверждает финализацию. Данные локального ledger и риск не подменяются расчетной формулой «ещё 30 секунд».

**S7 — HassIL:**
https://github.com/OHF-Voice/hassil

Парсер шаблонов/списков/контекста — кандидат маленькой зависимости. Наличие библиотеки не подтверждает миллисекунды на PLAN. Перед импортом кода/корпуса проверить точную лицензию и attribution выбранной версии.

**S8 — Realtime VAD:**
https://developers.openai.com/api/docs/guides/realtime-vad

`interrupt_response` и создание ответа настраиваются раздельно. Программный запрет barge-in сам по себе не доказывает, что весь микрофонный поток правильно закрыт во время Speaking; это проверяется в клиентском адаптере.

## 5. Референсы из согласованного обсуждения

XiaoZhi (`78/xiaozhi-esp32`) — основа аппаратуры; KALO — пример разделения режимов; xiaozhi-esp32-server — сравнение intent_llm/function_call; Pipecat — подход к очередям/прерываниям; ElatoAI — продуктовая организация устройств. Их возможности не добавляются молча в scope и не доказывают совместимость Spotpear.

Исходный ответ Gemini предоставлен Owner в диалоге. Документ сохраняет его терминологию и основные предложения, но явно перечисляет исправления выше. Факты, предложения и гипотезы не смешиваются: новая архитектура — требование следующей реализации, не описание уже развёрнутой системы.
