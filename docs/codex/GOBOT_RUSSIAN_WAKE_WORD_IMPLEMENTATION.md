# OWNER DIRECT · GoBot Home · локальное пробуждение «ГоБот» на ESP32-S3

Дата: 12 ноября 2026 года. Задание исполнителю Codex. Язык отчётов — русский.

## 0. Суть поручения

Довести **физическое устройство Spotpear ESP32-S3** до работающего локального голосового пробуждения **строго по русскому слову «ГоБот»**, без кнопки как основного способа активации и без постоянной передачи бытового аудио на сервер. Использовать **готовую, публично документированную архитектуру microWakeWord / ESPHome / TensorFlow Lite Micro** и опубликованный практический кейс обучения русского слова, а не придумывать с нуля очередной простой классификатор или транслитерацию в английскую MultiNet.

Критерий успеха — владелец произносит обычным русским голосом «ГоБот», гаджет явно переходит в состояние «Слушаю», принимает вопрос (с паузой либо в той же фразе), обращается к **существующему GoBot Brain** и выдаёт ответ. После завершения действительно восстанавливает локальный детектор. Повторные обращения работают без USB, кнопки, перезагрузки, переподключения к китайскому сервису или изменения сети.

**Не включать и не тестировать «Привет ESP», «Hi ESP», «Hey Jarvis», «Софья» или другое слово как промежуточный пользовательский вызов.** Эти кейсы — примеры технологий, а не желаемое поведение. Не подменять русский «ГоБот» английским «go bot». Ранее разрешённый временный запуск касанием остаётся и не удаляется. Не возвращать «на экране есть лицо, но устройство ничего не делает».

Владелец ранее разрешил именно этому экземпляру безопасную прошивку и разработку. Общего подтверждения начать снова не спрашивать. Но безопасность аппаратной записи, проверка backup/recovery, защита NVS, платные API-consents, лицензионные ограничения и системные подтверждения не отменены.

Задача — **реальный код → рабочая обученная/адаптированная модель → ESP-IDF firmware → проверка на плате**, а не очередная презентация, общая стратегия или обещание отдать работу другому агенту.

## 1. Зафиксировать актуальный исходный проект, прежде чем что-либо менять

Репозиторий: https://github.com/anpavel84-afk/gobot-home

На Windows PLAN рабочая папка:
    C:\Users\PLAN\gobot\GoBotHome

Сборочный Linux-узел (общий с другими проектами):
    vmi3510488:/opt/gobot-firmware/20261112-gobot-v1/

Последняя доступная read-only проверка PLAN во время подготовки задания показала:
- локальный HEAD a3791bd — «Install touch-first Spotpear UI, separate microphone processing from KWS and scope Live media»;
- перед ним 531caf9, a36c066, b1761e0;
- незакоммиченные изменения в services/voice/gobot_device_gateway.py и tests/test_spotpear_live_media.py;
- есть firmware/spotpear/touch_release.json, описывающий candidate 0.2.1-dev-touch-audio;
- работоспособность слова «ГоБот» и фактическая версия, загруженная на плате на момент НОВОГО запуска, не установлены — проверить заново.

Это snapshot, не требование откатиться на эти SHA. Сначала собственным чтением проверить git log/status, текущие процессы Codex/сборки/COM, USB, OTA slot, UART и текущую версию firmware. Сохраняй все dirty changes; отдельный branch/worktree для KWS. Никаких reset --hard, clean -fd, force-push и перезаписи незафиксированных файлов. Не переключать PLAN на старую документальную ветку codex/gobot-firmware-handoff-20261112; прочитать документ отдельно через git show/URL.

Первое чтение:
- AGENTS.md
- docs/CURRENT_STATUS.md
- docs/GOBOT_HOME_TARGET_SYSTEM.md
- docs/HARDWARE_CHECKLIST.md
- docs/REQUIREMENTS_MATRIX.md
- docs/DEVICE_MODE.md
- docs/PROTOCOL.md
- firmware/README.md
- firmware/spotpear/acceptance.json
- firmware/spotpear/touch_release.json
- firmware/spotpear/prepare_touch.py
- firmware/spotpear/touch_methods.inc
- firmware/spotpear/gobot_turn_guard.h
- firmware/spotpear/gobot-native.patch
- firmware/spotpear/prepare_bringup.py
- firmware/spotpear_bringup.py
- services/voice/gobot_device_gateway.py
- services/voice/spotpear_live.py
- design/visual-language/README.md, STYLEGUIDE.md и актуальные scene contracts

