# Display и речь

Исходный ответ отображается/сохраняется без изменения. SentenceBuffer удерживает
незакрытые скобки и fenced code; законченный фрагмент проходит SpeechFormatter v2,
затем серверный OpenAI TTS и bounded audio queue. Второй LLM не вызывается.

Formatter убирает Markdown и raw URL, сохраняет содержание значимых скобок,
исключает доказанные кириллица/латиница дубли имён. Иностранное имя без дубликата
сохраняется. Ограниченная транслитерация не гарантирует все варианты написания.
Нельзя удалять все скобки или склонять произвольную фамилию грубой заменой.

num2words + pymorphy3 переводят числа в русские слова: две минуты, до двух минут,
к двум часам, между двумя домами; валюты, единицы, десятичные дроби и даты.
Словарь services/brain/pronunciations.json задаёт GPT/ESP32/STT/TTS и допускает
точечные проверенные варианты произношения. Отрицания не удаляются. Текущие правила
консервативны и не решают весь синтаксис русского языка: неоднозначные падежи,
номера версий, сложные таблицы, интервалы дат и нестандартные сокращения требуют
дальнейших фикстур. Не заявляется универсальная проверка склонений всего ответа.

speech_segments хранит реально переданный в синтез speech_text, отдельный от
messages.content. status отличает submitted/generated/failed/interrupted и
client_playback_reported. audio_id + segment_id + seq обеспечивают порядок;
Web Audio отбрасывает дубликаты, останавливает очередь при cancel, не озвучивает
final заново. Повтор delivery replay не запускает TTS.

OpenAI TTS остаётся основным: gpt-realtime-2.1-mini, marin по умолчанию, Realtime
PCM 24k. Denis — только явный offline выбор. Browser speechSynthesis не подменяет
серверный голос. Текст и голос не переключаются молча на mocks при ошибке.

Ранее разрешённые три API-пробы выполнены по одному разу без retries. См.
openai-speech-probes.json: file STT 1417 мс; live первый partial 1920 мс,
после commit до final 783 мс; TTS первый PCM 1716 мс, 9 чанков, 3.35 с.
Имя «Гобот» распознано неверно обоими STT. Обязательного устойчивого качества
это не подтверждает. Проба не проверяла новые числительные на реальном TTS.
Оплаченный расход API не вернулся в этих транспортных данных; см. usage dashboard.

Готовый разрешённый образец доступен владельцу по приватному HTTPS
/audio/voice-check.wav. Программатическая проверка не доказывает слышимость на iPhone.

Официальные источники, проверены 10 ноября 2026:
[STT](https://developers.openai.com/api/docs/guides/transcription),
[Realtime transcription](https://developers.openai.com/api/docs/guides/realtime-transcription),
[TTS](https://developers.openai.com/api/docs/guides/text-to-speech).
