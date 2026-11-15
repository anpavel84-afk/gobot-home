# Локальное «ГоБот» на Spotpear

### Corrected r2 run and explicit Gabot —2026-11-15

First run failed before training on audible3160-sample negative «Гоу»; the new
negative-only normalization pads the missing40 samples without changing speech.
Positives/silence are still guarded. Existing60k plan is immutable/resumable.
`alias_corpus.py` extends a verified completed public corpus on a separate root:
1000 TRAIN clips for «Га́бот/Габо́т» and40 held-out alias clips; no private audio.
The r2 job trains on51k positive/10k negative source clips,102k feature windows,
10000 steps. `validate_reference.py --alias-validation PATH` is mandatory for an
alias-trained candidate. No qualified model, build or installation is claimed yet.
96 focused checks passed. The old unit failed; only the corrected r2 job runs.


### Full waveform reference run —2026-11-15 (RUNNING, not accepted)

`full_corpus.py` extends the existing offline corpus tools to50k positive and10k
negative *source waveforms*. It journals SHA-verified PCM, deterministic synthesis
plans and per-voice uniqueness; stochastic TTS regeneration after resume is not
claimed bitwise reproducible. Existing audio is never silently overwritten.
`full_reference_job.sh STAGE CODE full-reference-YYYYMMDD` composes generation,
held-out voice copy, full fresh MixedNet training and BUILTIN_REF evaluation.
Run only with the external resource/network caps documented in CURRENT_STATUS.
`train_reference.py --expanded --word-anchored --full-corpus --windows 100000
--steps 10000` uses lazy PCM loading and sees every positive source once during
feature generation. Source clips and augmented windows are separately counted.
No personal data, paid API, threshold sweep, retry, admission or flash occurs.

`mine_local_negatives.py` is PLAN-only private-teacher correction; its first
candidate FAILED held-out false-event checks. Selection and private weights
expire with their original sample, not with training completion.
`word_guard.py/.cc` are a REJECTED complete-word experiment, never a runtime
component. Do not add it to firmware or describe it as a working detector.
See `full-reference-run.json` for the observed job state and source hashes.
Earlier checkpoint prose below is historical.


### Current physical checkpoint:0.4.11 — NOT_ACCEPTED wake

`native-reference-build.json` identifies the installed/readback/boot-verified app.
The PUBLIC4ffc model and optimized kernels are unchanged.1625 public synthetic
INT8 outputs match host BUILTIN_REF EXACTLY (max_delta0).0.4.10's17-level mismatch
was also present between host optimized/reference backends; do not report an
ESP32 kernel defect. Original first fixture can be reproduced with explicit
`native_fixture.py --kernel desktop_optimized`; new goldens use native_reference.
`prepare_reference_fixture.py` preserves kernels and replaces only the golden
fixture/version. App-only guarded rollback chain is reference-fixture-rollback
->0.4.10, then native-parity-rollback ->0.4.9; prepared, not exercised.

Local scan runs; production and Owner wake admission remain OFF. Human no-touch
wake FAILED.94 free checks passed. Two public word-end-anchored CPU candidates
and their held-out failures are in `word-anchor-results.json`; neither was flashed.
All3 B starts are spent; no new paid call, raw recording or quota reset. One new
<=30s PLAN-only encrypted field sample has been requested, NOT approved/armed.
Existing deletion deadlines stand. These runtime proofs are not acoustic readiness.

Historical build, consent and installation checkpoints follow.


### Historical0.4.9 checkpoint, before Owner trial

`owner-wake-build.json` records the PUBLIC0.4.9 app actually USB-installed and
readback/boot verified. Full native INT8 model/front-end works (parity1987024791,
0 drop/error in the bounded snapshot); NVS/boot/inactive/assets retained.2s local
prefix and12s startup buffer preserve a question while the connection starts.
No personal model/audio was sent to the build host or put on the board.

Production qualification remains OFF. `GOBOT_WAKE_TEST_ARM` is an exact local USB
operator action: at most3 claims/600 seconds, initially unarmed. It is NOT a
financial permission; server device/profile/budget checks remain mandatory.
`GOBOT_WAKE_TEST_CANCEL` stops further test activations without pretending that
an active provider session was closed. Replaying arm cannot refill attempts.
The additional3x60s B grant is pending, policy DISABLED/unmounted; no paid call.
Do not arm automatically or substitute another engine. Same Brain/phones remain.

Candidate supports the3 whole-question episodes in the existing recording but
fails universal/name-only acoustic acceptance. Keep that limitation visible;
unit/build/native counters are not human voice acceptance. Models calibrated on
Owner audio are still private/temporary, not installed. Native trial-window test
and67 focused free Python checks pass. Rollback is guarded owner-wake-public-rollback
to0.4.8, then reference-local-rollback to0.4.6; not exercised after this install.

