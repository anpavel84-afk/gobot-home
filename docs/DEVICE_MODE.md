# Режим устройства GoBot Home

Панель: https://plan.tailffc57c.ts.net:18786/ . Кнопка «Режим устройства» ведёт на
/device того же private Tailscale HTTPS сервера. Новый публичный listener не создан.
Это браузерный прототип поведения, не эмуляция ESP32/ESP-IDF/акустики.

## Один сервер и один голосовой клиент

Device page использует тот же browser.js GoBotClient, GoBotCapture, SSE, STT и TTS.
Не создан второй Brain или отдельная запись звука. Маленький hidden bindings adapter
передаёт настройки общему клиенту; длинная панель не рисуется внутри круга. Shared
client hooks доставляют события в отдельный canvas renderer/SceneManager.

Conversation ID сохраняется между панелью и /device. Memory device_id остаётся
авторизованным subject; отдельный client_id browser-device UUID и client_kind=device
назначаются шлюзом для профиля owner+peer. PIN/unknown speaker ограничения прежние.
Настройки устройства: data/browser-devices/profiles.sqlite, без миграции архива.
Каждый subject/peer имеет отдельные приватные assets, GET screensaver разрешён только
его текущему subject. Upload: static JPEG/PNG/WebP, ≤2 MB / 4 MP, без анимации,
EXIF удаляется, остаётся нормализованный JPEG 240×240. HTML/SVG/код скинов не принимаются.

## Вход и управление

1. В панели выбрать модели/голос, при необходимости отметить ранее разрешённые
   расходы OpenAI STT/TTS и CLI. Эти флаги не включаются автоматически.
2. Выбрать Classic/Soft/Minimal в «Устройство → Экран и внешний вид» и сохранить.
   Цвет, глаза, рот, интенсивность, reduced motion, часы/заставка хранятся сервером.
3. Перейти в /device, нажать «Включить GoBot». Жест запускает playback context,
   получает разрешение микрофона и отпускает проверочный track. В PTT ожидании
   микрофон не записывает. Для вопроса удерживать круг, затем отпустить.
4. File STT той же OpenAI конфигурации → автоматический send один раз по utterance ID.
   Пауза для ручного исправления остаётся в панели. Whisper только при явном выборе.
5. Нажатие во время ответа останавливает старый turn/аудио и начинает запись нового.
   Pointercancel/потеря видимости отменяют запись, не отправляют её как вопрос.
   Доступен альтернативный toggle mode; повтор pointerup/click не дублирует отправку.

Local activity/длительность фильтруют короткое/тихое касание до STT, но это не
откалиброванный VAD и не доказательство отсутствия ложных распознаваний в шуме.
Web Locks разрешает одну активную Device аудиосессию на browser origin; при отсутствии
API включение закрыто безопасно, а не разрешается несколько захватов.

## Экран

Отдельный canvas, фактические width/height 240×240, CSS масштабирует его целиком.
Три процедурных скина и 8 состояний: idle/listening/recognizing/thinking/speaking/
error/muted/offline. Speaking следует RMS фактического playback Web Audio, не text
delta и не приходу audio_start. Нет утверждения о синхронизации с фонемами или
распознавании эмоций человека. Поле reduced motion уменьшает движение.

SceneManager принимает turn-bound screen_scene/visual_response. Старые turn IDs и
опоздавший image onload игнорируются. Во время речи готовая картинка остаётся,
лицо её не перекрывает. Фото могут иметь осмысленное круглое кадрирование, а
известные схемы имеют отдельный компактный native-canvas renderer с короткими
подписями. Полный browser JPEG и compact device variant остаются доступны.
Таймер живой по серверному deadline, активный восстанавливается из SQLite;
авторизованный endpoint не читает чужие таймеры. Возврат к заставке после ответа
настраивается и начинается после фактического окончания playback. В диагностике
кнопка «Открыть растр» показывает настоящий PNG canvas в 240×240, без увеличения.
Реальная читаемость Safari ещё должна быть проверена владельцем на iPhone.

## Визуальное поведение по умолчанию

Каждый product reply проходит VisualResponseComposer. Avatar — полноценная
осознанная сцена для приветствий/неуместных иллюстраций. Иконки/карточки учитывают
actual answer, tool route и короткий план; например, калькулятор/память берут
действительный текст результата. Retrieve/процедурные схемы идут параллельно речи.
Служебный speech_input_complete закрывает TTS раньше optional visual completion;
тест проверяет audio_stop до позднего изображения. Для медленного явного visual
запроса доступна короткая нейтральная progress фраза без утверждения «показано».

Автоматические иллюстрации, minimal/balanced/rich, предпочтение фото, иконки,
время показа/возврат сохраняются в профиле. Explicit фото и системный widget не
выключаются с auto illustrations. Нейросетевой image provider не подключён;
checkbox виден как недоступный. Процедурный Pillow/canvas не выдаётся за AI imagegen.
Не каждый объект понимается идеально; нет универсальной семантической проверки
изображений. Проверенный источник актуальных праздников ещё не подключён; такой
запрос должен получить честную unavailable карточку, не выдуманный праздник.

## Wake word: конкретный оставшийся blocker

В текущей среде sherpa_onnx есть, vosk/openwakeword нет. В data/models нет модели,
проверенной на русском «ГоБот». Официальный dscripka/openWakeWord README описывает
English pretrained models; добавлять «ГоБот» в конфиг и объявлять готовность нельзя.
Большое обучение/новый cloud/STT standby не запускались. В UI wake disabled/not
configured, PTT рабочий программный путь. Локальный WakeWordActivationService —
адаптер/guard: bounded 2-second PCM ring, TTS suppression/cooldown, prefix stripping;
fixture tests не доказывают распознавание речи. Реальный detector не подключён.

В ожидании Device нет внешнего STT/TTS/LLM/CLI и нет фоновой записи. Это проверено
для текущего PTT/disabled-wake режима; активный wake не тестировался. Его FRR/FAR,
activation latency и реальная CPU нагрузка: не измерены. Оба wake сценария с паузой
и в одной фразе остаются незавершёнными до совместимой модели и реальных проб.

## Mobile lifecycle

visibilitychange/pagehide/offline и прерывание track/audio context останавливают
запись/ответ, отпускают mic, ownership lock и screen wake lock. Возобновление
требует понятной кнопки/жеста. Screen Wake Lock только при поддержке/разрешении,
без скрытого видео. Manifest и локальные иконки помогают добавить страницу на
домашний экран; это не гарантия фонового микрофона, особенно после блокировки/звонка.

## Проверки и пределы

Pytest сохраняет все предыдущие regression. Node fixtures проверяют hold → shared
capture → STT fixture → авто-send, conversation/utterance, dedupe, pointer lifecycle,
состояния/скины, stale images, размер canvas, quiet gate, track release. Это не
настоящий Safari и не новый платный real speech E2E. Платные пробы этой фазы: 0.
32 синтетических content-aware запроса: composer-evaluation.json; source correctness
LLM/фото не доказана метками. Физической ESP32 по-прежнему нет, не прошивалась.

Portable contracts: device-profile.schema.json, device-scene.schema.json,
gobot-ui-esp32-v2.schema.json. Будущий LVGL требует собственной реализации
примитивов/GUI queue/доставки media; CSS/canvas не объявляются автоматически переносимыми.

Источники: https://github.com/dscripka/openWakeWord/blob/main/README.md,
https://alphacephei.com/vosk/adaptation,
https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API,
https://webkit.org/blog/12445/new-webkit-features-in-safari-15-4/ .
