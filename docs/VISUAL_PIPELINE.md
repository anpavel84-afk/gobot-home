# Визуальные ответы GoBot

Продолжение существующего Brain/Bridge/SQLite/Browser, без смены стека. Основные
OpenAI STT/TTS, ручные Whisper/Denis, семейные профили, память и изоляция CLI сохранены.

## Реализованный путь

Запрос → deterministic PresentationDecision → Smart Router TOOL → VisualService →
источник/локальный ImageCache → типизированное visual_response SSE → Browser Renderer.
Для визуальных запросов не требуется запускать Codex/Antigravity или LLM-классификатор.
Файловые полномочия, personal memory и high-consequence проверки остаются перед этим путём.

Поддерживаются image_card, image_gallery, info_card, timer_widget, weather_card,
status_card, music_card и rich_answer. Weather/music сейчас честные unavailable
карточки: погодный источник/место и музыкальный сервер не подключены. Status читает
локальное состояние Brain. Timer использует реальный SQLite deadline, обратный отсчёт
в браузере и scoped cancel endpoint. Info умеет показывать безопасный расчёт.
Rich answer показывает настоящую локально нарисованную схему GoBot; личный план теплицы
без оригинала не придумывается.

## Контракт

Event.type = visual_response; data.presentation = gobot.ui **version 2**:

```json
{"namespace":"gobot.ui","version":2,"id":"unique-turn-card-id",
 "type":"image_gallery","title":"Томаты типа «Бычье сердце»",
 "subtitle":"","text":"Короткое пояснение",
 "images":[],"actions":[],"metadata":{"state":"loading"},
 "source":{"label":"Openverse"},"updated_at":0,"expires_at":null,"cache_key":null}
```

Ready image_card/image_gallery требует реальные images. У каждой картинки: asset_id,
url (browser_image_url), preview_variant, device_variant, MIME, размер, caption/alt,
source, attribution, license, license_url и описание изменений. Абсолютный
local_cache_path находится только во внутреннем media index, браузеру не передаётся.
Схема: gobot-ui-v2.schema.json. Исходные v1 UICommand и widget_command совместимы.
Неполный payload не прерывает текст/голос; дубли id не создают вторую карточку.

## Источники и качество соответствия

Основной источник — **анонимный Openverse API**, без ключа, аккаунта или платного API.
Поиск ограничен Flickr, разрешёнными лицензиями BY/BY-SA/CC0/public-domain и mature=false.
Скачивается только фиксированный Openverse thumbnail endpoint по UUID. Произвольный
url из метаданных никогда не загружается. Авторство и лицензия показываются со ссылкой
на оригинал. Openverse сообщает индексированную лицензию, не гарантирует её точность.

Для трёх демонстрационных объектов каталог visual-catalog.json содержит четыре
просмотренных фотографических референса, attribution и SHA-256 исходных миниатюр:
два Oxheart Tomato (Robert Sanzalone), лабрадор (jfch), плата Raspberry Pi
(blacklerphotos). Это реальные фотографии, не сгенерированные картинки. Томаты —
иллюстрация типа по подписи автора, без гарантии конкретного российского сорта.
Raspberry Pi — пример семейства, без утверждения о пятой ревизии. Изменившаяся
после проверки миниатюра отклоняется по hash.

При ручной проверке отклонены спорный Cuor di bue 3in1 из Commons и Flickr
«raspberry Pi-5», где был докладчик, а не плата. Название файла само по себе не доказывает
соответствие. Для общего поиска selection_basis=source_metadata_search_unverified:
это поисковые примеры, не результат визуального распознавания. Проверенная точность
общего русскоязычного image retrieval пока не измерена. Есть небольшой словарь
русских названий; это не универсальный переводчик.

Прямая Wikimedia сохранена как дополнительный адаптер. Её запросы с этого ПК
вернули 403 с требованием User-Agent/contact. По умолчанию она не используется.
Публичный контакт необязателен для Openverse; для Wikimedia вводится добровольно
в настройках и хранится только в run/visual-source.json. При выключении/повреждении
существующего конфига внешние источники закрываются. Создание ключей/аккаунтов не нужно.

