# GoBot vNext — утренний отчёт исполнителя

## Последующее поручение: ручная приёмка B на колонке

После подтверждения Owner веб B изолированный hardware adapter включён.
Runtime9819af68a04a191b6a51c4f9f1beb681fd427d64; gateway realtime_b,
firmware0.4.3 не менялась. Прежний аппаратный пакет8×60s/8responses×512/$1estimate
активирован без расширения caps/authorization. На момент включения8 remaining,
0 provider starts/0 pending hangups. Phone/C allowances и C unknown reserve сохранены.
22 free local peer/LiveKit tests +96 regressions PASS; no OpenAI calls.
Физический B разговор ожидает Owner (один tap→короткий вопрос→ответ→новый вопрос
без tap→удержание Stop). Не объявляется hardware/acoustic PASS заранее.
`scripts/board_b_enable.py rollback` возвращает gateway C config при idle без
отката ledger; исходная C quarantine остаётся. Полный текущий статус в CURRENT_STATUS.

## Последующий B dialogue repair

Runtime **3de2eaa53873437203339242c5f66fdecdf4944c**, preview assets b-dialogue-1.
Owner обнаружил, что B требовал касания и для записи, и для отправки. Причина:
preview override отключал NativeVoice.followup, а первый вопрос использовал PTT.
Теперь один явный Start включает server-ACKed VAD для первого вопроса; конец фразы
обрабатывается без второго касания. После обеих playback drain ACK и echo guard
микрофон включается автоматически в той же сессии. B остаётся полудуплексом.
10s silent waiting closes normally;30s unfinished speech/noise closes without
committing a truncated command. Stop/late ACK/double tap/stale turn защищены.
96 targeted free tests passed; JS fixture:3 answers/1session/0provider calls.
Real Chromium regression + actual private HTTPS/capability smoke passed. Phone
acoustic/provider acceptance NOT_RUN (Owner приглашён к ручной пробе). Нет новых
квот, developer paid trials, firmware/C/audio capture preset changes.
Официальный VAD контракт: https://developers.openai.com/api/docs/guides/realtime-vad .

## Дополнение: отказ ручного STT после отчёта

Owner сообщил «не работает». Логи подтвердили ошибку admission origin web_stt
(и такой же дефект web_tts), затем non-JSON500 ломал ответ шлюза. Ошибка была до
вызова STT API. Исправлено: строго два manual speech origins при прежнем Owner
binding/kind=realtime/spend caps; JSON403/502 вместо необработанных исключений.
46 targeted free checks passed, включая fake-provider HTTP success/limit refusal.
Текущий Brain runtime **be5474fcc33c4b171a5459984a555916fc1a225d**, web168faae.
Прежний process manager безопасно принял существующие workers без их перезапуска,
затем обновлены только Brain/web. WAL backup20261113T071057720168Z. Private HTTPS/
clock/real weather smoke PASS; financial policies/rows unchanged. Платная реальная
speech приёмка NOT_RUN; предыдущие2379 full tests относятся к версии до hotfix.
Это исправляет завышенную практическую оценку готовности manual speech в первом отчёте.

## 1. Открыть и проверить

**https://plan.tailffc57c.ts.net:18786/device-next** — работающий Owner preview.
На iPhone включить Tailscale, обновить страницу, выбрать «Гибрид».
Brain runtime **4beb530ffed6c40adab0541aac030e4688bcea2b**, web bundle source **168faae**.
Integration branch `codex/hybrid-web-vnext` поверх71dcb18, recovery032e4ea сохранён.
Техническая приёмка завершена 2026-11-13 04:01 UTC; PLAN timezone America/Sao_Paulo.
Флаг `run/night-train/preview-policy.json` включает прежний Owner phone и локальный
PLAN preview binding. Desktop binding не получает платный API admission.
Все paid checkbox в новой странице OFF. Старые /device,/demo2,A/B/C сохранены.

Baseline runtime:e623dde0821af18dac1067782470efd5d01bdbde. WAL-aware backup до работы:
`run/night-train/backups/20261113T024157Z`. Свежие deployment backups:
`20261113T034336796074Z` и `20261113T034853172723Z` в том же каталоге, включая
SQLite backup, policy/config, web-dist и runtime-source.zip. Секреты не опубликованы.

## 2. Готовность по возможностям

| Возможность | Статус и evidence | Что проверить Owner |
|---|---|---|
| Web hybrid/auth | WEB_READY, S2 HTTP/S3 настоящий HTTPS | Text, Start/Stop |
| Таймер/replay | INTEGRATION_PASS/BROWSER_PASS: настоящий SQLite/executor/renderer в изолированном scope | Создание/reload/истечение |
| Погода/followups | REAL_SOURCE_PASS: production Brain/Open-Meteo tomorrow→Saturday | Домашнее место, значок, период |
| Речь/числительные | FORMATTER_PASS; PROVIDER_NOT_RUN | Ручная слышимость/естественность |
| Voice Library |100/100 READY; production browser cached audio graph | Прослушать готовый клип |
| Narrator player | BROWSER_PASS: AudioContext, queue/pause/resume/Stop/ACK | Явно тестовый рассказ |
| Новая история | IMPLEMENTED; PROVIDER_NOT_RUN, ручная кнопка существующего gpt-6-luna | Только по желанию, API расход |
| Свой текст/TTS | IMPLEMENTED; PROVIDER_NOT_RUN, existing Speech/marin/Owner budget | Checkbox TTS, короткий текст |
| Browser B handover | CONTRACT_PASS; PROVIDER_NOT_RUN, input_text/audio-only fixture | Отдельная ручная проба |
| C handover | BLOCKED: quarantine/consumed recovery; text handover не принят | Не считать seamless готовым |
| Старые страницы | HTTP_PASS200 + browser regressions | Старые закладки |
| Hardware patch/build | FIRMWARE_PREPARED/FIRMWARE_BUILT | НЕ установлен, не acoustic PASS |