Предыдущие задания, только для контекста:
- docs/codex/GOBOT_FIRMWARE_IMPLEMENTATION_PROMPT.md
- docs/codex/GOBOT_TOUCH_UI_PRODUCT_CONTINUATION.md
в документальной ветке codex/gobot-firmware-handoff-20261112.

В последнем релизе touch-first KWS был намеренно выключен, чтобы неисправная модель не ломала касание. Поэтому **не достаточно поменять флаг CONFIG_USE_CUSTOM_WAKE_WORD**: нужна реально работающая модель и обособленный runtime, подключённый к общему StartGoBotTurn. Не терять уже сделанные дисплей/скины/жесты, device enrollment, VAD, Opus и Brain.

## 2. Проверенные источники и почему выбран именно этот путь

### [R1] Open Home Foundation microWakeWord — основной алгоритм и training

https://github.com/OHF-Voice/micro-wake-word
https://github.com/OHF-Voice/micro-wake-word/blob/main/README.md

Публичная обучаемая система streaming keyword spotting для TensorFlow Lite Micro. По README: 16 kHz mono; 40 спектральных признаков, обновление каждые 10 ms; потоковая inference и сглаживание вероятности на нескольких окнах. Важны не одни веса, а **точно соответствующий training frontend**, состояние стриминга, нормализация и thresholds. Авторы прямо предупреждают, что обучение качественной новой фразы непросто.

### [R2] ESPHome micro_wake_word — референс *работающей на ESP32-S3* embedded-интеграции

https://esphome.io/components/micro_wake_word/
https://github.com/esphome/esphome/tree/dev/esphome/components/micro_wake_word
https://github.com/esphome/esphome/blob/dev/esphome/components/micro_wake_word/micro_wake_word.cpp
https://github.com/esphome/esphome/blob/dev/esphome/components/micro_wake_word/streaming_model.cpp

Именно сюда смотреть при переносе: TFLite Micro interpreter / mutable op resolver, audio frontend, кольцевые буферы, wake/VAD probability windows, model load/unload, FreeRTOS task, bounded queues, stop/start, watchdog, resource allocation и события обнаружения. Документация допускает собственный model manifest, probability_cutoff/sliding_window_size и отдельный VAD для снижения ложных пробуждений.

**Не переписывать весь GoBot на ESPHome и не заменять Brain на Home Assistant.** Переиспользовать только совместимые части и идеи KWS с выполнением license/NOTICE. Это отдельный native ESP-IDF-компонент внутри текущей прошивки GoBot. Официальный компонент ESPHome зависит от его собственного окружения; source не обязан компилироваться «копированием одного .cpp».

### [R3] Espressif esp-tflite-micro — реальная ESP-IDF-библиотека вывода TFLite

https://github.com/espressif/esp-tflite-micro

Официальный ESP-IDF-компонент TFLite Micro, заявляет поддержку IDF 6.0 и 5.5. Выбрать совместимый pinned release, точно нужные INT8 ops и необходимый tensor arena; проверить ABI и coexistence с текущим esp-sr аудиофронтендом. Не включать AllOpsResolver без оценки memory/flash. При необходимости использовать vendor kernels esp-nn, если доказана применимость/корректность. Измерить heap/PSRAM и worst-case frame time на S3.

### [R4] Реальный русский кейс «Джарвис» с обучением собственного слова — главный практический образец

https://github.com/interkelstar/microwakeword-trainer
https://github.com/interkelstar/microwakeword-trainer/blob/main/example_ru_jarvis.yaml
https://github.com/interkelstar/microwakeword-trainer/blob/main/negative_phrases_ru.txt

Опубликованный автором пайплайн для русского слова «Джарвис» на microWakeWord: синтез русскими Piper-голосами (Denis/Dmitri/Irina/Ruslan), негативные и похожие фразы, training/feature extraction/export в quantized streaming TFLite, проверка на *реальных* записи/ложных срабатываниях. В README автор сообщает 47/50 реальных положительных обращений и 1/140 сложных отрицательных, модель около 82.5 KB. **Это самозаявленные результаты другого слова, не гарантия наших метрик.** Самый ценный урок: mining тяжёлых false positives, speaker-disjoint evaluation, реальная бытовая речь, а не только разные синтетические голоса.