### Full reference / finite CPU correction — 2026-11-14

`train_reference.py` runs a public-synthetic-only64x4 MixedNet/204-frame profile.
50,000 means augmented feature windows from60 positive/792 negative seed clips,
not50,000 unique TTS utterances. Split2 trains Denis/Dmitri/espeak-ru/Anna;
Aleksandr validates, Elena tests. Do not call Dmitri held out for this profile.
The rejected pooled run exposed an initialization-selection bug. Export now
requires a trained finite checkpoint, preserves last weights and reports selection.
The upstream default temporal head is retained (pooled=false). The active bounded
run uses2CPU threads,4GiB memory and30min maximum, no paid/model service/network.
`validate_reference.py` checks fixed10-score/cutoff231/warmup68 streaming behavior,
manifest hashes and split isolation; ambient.py now honors the SAME smoothing and
warmup instead of silently reverting to legacy3-score inference.

`reference-template-build.json` identifies the successfully built PUBLIC0.4.8
placeholder template: ESP32-S3 image/checksum/hash checked,131072-byte model slot,
512KiB arena, SplitV, truthful local-scan/warmup status. NOT a qualified model,
NOT flashed. The existing physical board remains0.4.6, touch intact; USB port
currently enumerates but Windows returns device-not-functioning on open. Owner
was asked to reconnect. No recording is armed and no paid test was started.

### Corrective pipeline checkpoint — 2026-11-14

Fixed positive-word front cropping in `train.window`: oversized positive
augmentations are time-fitted rather than losing initial phonemes. Private audit
found428/512 affected examples under75 frames;120-frame context and40-call warmup
are supported. Complete original replay is60 positive/792 negative clips across
Denis/espeak-ru/Anna/Aleksandr, with manifest/SHA checks; Dmitri/Elena stay excluded.
`validate_local_candidate.py` performs fixed-cutoff250 streaming tests on both
reference speakers and the encrypted pre-AFE sample; no model/audio exported.
The versioned split can train the middle question prefix while retaining outer
questions and isolated4/9 as holdouts. Do not repeat the older all-questions-excluded
claim for split2. Human timings are provisional and repeatedly inspected.

All new profiles remain experimental/failed. No universal recall or accepted wake
is claimed. Immutable encrypted candidate copies are covered by the SAME expiry
task; candidate reports/IDs stay private. Public-only `prepare_private_template.py`
builds an unqualified0.4.7 template with64KiB slot and12s transition buffer.
`private_image.py` substitutes a model locally in RAM, verifies fixed segment
layout/checksum/SHA and rejects ambiguous slots. The real template patch passed
esptool image parsing, not hardware inference. No private weights on build host,
no new flash/paid call and no route enablement. Installed0.4.6 remains.

### Exact-input capture confirmed — 2026-11-14

Owner physically started and confirmed the FULL50s pre-AFE/Opus-free recording.
USB sequence/CRC/length passed, encrypted on PLAN, deletion task verified; no raw
audio/features/personal weights uploaded. Recorder closed, board idle/upload0.
New consent consumed; do not re-arm. Earlier expired-window statements below
are historical. Installed synthetic-only model emits0 events at cutoff250.

Calibration now requires explicit private, provisional timing intervals, fixed
two-utterance holdout and non-overlapping reviewed negatives. No loudest-peak
labelling. Optional continuous frontend replay retains real filter history in
training windows; offline/streaming and float/INT8 probes compare the same trained
weights. Personal model stays encrypted and shares raw sample deletion. Calibration
scores are NOT independent human acceptance; no learned model installed or wake
route enabled.31 focused free Python checks PASS, native C++ capture test retained.

Latest bounded calibration still FAILS. Two replay profiles plus complete-negative
interval correction (fixed12 epochs each) and diagnostic reproductions, no endless
search. Latest candidate:3 events on87 Dmitri synthetic negatives/189.93s (included
in training);15/15 positive clips but69 events on198 Elena negatives/616.89s.
These are synthetic regression metrics, NOT a human false-wake rate. The unknown
last utterance in the50s sample remains unlabelled/excluded, not counted positive.
No learned model installed; no training left running. Failed evidence retained.
Conversion audit compares nonstream/float-stream/INT8 peaks and tags artificial
zero padding explicitly; it does not establish full framewise equivalence.
Collector journals arm/start/completion/error classes privately without raw UART
logs, PCM or speech text. Original sample/model expiry is never extended.

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
