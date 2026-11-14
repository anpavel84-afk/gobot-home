# Локальное «ГоБот» на Spotpear

### Input-domain correction — 2026-11-14

The two consented samples (49.92s and35.0s) are POST-AFE/Opus conversation audio.
The second ends with FOUR wake controls per Owner correction. Idle KWS gets
pre-AFE PCM, so prior pilot counts/adaptation below are NOT device acceptance.
Training stopped. Both consents consumed, original DPAPI/deletion deadlines kept.
`fine_tune_local.py` and product admission now require pre-AFE provenance.

`prepare_raw_capture.py` patches a COPY of installed0.4.5, never flashes. It adds
one explicit USB-arm/physical-tap capture at the existing16k mono pre-AFE tap.
Fixed PSRAM bound, zero-on-stop/expiry, no provider/network stream, no second I2S.
Full microphone/Opus path remains unchanged outside this diagnostic. Export is
lossless PCM with session nonce, chunk sequence and CRC32,20s timeout; host rejects
incomplete/corrupt/oversized recordings. `record_raw_usb.py` registers deletion
before arm and encrypts only the complete WAV on PLAN. Installation and a NEW
recording require scoped authorization. Owner approved installation and ONE NEW
<=50s sample; installed app/boot verified and the one-use USB collector prepared.
Its first armed window expired with physical touch counter0, no STARTED and no
audio file. Collector cancelled, idle/upload0 verified; NEW consent is unused,
wait for Owner presence before re-arm. USB arm/cancel console control passed;
lossless physical PCM transfer remains unverified.
Candidate0.4.6-dev-raw-wake-1 built offline,2722208 bytes; exact app/model hashes
and separate physical-acceptance flags are in raw-capture-build.json. Installed,
NVS/boot/OTA/inactive/assets verified unchanged. Human wake acceptance NOT_DONE.

Free checks PASS: C++ capture state/bounds/expiry/zeroization/input-gap test;
21 Python framing/retention/admission tests including corruption/replay/overflow.
These are not physical USB/microphone or human wake acceptance.

### 2026-11-14: real sample / local-only adaptation checkpoint

Owner initiated49.92s recording and confirmed the requested pronunciation sequence.
It is DPAPI-encrypted on PLAN only; exact-file deletion at23h was registered before
recording. Raw sound/features and personal weights were not sent to the build host
or published. Normal B restored; installed0.4.5 unchanged, wake route still OFF.

Existing local Whisper was used for approximate timing only, with no external STT
or published speech. The three prior models emitted9/5/4 events respectively;
event counts are not verified recall. `fine_tune_local.py` runs a fixed12-epoch,
2-CPU-thread existing microWakeWord adaptation from verified synthetic-only weights.
8 isolated examples participate in gradients;2 isolated examples and question
phrases do not. Timing is energy-inferred and repeatedly evaluated: this pilot is
not independent human acceptance. Optional balanced replay uses18 existing licensed
Denis/Dmitri positives and174 negative clips. Personal TFLite is DPAPI-protected
and deleted by the SAME sample expiry task; temporary exports are removed.

The local model retains extra detections:2 events on87 synthetic Dmitri negatives
over189.93s (training regression, NOT held-out), including "погода" / "какой бот".
Cutoff255 still leaves a false event. No product admission, new flash or paid call.
Further recording requires separate consent: the first ONE-sample permission is
now consumed. No second sample is armed. No speaker identification or private
memory permission is inferred from the recording or personalized keyword model.

Диагностическая установка сохраняет экран, касание и аппаратный gateway версии 0.2.3. Никаких моделей или ключей облака для поиска слова не требуется. Во время диагностики модель считает совпадения, показывает «Слышу ГоБот» и оставляет сетевую сессию закрытой. Рабочий путь для прошедшей приёмку модели вызывает `StartGoBotTurn("wake")`. При открытии канала ограниченный буфер в PSRAM вмещает первые 1,5 секунды после детекции. До детекции обрабатывается один поток штатного ES8311. PCM ожидания в буфер передачи не попадает.