Проверить фактически существующие scripts, версии, license и команды в выбранном commit; не полагаться на команду из README, если скрипт в repo был переименован. Не переносить готовую модель «Джарвис» или сервис ElevenLabs в GoBot без нужды и лицензии. Зафиксировать собственный reproducible config только для «ГоБот».

### [R5] Дополнительный конвейер customWakeWord — образец dataset и evaluation, НЕ совместимость форматов

https://github.com/temm1e-labs/customWakeWord
https://github.com/temm1e-labs/customWakeWord/blob/main/RELEASE_PROTOCOL.md

Полезны: генерация ~разных голосов, негативных близкозвучных фраз, room-impulse-response, окружающих шумов, adversarial evaluation, измерение FAR/FRR. Но автор прямо отмечает: выход INT8 .tflite для ESPHome **НЕ загружается** в stock XiaoZhi ESP-SR/WakeNet. У Espressif свой proprietary model binary. Никакого «переименовать .tflite в wn9.bin» и никакой мнимой универсальной конвертации. Repo может рекомендовать платные GPU-сервисы (RunPod): без отдельного разрешения их не запускать.

### [R6] Опубликованный русский .tflite «Эй Кузя» — только подтверждение существования русских моделей

https://microwakeword.com/library/1482

INT8 TFLite, 59 KB, опубликованный benchmark 86.8% recall с шумом и 0.76 false activations/hour. Это модель ДРУГОГО слова и не критерий приемки GoBot. На сайте личное/некоммерческое лицензирование по умолчанию; GoBot имеет потенциальное коммерческое применение. **Не встраивать готовые чужие модели без проверки лицензии и не требовать регистрацию/платную облачную тренировку**, если возможен воспроизводимый локальный training.

### [R7] Официальный ESP-SR WakeNet10 — альтернативный коммерческий путь, НЕ самодельная MultiNet7

https://github.com/espressif/esp-sr
https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/wake_word_engine/ESP_Wake_Words_Customization.html

ESP-SR с сентября 2026 сообщает русский WakeNet10, в списке есть заранее обученное «Привет ESP». **Это подтверждает поддержку русского в семействе моделей, но НЕ существование готового «ГоБот».** Для собственных WakeNet-слов Espressif предлагает платную кастомизацию через производителя. Не заказывать её без разрешения и не считать это бесплатным self-service training. Английская MultiNet7 и фонетическое описание русского «ГоБот» ранее провалились на плате (0/3 synthetic positives): это закрытая неудачная гипотеза, не основной путь новой итерации.

### [R8] Русская статья Хабра про ESP32-S3/XiaoZhi — контекст готовой поддержки wake

https://habr.com/ru/articles/1005272/

Автор собрал русскоязычную XiaoZhi-колонку и включал имеющееся preset wake word «Софья» через WakeNet/ESP-SR. Это **не обученная модель «ГоБот»** и не повод подменять наше слово. Подтверждает, что класс ESP32-S3/XiaoZhi способен локально реагировать на wake при наличии правильных весов.

### [R9] Две ссылки, присланные владельцем

https://narodstream.ru/esp32-urok-44-soprocessor-ulp-pervoe-znakomstvo/

ULP у классического ESP32 — вспомогательный маломощный сопроцессор для событий и deep sleep. Он не является готовой нейросетью обнаружения русского слова. Для нынешней платы с USB-питанием оптимизацию ULP отложить; сначала низколатентный wake через core ESP32-S3. Не переносить из этой старой статьи ассемблер/настройки ULP классического ESP32 в S3 без проверки.

https://www.stork.ai/blog/a-10-chip-just-learned-to-hear
https://github.com/andrisgauracs/whistle-esp32

Материал про Whistle: **полная офлайн-транскрипция коротких команд**, а не мгновенное KWS. Фактический пример Whistle после урезания использует около 14.5 MB модели на плате N16R8, значительно дольше одной wake inference и в описанном demo поддерживает семь языков **без русского**. Он реализует hold-to-talk. В нашем 16 MB Flash уже находятся GoBot app/assets, поэтому перенос чужого Whistle demo ломает partition budget; для «ГоБот» не подходит. Не тратить время на Whistle в этой итерации.