## 3. Что изменено

W0: фактический HEAD/WIP/runtime, сохранение локальных изменений, WAL backups.
W1: typed SkillManifest/IntentCandidate/RouteDecision/ActionResult/AnswerEnvelope.
W2: deterministic dispatcher поверх Quick Intents, bounded compound preflight,
scoped pending/weather frames, server-issued operation/action IDs/replay receipts.
W3: прежние таймеры/SQLite, Open-Meteo, speech/display envelope и реальные widgets.
W4: inventory/dry-run готовых клипов, RAM story jobs и настоящий Web Audio player.
W5: Owner-only /device-next/API в том же Brain и прежнем private web gateway.
W6: бесплатные тесты/browser QA/self-review. Independent Gemini/holdout NOT_RUN.
W7: safe deployment, два guarded idle-only Brain+web restart: первоначальный и
исправление дефекта реального weather smoke. Другие сервисы/LiveKit/board gateway
не перезапускались; active turns/B/C/media=0. W8: contract/candidate без установки.

Checkpoints:46fb07b docs-only пакет Owner325c331;8d7aabe contracts;ebac9c4 router;
d11a86f web/player;0c8d7ae rollout/build;4beb530 source fix;168faae cached status.
NOT_CHANGED: master, installed0.4.3/NVS/KWS, C audio transport, финансовые grants/
policy/ledger, чужая инфраструктура. Общий weather adapter получил только исправление
проверки выбранных дней; голосовая архитектура/модель C не менялась.

## 4. Испытания

- Полный pytest до последнего source fix:exit0,2376 passed/18 skipped/1 xfailed/
  118 subtests,229.33s; private `run/night-train/full-tests.xml`.
- Затем73 targeted tests exit0, включая новые regressions. После weather fix:
  559 weather/context/hybrid/API checks exit0,49.39s; `weather-hotfix-tests.xml`.
- Финальный `python -m pytest -q --junitxml=run/night-train/final-tests.xml`: **exit0,
  2379 passed,18 skipped,1 xfailed,118 subtests,260.48s**. Это итоговый прогон после
  source fix и уточнения fixture выбранного дня; предыдущее падение не скрывается.
- Router dataset150 authored semantic cases:40 direct,25 context,20 compound,
  25 indirect,20 free,20 unavailable. Независимого holdout нет.
-34 API/security/media regressions отдельно от корпуса: scope/epoch, replay,
  stale/forged ACK, concurrency, client authority injection, no-paid boundaries.
- `python tests/night_browser.py`:exit0, Chromium1243,390×844, production JS/API на
  fixture DB/HTTP. Реальный AudioContext, timer restore, weather followups,
  pause/resume/Stop, no overflow/JS exceptions; paid boundary calls=[].
- `python tests/night_private_browser.py`:exit0, настоящий private HTTPS без TLS
  bypass, clock + cached clip,100/100 inventory, без новых provider calls.
- `python scripts/night_smoke.py`:exit0; /device-next,/device,/demo2/assets200,
  local clock verified, реальный Open-Meteo tomorrow→Saturday success; foreign
  Host403, authority injection422. Financial tables/policies совпали с WAL backup.
- JS syntax checks exit0. Voice-library dry-run:0 requests,missing0,цена неизвестна.
- Server flag rollback проверен реально: preview403, прежний /device200;
  флаг восстановлен, ledger не менялся.

Исправлены resume/audio-lock race, late STT после Stop, «не надо» при pending,
ложная подпись «B завершён» при cached playback без B. Реальный источник выявил
null в16-м дне: раньше он ломал даже полный прогноз на завтра. Теперь глобально
проверяется календарь, а числовые данные — запрошенных дней. Missing requested
facts по-прежнему дают отказ, не нули. Первый firmware compile выявил missing
include; preparation script исправлен, rebuild PASS. Никакие проверки не отключены. Регрессия cache eviction уточнена: null помещён
именно в запрошенный день1 вместо незапрошенного дня0; отказ/eviction продолжают
проверяться. Отдельный тест подтверждает, что дальний null не ломает завтра.
Fixtures синтетические; household transcripts/coords не публикуются. Скриншоты и
JSON приватно `run/night-train/browser/`. iPhone/Spotpear acoustic NOT_RUN.
Полезный voice TTFA/p95 не измеряли. Audio graph и сигналы не доказывают слышимость.

