# GoBot UI v2: подготовка, без прошивки

Контракт, cache/device HTTP variant и тестовый GUI queue реализованы на сервере.
См. docs/VISUAL_PIPELINE.md и docs/gobot-ui-esp32-v2.schema.json.

Native consumer должен валидировать gobot.ui/version=2/command=presentation.show,
класть данные в ограниченную очередь и обновлять LVGL в GUI task. Не вызывать LVGL
непосредственно из WebSocket callback. Предварительный 240×240 baseline JPEG ≤64 KiB
получать HTTP-путём, не трактовать XiaoZhi Opus binary v1/v2/v3 как JPEG.

ESP32VisualRenderer.preview готовит существующий MCP self.screen.preview_image
только с user-only permission и подтверждённым tools capability. Нужны HAVE_LVGL,
CONFIG_LV_USE_SNAPSHOT и фактическая совместимость выбранной firmware. Это не
автоматическая доступность инструмента из обычного tools/list.

Сейчас MCP URL выдаёт loopback ImageStore для fixture. Реальная LAN доставка,
проверка ревизии/GC9A01/pin map/памяти/питания и firmware handler остаются до приезда
платы. Не прошивать, не стирать NVS/OTA. Перед первой прошивкой — полный factory
Flash dump и проверка размера по HARDWARE_CHECKLIST.