### [R10] Реальный код устройства — обязателен

Исходники/коммиты GoBot перечислены в §1. Наш runtime — **ESP-IDF + XiaoZhi-based drivers, 24 kHz ES8311 mic/speaker, GC9A01 LCD, CST816D touch (наличие подтверждать), 16 MiB Flash, 8 MiB PSRAM**. Не делать второй сервер, второй Bluetooth-мост, вторую память или полную миграцию на ESPHome.

## 3. Выбранное инженерное решение

**Primary track: обучить русское «ГоБот» в системе microWakeWord → экспортировать quantized streaming TFLite → портировать inference/frontend из проверенного ESPHome-подхода через esp-tflite-micro в нашу существующую ESP-IDF прошивку → передать событие реальному StartGoBotTurn("wake").**

Не начинать очередной фонемный эксперимент с английским MultiNet7. Не писать простенький MFCC+linear/ridge/template detector с нуля, не объявлять TFLite без рабочего embedded runner. Никаких чужих слов пробуждения для демонстрации.

Сначала **короткий hardware gate**: физический codec, sample rate, сырые уровни/обрезание, фактический буфер 24 kHz I2S и ресемплинг в 16 kHz mono, CPU, наличие PSRAM. При проблеме с микрофоном исправить её отдельно: при изначальном неверном gain не поможет никакая тренировка.

Реализовать собственный ясный boundary, например GoBotLocalWakeDetector:
- initialize(model, frontend, thresholds) → readiness/error;
- start_idle(), stop_for_turn(), pause_for_playback(), mute(), unmute(), reset_session();
- feed_audio(const int16_t*, samples) в корректном 16 kHz;
- on_detected callback в **основной device task**; не трогать LVGL и сеть из inference callback;
- counters: frames, underruns, inference latency, probability, detected, rejected_by_vad, suspended, dropped, overrun; без записи аудио/личных транскриптов;
- исключить повторное срабатывание от одного слова, от собственного TTS и от stale audio/прошлой сессии.

Совместимость audio:
- ESP32 hardware codec на 24 kHz, KWS frontend должен получить именно 16 kHz mono без перепутанных каналов/байтов/масштаба;
- обеспечить воспроизводимый feature parity test против Python reference на одних и тех же тестовых данных; сравнивать до классификатора, а не только итоговый hit;
- НЕ открывать второй конкурирующий I2S driver, если существующий audio_service уже владеет им;
- пользоваться bounded fan-out/ring buffer или правильным provider callback. Не приводить к VAD task starvation, TTS crackle, display freeze или Wi-Fi проблемам.

Coexistence:
- в состоянии READY wake-движок активен локально, uplink=0, без provider sessions;
- touch работает независимо: вызывает уже имеющийся StartGoBotTurn("touch"); wake вызывает тот же метод с source="wake"; все ACL/consent/guard едины;
- в LISTENING активный wake отключён или защищён от повтора; в SPEAKING запрет самопробуждения от аудио GoBot; в IDLE после реального playback drain wake восстанавливается;
- на OFFLINE локальная модель продолжает распознавать слово, при trigger кратко показывать «нет связи» и вернуться к ожиданию; no endless connecting;
- MUTE останавливает и KWS, и capture/uplink (честный UI);
- после power-save screen dim wake не должен пропадать; deep sleep, отключающий микрофон/основные ядра, недопустим, пока не реализован иной доказанный wake путь;
- не открывать сессию при загрузке, при тихом idle или после disconnected reconnect без нового wake/touch.

## 4. Обучение именно «ГоБот» и проверка generalization

Подготовить отдельный воспроизводимый pipeline в проекте, например firmware/spotpear/kws/gobot/ (адаптируй пути к текущей структуре). Используй pinned open-source upstream из [R1] и [R4], не копируй чужой trainer вслепую. README, config, scripts, dependency versions, seeds, license/provenance каждой модели, hashes каждого dataset manifest и экспортированного .tflite обязательны.

### 4.1. Языковые формы

Цель — **одно пользовательское слово**, произносимое по-русски: «ГоБот». Разрешены разные естественные произношения/ударения **именно этого слова** («Го́бот», «Гобо́т», разная скорость/интонация), но не замены вроде «go bot» или «Привет ESP». Сверить фонетический состав, длину, реальную слышимость в русском. В рабочем UI отображать «ГоБот».

