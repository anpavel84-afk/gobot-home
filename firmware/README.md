# Firmware readiness

Upstream SHA a73e9a7e266e3196d1368ba46c30bee0d81f0a64; профиль/pins проверены по source, физическая ревизия неизвестна.
См. docs/HARDWARE_CHECKLIST.md и docs/PROTOCOL.md. Прошивка не выполнялась.
sdkconfig.gobot.defaults — candidate. HAVE_LVGL — build define.
custom-ui-card.patch использует существующий Application::Schedule/display API для простой карточки.
Патч проверен только git apply --check; ESP-IDF отсутствует, компиляция и native timer/weather widgets
ещё не проверены. Постоянные LVGL widgets/timer tick — дальнейшая работа. Этот patch не применялся к устройству.
preview_image уже есть условно, но нуждается в user permission и firmware URL/MIME/size/redirect guards.
До первой записи — полный factory dump и проверка размера. Flash scripts не создавались.
Hermes не установлен и не заменяет XiaoZhi; его Spotpear profile экспериментален.