## Сборка и происхождение

- [Русский тренер «Джарвис»](https://github.com/interkelstar/microwakeword-trainer/tree/8fdbadc3b969a8c1993108c0d655910440dfb762) использован как пример разметки, генерации и испытаний. Веса обучены заново. Классификатор, слои со стриминговым состоянием и конвертация взяты из [OHF microWakeWord](https://github.com/OHF-Voice/micro-wake-word/tree/4665173cd35f1cff9a61e06fc427f124766c488e), Apache-2.0.
- Параметры фронтенда и контракт тензоров сверены с [ESPHome 2026.10.2](https://github.com/esphome/esphome/tree/9a78022ded2285861f10de50168a0aa71e2a4322/esphome/components/micro_wake_word). ESP-IDF 6.0.1 подключает espressif/esp-tflite-micro 1.3.3~1, esphome/esp-micro-speech-features 1.2.3 и транзитивный esp-nn 1.5.0. Зависимости сохраняют свои лицензии. Микрофронтенд использует Apache-2.0, шаблон опирается на реализацию TensorFlow и изменения Kevin Ahrendt.
- Русские Piper Denis и Dmitri из [piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/2f358b6a560e3a913ebf509b2f3344f20b367f94/ru/ru_RU). В карточках обеих моделей исходный корпус обозначен CC0. Точные SHA модели и конфига проверяются в corpus.py. Использованы русский голос eSpeak NG 1.51 и голоса Anna, Aleksandr и Elena из дистрибутива RHVoice 1.8.0+dfsg-3build3. Источник лицензий голосов — файл copyright пакета Ubuntu и [документация RHVoice](https://github.com/RHVoice/RHVoice/blob/master/doc/en/License.md). В репозитории нет голосовых синтезаторов и звуковых записей. Платные TTS, Irina и Ruslan не использовались.
- Разделение v3 по исходному голосу: обучение Denis, Anna, Aleksandr и eSpeak ru, валидация Dmitri, отдельная проверка Elena. На каждый голос 15 положительных и 198 отрицательных синтетических записей. В seed-фиксированных аугментациях меняются скорость, усиление, шум, фильтрация и задержанное отражение. Набор не включает бытовые записи владельца. Повторные обращения к проверочному набору при разработке ограничивают независимость общей оценки.
- 16 кГц, mono PCM16, окно 30 мс, шаг 10 мс, 40 полос, вызов модели каждые 30 мс. Вход INT8 [1,3,40], выход UINT8 [1,1]. Проверочный зонд из parity.py и тот же зонд на S3 обязаны дать 98 строк и контрольное значение 1987024791. Несовпадение выключает детектор. Порог и гистерезис указаны в gobot.json и stream-report.json. Полное выделение арены — 131072 байта PSRAM.

На изолированном Linux CPU с Python 3.12 установить requirements-cpu.txt. Поместить файлы голосов Piper в voices/. Для eSpeak NG и RHVoice требуются их CLI, русские данные и голосовые пакеты. После получения зависимостей все шаги выполняются локально.

```sh
git clone https://github.com/OHF-Voice/micro-wake-word mww
git -C mww checkout 4665173cd35f1cff9a61e06fc427f124766c488e
export PYTHONPATH="$PWD/mww" TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1 OPENBLAS_NUM_THREADS=1
python corpus.py voices corpus denis dmitri espeak-ru anna aleksandr elena
python train.py corpus model3
python evaluate.py corpus model3
python ambient.py model3 corpus/elena
python mine.py corpus model3 mined.npy
python train.py corpus model4 --mined mined.npy
python evaluate.py corpus model4
python ambient.py model4 corpus/elena
```

Результаты тестирования относятся к хешу модели, приведённому в отчёте. При повторной генерации проверить хеши манифестов. Использованные пакеты и seed задают воспроизводимый процесс. Побитовое совпадение ONNX-синтеза и TF не проверено на других процессорах.

Для сборки предоставить отдельную копию проверенного дерева XiaoZhi, подготовленного по ../prepare_touch.py для 0.2.3. Выполнить `python prepare.py <копия> <папка модели>`. Затем собрать из корня копии `idf.py reconfigure` и `cmake --build build -j3` в закреплённом образе из ../touch_release.json. Проверить app, модель, таблицу разделов и assets независимо. Имя выходного bin само по себе не разрешает запись. На PLAN утилита firmware/spotpear_bringup.py проверяет физическое устройство, две заводские копии, текущий полный snapshot и ожидаемый ota_0. Операция wake-rollback возвращает ota_0 к 0.2.3. NVS и assets остаются на плате. Физическое восстановление заводского дампа не упражнялось.

## One-phrase candidate (2026-11-13)

Use prepare_one_phrase.py only on a copy of installed media-ready0.4.3.
The candidate keeps diagnostic wake_route=0; touch and installed firmware remain.
WakeQuestionBuffer retains1s local rolling prefix and12s total bounded PCM in
PSRAM, drains once into existing audio engine, zeroizes consumed/reset memory,
and cancels on overflow. This is connection prebuffering, not a second STT.

corpus.py --wake-variants requires a NEW output directory. wake_variants.py
defines first/second stress and separated/diphthong variants; five forms do not
prove human acoustic coverage. Preserve old corpora/model reports. Train/evaluate
with existing pinned CPU environment, held-out voice and continuous negatives.
Host test: g++ -std=c++17 -Wall -Wextra -Werror test_wake_question_buffer.cc -o test-buffer && ./test-buffer.
No cloud wake until acoustic qualification; no unattended paid session.

## Resumed voice-first product checkpoint (2026-11-13)

Installed0.4.5 touch-first remains the rollback; no failed model was installed.
`prepare_product.py` targets a COPY of that current source, preserving fast-start
capture/UI and existing native KWS/audio ownership. The existing1s rolling prefix
and12s bounded question buffer feed the SAME audio engine once. Product routing
requires matching model hashes, held-out and30min synthetic-negative success,
labelled30-call human recall>=90% and background observation. The11 free tests
cover gates/expiry/path safety, not acoustic readiness.

Two bounded CPU experiments completed with no paid service or household speech:

```sh
python train.py one-phrase-v1/corpus-variants model6 --frames 120 --positive-fraction .25 --negative-weight 4 --mined mined.npy
python evaluate.py one-phrase-v1/corpus-variants model6
python train.py one-phrase-v1/corpus-variants model7 --frames 120 --robust --mined mined.npy
python evaluate.py one-phrase-v1/corpus-variants model7
```

Both FAILED streaming acceptance; see model6-result.json/model7-result.json.
No further unattended model search. More same-TTS tests do not establish human
recognition. Owner allowed ONE <=60s PLAN-only microphone sample. The prepared
recorder uses existing authenticated TLS, rejects backend HTTP, waits for touch,
captures at most50s, encrypts with Windows DPAPI and registers exact-file deletion
at23h via Windows Task Scheduler. No raw sound/features to Git, remote build host,
external STT or semantic memory. First armed10min window timed out without touch;
no sample exists, real gateway restored. Re-arm only when Owner is present, under
the same unconsumed sample consent; this is calibration, not the product's wake UX.

PLAN-only feature/inference dependencies are in private local-wake-runtime,
ai-edge-litert2.3.0 and pymicro-features2.0.2; parity98/1987024791 matches ESP32.
`evaluate_local_sample.py` reads only DPAPI samples before their expiry and reports
numeric scores/segments. These are unlabelled until verified against real trials.
The voice-first product remains NOT_ACCEPTED; do not replace this status with
source/build/unit-test counts. C/B ledgers and finite admissions stay unchanged.
