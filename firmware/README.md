# Firmware readiness

2026-11-12: physical Spotpear arrived, ESP32-S3/16 MB Flash/8 MB PSRAM
identified through COM3; full factory image saved and SHA-256-checked twice
(see docs/HARDWARE_CHECKLIST.md). **No firmware flashed.**

Owner direction: autonomous hands-free local wake word REQUIRED; one-turn
wake → request → speech → idle rather than continuous listening.
See GOBOT_DEVICE_V1.md. New gobot-one-turn.patch is a candidate for the
pinned source: git apply --check only, NOT ESP-IDF-compiled or device-tested.
The current pinned upstream ESP-SR 2.4.7 needs compatibility validation
before using the newer Russian WakeNet10 model for «Привет ESP».

Upstream SHA a73e9a7e266e3196d1368ba46c30bee0d81f0a64; профиль/pins проверены по source, физическая ревизия неизвестна.
См. docs/HARDWARE_CHECKLIST.md и docs/PROTOCOL.md. Прошивка не выполнялась.
sdkconfig.gobot.defaults — candidate. HAVE_LVGL — build define.
custom-ui-card.patch использует существующий Application::Schedule/display API для простой карточки.
Патч проверен только git apply --check; ESP-IDF отсутствует, компиляция и native timer/weather widgets
ещё не проверены. Постоянные LVGL widgets/timer tick — дальнейшая работа. Этот patch не применялся к устройству.
preview_image уже есть условно, но нуждается в user permission и firmware URL/MIME/size/redirect guards.
До первой записи — полный factory dump и проверка размера. Flash scripts не создавались.
Hermes не установлен и не заменяет XiaoZhi; его Spotpear profile экспериментален.