## Кэш и безопасность

Media index — отдельный data/visual-cache/index.sqlite, исходный архив не мигрировался.
Файлы: browser JPEG ≤960 px без увеличения оригинала, preview ≤480 px, device
240×240 baseline JPEG ≤64 KiB. Устройство получает весь кадр с полями, без обрезки.
EXIF/ICC и исходная прозрачность удаляются/нормализуются. local_cache_path остаётся
внутренним. Исходные thumbnails не дублируются отдельными файлами в рабочем кэше.

TTL: media 7 суток, поисковый результат 1 сутки, ошибка 10 минут. Лимит 128 объектов
и 128 MiB, LRU/TTL cleanup; координация одинаковых запросов исключает повторные
загрузки, orphan-файлы удаляются только по собственным hash-именам внутри cache root.
Не более трёх кандидатов, 18 секунд поиска и двух параллельных image операций.
Локальный бюджет источника: 8 обращений/минуту, 80/24 часа, с учётом загрузок и ошибок;
429 учитывает Retry-After. Лимиты источника могут быть строже. Платного fallback нет.

HTTPS/TLS, фиксированный allowlist хостов/путей, проверка public DNS адресов, redirects
запрещены, trust_env=false, нет Authorization/cookies от пользователя. Download ≤8 MiB,
metadata ≤512 KiB, decode ≤16 MP, только JPEG/PNG/WebP без анимации; SVG/HTML запрещены.
Это не универсальный URL proxy. Полный GoBot context источнику не передаётся.
Явные запросы личных фото/планов не отправляются наружу. Приватные image uploads и
мультимодальный анализ пользовательских фотографий в этой фазе не реализованы.

В браузер — только same-origin /api/visual/assets/<hash>/{browser,preview,device}.jpg
через прежний private Tailscale gateway. Brain и Bridge остаются loopback, новые порты
не открывались. Полные приватные запросы не пишутся в image logs. В queries — hash;
remember=false не сохраняет презентацию в разговорном архиве. Публичный image cache
не является личной памятью и может использоваться повторно для одинакового объекта.

## Речь и отмена

display_text сохраняется исходным, presentation — отдельным trace-событием. Для
визуального ответа создаётся одна короткая speech_text реплика, затем тот же
Speech Formatter → OpenAI TTS → audio queue. Все подписи галереи голосом не читаются.
Browser скрывает повтор карточного пояснения, если оно уже показано в текстовом ответе.
Cancel прекращает ожидающий HTTP и воспроизведение. Уже запущенная ограниченная
локальная обработка Pillow в потоке может закончить public-cache запись после cancel.
Повтор delivery ID возвращает сохранённую карточку без нового скачивания и TTS.

## ESP32 readiness

ESP32VisualRenderer выдаёт compact custom gobot.ui v2 (≤8192 bytes), с credit,
asset ID и параметрами device variant; MockUIRenderer применяет её только на gui_tick.
Native LVGL обработчик этого контракта пока не реализован/не прошит.
HTTP device variant существует отдельно от browser variant. JPEG не отправляется в
XiaoZhi WS-аудиофреймах. MCP self.screen.preview_image готовится отдельно только при
подтверждённой capability и user-only permission; ImageStore URL живёт 30 секунд.
Текущий ImageStore loopback — fixture, не доступный реальной плате LAN origin.
Доставку на физическое ESP32 и firmware LVGL flags проверим после идентификации платы.
Tailscale HTTPS не объявляется автоматически доступным ESP32.

## Проверки и ограничения

pytest: фикстуры/MockTransport/синтетические JPEG в отдельном cache. Node DOM units:
восемь типов, gallery, неполный payload, URL allowlist, id dedupe, countdown/cancel.
Реальные image проверки отдельно: scripts/e2e_visual.py --network. Они используют
частный HTTPS, реальные публичные фотографии и HTTP варианты, без STT/TTS/CLI вызовов.
Результат: visual-e2e.json. Warm cache: visual-cache-benchmark.json.