## 5. Расходы и C incident

Automatic paid calls нового harness:0 на перехваченной provider boundary.
Production smoke запросил только local tools/Open-Meteo/cached WAV. Все financial
rows Live/Realtime/Owner и policy совпали с deployment backup. Grants не использованы.
C:221 confirmed seconds/$0.1841667 по прежней проектной оценке; один старый orphan
final=false, последние15 наблюдавшихся секунд не final. Reserve60s/$0.05 сохранён;
**это не предел неизвестного конечного счёта**. Local release не подменяет provider
close ACK. Одно recovery разрешение использовано ранее (51confirmed sec), не продлено.
Новый C тест ночью не запускался; карантин не мешает household preview.
Hardware B: отдельный8×60s,8responses×512,$1estimate,gpt-transcribe пакет OFF,
не deployed/provider-tested. Browser B использует прежний phone admission, не этот
пакет. Нет увеличения до5 минут, новых моделей или автоматических платных retries.
Subscription CLI/reviewer не вызывался; цену текущей инженерной Codex-сессии не
оценивали. Manual STT/TTS: существующий Owner budget, отдельные origins, консервативная
pending оценка .50USD/call; actual usage adapters PROVIDER_NOT_RUN. Hard money cap
не гарантирован. Mass synthesis не выполнен. Истории/текст RAM, remember=false,
личный архив не подключён. Timer operational receipts не являются semantic memory.
Новый preview не заявляет полный encrypted text journal каждого события.

## 6. Аппаратная подготовка

[Contract и preparation script](../../firmware/spotpear/vnext/CONTRACT.md).
Installed до/после:0.4.3-dev-media-ready, без flash/OTA/NVS/wake_to_brain.
Candidate0.4.4-night-contract, отдельная копия vmi3510488:
`/opt/gobot-firmware/20261112-gobot-v1/night-train-stage-v1/build/xiaozhi.bin`.
2711488bytes, SHA256 fe624dc9f020c4be738d05bb458cf800dcc16990a3ee4d1e8a5a2c3282b0d141.
Pinned IDF6.0.1 container/network none/no devices, esp-sr2.4.7 неизменён;
partition34%free. Runtime RAM/performance не измерены. Contract3/scene2,
playback activity_only/segment_position=false. Не precise playhead и не полный
аппаратный narrator port. FIRMWARE_BUILT не означает INSTALLED/HARDWARE_ACCEPTED.

## 7. Утренняя проверка — шесть действий

1. С Tailscale откройте URL, «Гибрид», без paid checkbox. Введите «Поставь таймер
   на три минуты», обновите страницу: один отсчёт должен сохраниться.
2. «Какая погода завтра?» → «А в субботу?» → «Точно?»: прежнее домашнее место,
   правильный период/значок/числа; при source failure нет скрытого B/C.
3. «Поставь таймер» → «Который час?» → «Да»: часы отвечают, позднее согласие
   не запускает таймер. «Не ставь таймер на пять минут» не создаёт действие.
4. Явно откройте тестовый рассказ: play/pause/resume/Stop. Сигналы обозначены
   тестовыми, не сказкой от модели; после Stop нет позднего звука.
5. В голосовой библиотеке выберите готовый клип. Новый synthesis не нужен.
   Свой текст/TTS и новая история Luna — отдельные ручные функции, расходующие API.
6. По желанию, в прежнем phone admission: включите STT для короткой команды либо
   Direct B + consent. Это платная ручная проба, ночью NOT_RUN. C не обозначен
   готовым новым handover. /device и /demo2 остаются доступны.

## 8. Откат

Из C:/Users/PLAN/gobot/GoBotHome:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/night_preview.py disable
```

Preview сразу403, прежний https://plan.tailffc57c.ts.net:18786/device остаётся200.
Таймеры/пользовательские изменения/ledger не удаляются. Обратное включение:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/night_preview.py enable
.venv/Scripts/python.exe -X utf8 scripts/night_preview.py status
```

Полный source rollback — отдельная idle maintenance операция: runtime-source.zip
и web-dist из backup развернуть в отдельный checkout; восстановить только код/web,
штатно один Brain на прежней production DB. Financial DB не накатывать поверх
новых записей, reset/clean не использовать. Проверенный быстрый rollback — флаг.
Firmware rollback не требуется: она не менялась.

## 9. Ограничения

WEB_READY household vertical slice, не PASS всех голосовых модулей. B handover,
manual STT/TTS/Luna, iPhone acoustics PROVIDER_NOT_RUN. C incident/text handover
BLOCKED без нового risk approval. Compound: два полных local действия; tool+story/
conversation пока clarification без первого side effect. Semantic plugin OFF;
HassIL не установлен. Rain-window/hourly данных нет, не придумываются. Дальний
день может отсутствовать. Gemini/holdout и hardware installation NOT_RUN.
Private archive/неизвестные integrations/precise hardware resume не активированы.
Heard-only context вычисляется и защищён в API; его полный переход из рассказчика
в реальный B/C разговор ещё не принят. Полный narrator→conversation маршрут NOT_RUN.
Невидимого фонового train/stress test после этой сессии не будет.
