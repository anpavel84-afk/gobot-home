# GoBot vNext — утренний отчёт исполнителя

**Это пустой шаблон. Публикация пакета не означает выполнения работ. Все начальные статусы — NOT_RUN.**

## 1. Открыть и проверить

- Реальный URL web preview: **NOT_DEPLOYED**.
- Время завершения / timezone: **NOT_RUN**.
- Runtime commit / branch / process build: **NOT_VERIFIED**.
- Последний рабочий baseline и сохранённый rollback: **NOT_VERIFIED**.
- Изменённые feature flags / кому доступен новый режим: **NOT_RUN**.
- Нужно ли пользователю обновить страницу и какой режим выбрать: **NOT_RUN**.

Исполнитель заменяет поля фактами. Не придумывать URL/успешный deployment. Не раскрывать secrets, raw session IDs, домашние координаты или частные разговоры.

## 2. Готовность по возможностям

| Возможность | Реализация | Evidence level | Что проверить Owner |
|---|---|---|---|
| Web hybrid + auth | NOT_RUN | none | Открытие, Start/Stop, route status |
| Таймер и replay | NOT_RUN | none | Одна команда — один таймер |
| Погода и followups | NOT_RUN | none | Завтра / суббота / смена места |
| Речь и числительные | NOT_RUN | none | Слышимость и естественность |
| Voice Library | NOT_RUN | none | Ready clips против missing |
| Рассказчик player | NOT_RUN | none | Pause/resume/Stop и позиция |
| Генерация новой истории | NOT_RUN | none | Разрешённый provider либо blocker |
| B handover/полудуплекс | NOT_RUN | none | Реальная ручная сессия отдельно |
| C handover/эталон | NOT_RUN | none | Инцидент/готовность отдельно |
| Старая /device и /demo2 | NOT_RUN | none | Не сломаны |
| Hardware contract/patch | NOT_RUN | none | Совместимость и оставшийся gap |
| Firmware candidate build | NOT_RUN | none | Сборка не установка |

Допустимые статусы различать: IMPLEMENTED_NOT_TESTED, FIXTURE_PASS, INTEGRATION_PASS, BROWSER_PASS, PROVIDER_NOT_RUN, HARDWARE_NOT_RUN, BLOCKED. Не сводить всё к одному PASS.

## 3. Что действительно изменено

Короткая карта файлов/коммитов и runtime deployment. Какие старые функции переиспользованы, какие новые. Отдельно перечислить NOT_CHANGED: установленная прошивка, master, C transport, чужая инфраструктура, quotas/ledger. Если что-то из этого всё же изменено по отдельному разрешению — указать точное основание и diff, не замалчивать.

## 4. Испытания

Команда → версия/среда → exit code → количество кейсов → артефакт. Базовый корпус и holdout отдельно. Новые failures / baseline failures / skipped / xfailed объяснены.

Реальные данные против fixtures, настоящий player против mock, browser automation против iPhone/hardware акустики. Метрики: n, условия прогрева, clocks, p50/p95 только где обоснованно. Полезный звук отдельно от filler.

## 5. Расходы и C incident

- Автоматические paid provider calls: **NOT_MEASURED**, не подставлять 0 без evidence.
- Изменение ручных grants/counters: **NOT_VERIFIED**.
- C local_resources_released / provider_close_confirmed / final_usage: **NOT_VERIFIED**.
- Старый unknown usage/reserve/provenance: сохранение **NOT_VERIFIED**.
- B budget и admission readiness: **NOT_VERIFIED**.
- Разрешённый developer subscription executor и фактическое использование, если доступно: **UNKNOWN**, не выдумывать денежную оценку.

## 6. Аппаратная подготовка

Установленная версия до/после (должна остаться прежней), patch path, protocol version/capability negotiation, build command/result, binary SHA, partition/RAM notes и точные будущие действия. Flash/OTA: **NOT_PERFORMED** в рамках этого задания. Build host недоступен — явно указать, что подготовлен только patch, а не бинарник.

## 7. Ручная проверка — минимальная последовательность

Дать 4–6 действий из ACCEPTANCE, ожидаемый смысл результата и пример ошибки. Сначала text/бытовые функции без B/C, затем только разрешённые ручные голосовые маршруты. Указать, какие ручные затраты могут возникнуть. Не просить Owner перепроверять каждый unit test.

## 8. Откат

Точный server-side flag/config rollback, bundle/commit и штатная команда при необходимости. Возврат не удаляет новую финансовую историю или пользовательские данные. Проверка старого /device и health после rollback. Никаких `git reset --hard`/drop DB/очистки ledger.

## 9. Что не готово и почему

Для каждого blocker: пользовательское влияние, причина, evidence, безопасный обход в текущих правах, следующий необходимый шаг. Не выдавать отсутствующий доступ/бюджет за дефект модели. Не обещать фоновое продолжение после завершения этого прогона.