Browser tools не предоставили ни одного браузера. Реальный Safari layout/playback
этим автоматическим прогоном не подтверждён. Общий поиск может честно вернуть ошибку:
в первоначальной пробе подсолнуха загрузка не прошла из-за Accept/HTTP 406;
после исправления ниже фотография реально загружена.
Три подготовленных photographic сценария работают; это не доказательство качества
произвольного image search. Платные OpenAI TTS пробы в этой фазе не выполнялись.

Официальные источники:
[Openverse API](https://api.openverse.org/v1/),
[About/licensing](https://openverse.org/about/),
[MediaWiki imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo),
[Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).

## Исправление HTTP 406 в общем поиске

Запрос владельца «Покажи как выглядит кратер» находил Flickr фотографии через
Openverse, но все три thumbnail URL вернули HTTP 406 с image-only Accept. Исправлен
заголовок thumbnail запросов на */*; metadata остаётся application/json. Ответ
по-прежнему обязан иметь JPEG/PNG/WebP MIME и пройти прежние size/decode/SSRF проверки.
Разрешения источников, redirects и список форматов не расширялись. Особенность
thumbnail action сверена с официальным исходником:
[Openverse ImageViewSet](https://github.com/WordPress/openverse/blob/main/api/api/views/image_views.py).

FETCH_POLICY_VERSION отделена от версии JPEG нормализации: новый fetch policy
меняет query cache key, поэтому прежний отрицательный результат не удерживает
ошибку после обновления. Существующие изображения и разговоры не удаляются.
Добавлены тесты content negotiation, отказа HTML/JSON/SVG и смены negative cache key.

Реальные general-search результаты (без нового curated entry): кратер вулкана,
Flickr 39824826@N08/7125541261; подсолнух, Flickr 15203873@N08/6101744035. Оба фото
загружены на cache miss и просмотрены локально; затем прошли browser/preview/device
GET через private HTTPS. Поиск остаётся metadata-based, не универсальной визуальной
верификацией и не гарантией доступности всех снимков. Точный вид кратера в ответе
задаётся подписью источника: вулканический, не утверждение об ударном происхождении.

Полный pytest: 431 passed. HTTPS image E2E расширен до 12 сценариев + повторный
cache hit. Платных API/CLI/STT/TTS вызовов: 0. Safari rendering по-прежнему не
подтверждён автоматикой; снимок владельца помог найти серверную ошибку.

## Visual-first и Device Mode

Каждый product ответ теперь получает сцену через VisualResponseComposer; отсутствие
фото осознанно оставляет avatar/icon/card, а не текстовый-only режим. Фото/схемы
выбираются существующим planner и actual answer/route. Optional visual task не
блокирует voice stream, speech_input_complete закрывает TTS отдельно. См.
[MULTIMODAL_RESPONSES.md](MULTIMODAL_RESPONSES.md) и [DEVICE_MODE.md](DEVICE_MODE.md).

Поиск дополнен опциональным FreeDict/WikDict lexicon, морфологией и ограниченным
однозначным переводом. 33717 headwords — помощник, не whitelist поддержки. Двусмысленные
запросы остаются русскими/требуют уточнения. Проверенный пример: пончик → doughnut,
реальная thumbnail загружена. Проверка telescope вернула спектральный график вместо
предметного фото: общая релевантность поиска не подтверждена, полноценного image
semantic verifier нет. Нельзя объявлять произвольный image query точным.

Позитивный cache сохраняется при изменении fetch policy; старые отрицательные
результаты не блокируют исправленный путь. Итоговый HTTPS прогон: 14 сценариев +
повторный hit; реальные источники и процедурные synthetic diagrams различены в отчёте.
Нейросетевая генерация не подключена, платных вызовов для визуалов нет.