Положительные примеры: слово отдельно с паузой; «ГоБот, какая погода?» в одной фразе; быстрые/медленные; далеко/близко; взрослые голоса и различные акценты, если доступны с разрешением.

Жёсткие отрицательные: «робот», «бот», «готов», «говорит», «работа», «работает», «город», «компот», «колобок», «погода», «голос», «Гога», «гоп», «год», «го», «вот», похожие сочетания, обычные домашние разговоры, телевизор, музыка, TTS самой колонки, silence/noise. Добавить список по реальным ошибкам без записи семейной речи без согласия.

### 4.2. Источники и разделение

На PLAN уже ранее лежали локальные synthetic Piper corpora, но они были недостаточны для MultiNet/linear. Не объявлять их пригодными автоматически. Использовать несколько **разных** лицензированных русских TTS-моделей/голосов с разнообразием темпа, высоты, реверберации, громкости; при необходимости другие разрешённые генераторы.

Данные split train/validation/test **по исходным голосам/клипам и условиям, без утечки аугментаций**. Никаких одних и тех же TTS заготовок в train и тесте под разным шумом. Отдельный hard-negative continuous ambient набор. Модель, увидевшая одни и те же голоса только с изменённой скоростью, ещё не проверена на другом человеке.

Аугментации: разные микрофонные характеристики, gain/AGC, room impulse, шум улицы/кондиционера, телевидение, музыка, шум домашней комнаты, clips/codec, скорость/pitch; учитывать license noises. Не собирать личные записи без согласия. Не включать неизвестные коммерческие датасеты, NC лицензии или ElevenLabs API по умолчанию.

Не тратить деньги на GPU/RunPod, ElevenLabs или сторонний training-service без отдельного разрешения. Начать локально/на уже доступном build host и оценить длительность/CPU; избегать загрузки всех больших corpus на общий VPS без ограничений. Использовать ресурсные ограничения, не останавливать другие проекты.

### 4.3. Проверять именно streaming detection

Host evaluation:
- custom TFLite и Python reference на held-out positives/negatives;
- streaming windows и фактические frontend features, а не offline classification готового WAV;
- FNR/FRR по условиям, false accepts/hour на длинном negative audio, confusable phrases, ROC/threshold, latency;
- reproducible model manifest с probability_cutoff, sliding window, feature_step_size, tensor_arena_size и trained_languages=["ru"] — фактические значения модели, не выдуманные; валидировать по текущему schema ESPHome;
- train/validation/test не пересекаются;
- не тестировать собственную модель исключительно synthetic аудио своего же TTS.
- Если текущий эксперимент линейного классификатора даёт 2/9, 5/9 и false triggers, **не тюнинговать его бесконечно**; сравнить новый pipeline с ним и остановить старую гипотезу.

Embedded evaluation:
- точный TFLite buffer integrity и ops mapping на ESP32-S3;
- hash модели и правильная загрузка после reboot, actual KWS frames processed, no silently fake-ready;
- memory footprint/PSRAM, task watchdog, CPU per frame and p95/worst latency, competing LVGL/audio threads, audio packet counts while idle;
- реальное событие пробуждения связано с новым разговорным turn, а не просто напечатано в USB или показано лицо;
- при отсутствии модели/ошибке selftest wake disabled with honest status **но touch остаётся работающим**. Не возвращать устройство в полностью неработоспособное состояние.

## 5. Однословный вызов и «ГоБот, вопрос» без потери первого слова

Поддержать оба сценария:
1. «ГоБот» → звуковая/экранная обратная связь → пользователь задаёт вопрос.
2. «ГоБот, поставь таймер на две минуты» в одной фразе.

Вариант 2 требует post-wake pre-roll/transition buffering, потому что детектор часто подтверждает слово уже после нескольких аудиокадров. Продумать ограниченный в памяти ring (порядка 1–2 секунд по фактическим измерениям, выбрать размер после тестов) и handoff к 16/24 kHz voice pipeline, чтобы не потерять хвост wake и начало вопроса. Приоритет: не отправлять непрерывную речь до активации. Уточнить и документировать, какая часть буфера разрешена к отправке после wake, как удаляется само слово wake, когда pre-roll уничтожается. В idle эта память не сохраняется на диск.

