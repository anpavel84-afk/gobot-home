# Проверка устройства после доставки

## Запись и загрузка на PLAN — 12 ноября 2026

- Независимый полный readback до записи подтвердил SHA-256 заводских копий. Новый снимок сохранён отдельно в приватном каталоге операции.
- COM3, S3 rev 0.2, Flash 16 МиБ, PSRAM 8 МиБ. Проверены security state, OTA state и совпадение таблицы. Запись и verify для app по 0x20000 и assets по 0x800000 завершены.
- Загрузка `0.1.0-dev-gobot`, Wi-Fi и enrollment подтверждены по USB. Автоматическая проверка KWS на железе дала 0/3. Для реальной фразы, звука динамика, работы touch и отображения инструментов физическая приёмка ещё нужна.
- [Guarded recovery](../firmware/README.md) подготовлен для этой платы. Фактического возврата в заводской режим не выполняли.

Физическая совместимость не подтверждена. Source SHA a73e9a7e266e3196d1368ba46c30bee0d81f0a64; профиль
CONFIG_BOARD_TYPE_SPOTPEAR_ESP32_S3_1_28_BOX, main/boards/spotpear/sp-esp32-s3-1.28-box/ существует.
CMake project version 2.5.3, idf_component.yml требует ESP-IDF >=6.0.1. ESP-IDF/esptool здесь отсутствуют.

| Узел | Только source profile |
|---|---|
| LCD | GC9A01 240x240, 16-bit BGR, mirror X |
| SPI | SCLK4/MOSI2/CS5/DC47/RESET38, 40 MHz |
| Backlight | GPIO42 inverted |
| Codec | ES8311; SDA15/SCL14; PA46 |
| I2S | MCLK16/WS45/BCLK9/DIN10/DOUT8; in/out 24000 Hz |
| Touch | CST816D optional probe 0x15; SDA11/SCL7/RST6/INT12 |
| Other | LED48/Boot0/power-hold3/battery ADC1/charging41 |
| Flash/PSRAM | Фактические размер/тип неизвестны |

HAVE_LVGL — build define, не sdkconfig option. RECEIVE_CUSTOM_MESSAGE default n; LV_USE_SNAPSHOT
нужен для preview tool. sdkconfig.gobot.defaults — candidate, не проверенная сборка. Ревизия может отличаться.

## Строго следующие 3 действия при доставке

1. Сфотографировать корпус, маркировку PCB/наклейки; определить точную ревизию, USB VID/PID и COM,
   снять boot log без изменения flash; сравнить pin map/codec/touch/питание с таблицей.
2. Подготовить согласованную project-local версию esptool, проверить --help и read-only chip/flash/
   PSRAM identification. **До первой записи снять полный factory flash от 0 до обнаруженного размера**,
   проверить длину и SHA-256, сохранить вторую копию вне git.
3. После проверки backup/rollback и ревизии подготовить закреплённую ESP-IDF-сборку и hardware smoke:
   экран/цвета/ориентация, touch, mic/speaker, питание и PTT. Решение о первой прошивке — отдельный шаг
   владельца после этих проверок. Сейчас flash/erase/NVS/OTA не выполняются.

Дамп содержит NVS/Wi-Fi secrets: не печатать/не коммитить/не публиковать. Фото, boot log, dump и build
metadata хранить в игнорируемом data/hardware/. При необходимости снять второй dump и сравнить.
Проверить gain/PA/channels, BGR/inversion, touch presence и power GPIO. Rollback требует тот же
идентифицированный chip/размер/COM и проверенный full factory image; write/restore не автошаг скрипта.
