# Локальное «ГоБот» на Spotpear

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