Риск самопробуждения от произнесённого TTS («ГоБот») закрыть даже без гарантии хорошего AEC. Для первой приёмки можно выключать wake во время TTS и re-arm после фактического audio drain и cooldown. Не обещать full-duplex voice interruption, пока её не измерили. Касание Stop/mute должно сохраняться.

## 6. Сохранение текущего GoBot Home и разрешений

- Вся внешняя обработка остаётся в **едином существующем Brain**, без нового персонажа, нового Router и отдельной базы памяти.
- Не менять пользовательские скины, работающий экран, LVGL renderer, touch/BOOT, RTC/status, weather/timers, Opus, свой device gateway, C/A/B/phone режимы и their ACL.
- Не оживлять заводское XiaoZhi cloud enrollment/OTA. Секреты Brain/OpenAI на ESP не класть; сохранить собственный защищённый device enrollment.
- Любая сетевая сессия начинается **после подтверждённого wake или touch** и подчиняется hardware-scoped grant. Квоту телефона не присваивать колонке, новую платную API-квоту не выдумывать.
- Отдельно различать: wake recognized, channel opened, input ended, real Brain response, speaker playback drained, returned to wake ready. Не считать 200 по Wi-Fi или fixture media доказательством полноценного разговора.
- Пока новая модель не принята, пользователь может пользоваться устройством через касание — никогда не возвращай блокировку всей системы от неработающего KWS.

## 7. Аппаратная запись и восстановление

Плата: Spotpear EN-V5 With-B-1, ESP32-S3 rev 0.2, 16 MiB Flash, 8 MiB PSRAM, USB VID 303A/PID 1001; COM номер динамический. Original factory dump 16 777 216 bytes, две owner-private копии на PLAN с SHA-256:
    1fe1e310d86425dbe2432133c8712aecb64262bb3649647a5104989de671f4e6

Пути:
    C:\Users\PLAN\gobot\GoBotHome\data\hardware\factory\spotpear-factory-full-20261112.bin
    C:\Users\PLAN\AppData\Local\GoBotHome\FactoryBackups\spotpear-factory-full-20261112.bin

Проверить реальные bytes/hashes и текущий preflash, сохранить новый согласованный rollback set перед любой записью. Backup содержит Wi-Fi/NVS secrets, не отправлять в GitHub/PR, в облачный LLM или на публичные сайты. Preserve bootloader, partitions, otadata/NVS/PHY, не использовать erase-all или generic idf flash без разбора диапазонов. Никаких eFuse irreversible операций.

Сначала отдельная **compile/flash-модельная диагностическая сборка** только после проверки совместимости и механизма восстановления; затем stable bring-up с UI+touch+KWS. Временные экспериментальные образы должны иметь видимую версию/статус, не подменять активную рабочую прошивку без recovery. После flash — readback/verify, реальная загрузка, статусы и hardware smoke, сохранение исходного экрана и касания.

Если обнаружится, что одновременное размещение app/assets + TFLite model невозможно при текущей таблице, показать реальную карту памяти и варианты безопасной адаптации: встроить компактный ~десятки KB модельный файл в app/отдельный section, использовать текущие OTA bounds, не сносить общие assets и NVS ради экономии нескольких сотен KB. Не менять partition layout без plan/rollback.

## 8. Аппаратная приёмка, цифры и ложные пробуждения

Предлагаемые инженерные целевые показатели, НЕ заранее подтверждённые и НЕ официальные гарантии:

| Проверка | Минимальное доказательство |
|---|---|
| boot KWS | wake_running=1, model name/hash и frame processing; отсутствие panic |
| реальная фраза владельца | не менее 30 ручных произнесений «ГоБот», с исходом hit/miss и условиями |
| несколько голосов/условий | speaker-disjoint, разное расстояние, темп, помещение/шум |
| целевой ранний recall | >=90% на отдельной начальной серии, затем стремиться к >=95% на репрезентативной серии |
| confusables | отдельный тест «робот», «готов», «бот», «компот» и др., с реальными ошибками |
| FAR | несколько часов бытового шума/разговоров, события в час и длительность наблюдения; целевой продуктовый ориентир <=0.2/hour, не заявлять достигнутым раньше измерений |
| privacy standby | локальный mic processing, 0 uplink-audio/payload и 0 платных provider sessions до wake/touch при активном детекторе; измерение со сломанным KWS не засчитывается |
| wake→screen | видимая реакция без кнопки, measured latency и p95 |
| wake→real Brain | не mock/test beep, а реальный авторизованный разговор, в пределах действующей квоты |
| wake→answer→wake | завершение полного аудио и re-arm, несколько последовательных циклов |
| touch/UI regression | прежний рабочий touch, Stop/mute, лицо, погода и таймер не сломаны |
| reboot/network loss | после offline/reconnect wake доступен, нет автоматической платной сессии |
| self-trigger | собственный TTS/TV не запускают бесконечные вызовы |

Обязательные отдельные статусы: source_only / trained / compiled / flashed / boot_verified / synthetic_tested / human_acoustic_tested / real_brain_e2e / accepted. Одна команда git, один тон, 0/3 synthetic и отсутствие плавающего API трафика не означают accepted. Если человека для акустической приёмки рядом нет, отметь human_acoustic_tested=not_run, а не выдумывай человеческий тест.

После экспериментальной установки, если нужна помощь владельца, попросить **один короткий набор**: произнести «ГоБот» 10–30 раз в обычной обстановке, затем «ГоБот, сколько времени?» и «ГоБот, поставь таймер на две минуты», сообщить появление «Слушаю» и слышимый ответ. Нельзя просить сначала тестировать другое слово.

## 9. Порядок исполнения

1. Проверить и сохранить актуальный PLAN HEAD, dirty files, runtime и USB; существующий бинарник и status без предположений. Не конфликтовать с параллельным Codex.
2. Изучить и pin [R1], [R2], [R3], [R4]; за 1 страницу зафиксировать конкретный выбранный training baseline + TFLite-Micro/ESP-IDF integration map и что прямо переиспользовано, а не придумывается.
3. Создать воспроизводимый русскоязычный GoBot training config и dataset pipeline по [R4]; провести лицензионную/ресурсную проверку; train/held-out streaming evaluation; улучшать отрицательные примеры.
4. Одновременно реализовать/native compile microWakeWord inference pipeline на S3: audio fan-out/resample, exact frontend, TFLM op subset, ring, bounded RTOS tasks, model loading, VAD/smoothing, debug counters. Защитить существующий touch.
5. Встроить конкретную GoBot .tflite, запустить synthetic/device tests, измерить CPU/heap/latency/privacy и устранить ошибки. Не «поправлять» ассерт, искусственно показывая readiness.
6. Применить guarded flash/recovery в рамках ранее данного разрешения владельца. Проверить реально работающий UI и локальное событие «ГоБот» на устройстве.
7. Протестировать реальную акустику и сквозной Brain в пределах разрешений; без paid consent продолжить все бесплатные hardware проверки и обозначить один точный permission blocker.
8. Сохранить source/model provenance, build+flash+test manifests, обновить docs/CURRENT_STATUS.md и REQUIREMENTS_MATRIX.md, создать безопасную ветку/PR на актуальной базе после secret scan.

Не останавливаться на одной «исследовательской» заметке, не требовать новой платы, не переписывать весь продукт под ESPHome, не переключаться на ULP/Whistle вместо собственно KWS. При отсутствии одного инструмента/голоса/допуска продвигать независимые части и сохранять checkpoint. Платных GPU или модельных услуг без явного разрешения не запускать.

## 10. Итоговое сообщение владельцу

Первая строка должна ответить: **реагирует ли настоящий Spotpear на произнесённое «ГоБот» без касания прямо сейчас?**

Затем компактная таблица:
- что установлено на плате (actual version, hashes/readback/boot);
- готовность и качество детектора (engine/model/source, true acoustic n/N, false/hour, реальные условия);
- как устроено локальное ожидание и подтверждено ли отсутствие audio upload;
- работает ли касание/интерфейс/Stop/таймер после изменений;
- был ли настоящий диалог GoBot Brain с русским ответом и какой именно mode, без mock;
- не испорчены ли backup, NVS, телефонные квоты и окружение;
- какой остался блокер и следующий конкретный шаг (не предлагать «Привет ESP»).

Документы/логи/patch должны соответствовать реально действующему commit и runtime, а не друг другу на бумаге. **Готовность оценивается по голосовому событию «ГоБот» на настоящем микрофоне и сохранению работающего GoBot, а не по количеству синтетических тестов.**

Начинай работу по этой инструкции в текущей сессии Codex.