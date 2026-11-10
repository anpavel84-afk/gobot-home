# Фактический статус — 10 ноября 2026

Основной продукт: https://plan.tailffc57c.ts.net:18786 . Включить Tailscale и открыть
в Safari; HTTP :18785 — отдельный старый mock-стенд. Доверенный TLS, точный allowlist
компьютера и iPhone. Brain/Bridge/fixture voice/images отвечают на healthcheck.
Docker отсутствует; процессы Windows native, без автоматического старта при входе.

AUTO/FAST выбирает Antigravity gemini-3.8-flash-low, REASONING — Flash Medium.
Ручной Antigravity — gemini-4-argon-medium, Codex — gpt-6.1-sol. Конкретная модель
видна под ответом. Нет тяжёлого/Mock fallback без разрешения. Gemini CLI и прямой
Gemini API не используются. Lite не доверена ни одна категория.

Реальный Codex E2E был успешен; Antigravity из браузера проверен владельцем.
Новые ContextPacket/usage изменения проверены фикстурами; нового платного CLI
запроса ради regression не было. Модели Flash объявлены официальным agy models,
но сравнительное качество Flash/Argon/Codex не измерялось.

OpenAI STT gpt-transcribe / gpt-live-transcribe и TTS gpt-realtime-2.1-mini / marin
основные. Разрешённые три пробы выполнены по одному разу без retries. STT ошибся в
имени «Гобот»; редактирование текста доступно. См. openai-speech-probes.json.
Whisper/Piper проверены как явно выбранный резерв, настройки по умолчанию не менялись.

Реализованы Quality-Aware Router, локальный калькулятор/таймер, source-gated
abstention, ContextPacket с cap, темы/эпизоды, scoped FTS5, идемпотентность,
диагностическое пространство mock, версионные выдержки, consent-факты,
удаление, временный режим, Speech Formatter и отменяемая аудиоочередь.

В интерфейсе: выбранная модель/исполнитель, тема и изменение названия, разрешённые
факты с исправлением/удалением, удаление разговора, режим «не запоминать», диагностика
packet/source IDs/provider usage. Это не отправляет ключи в браузер или CLI.

Бесплатные проверки: 426 pytest, Node harness, 240 уникальных synthetic router cases,
200-turn synthetic day. Поиск по синонимам не работает; semantic encoder не подключён.
Общего проверяющего web/home инструмента нет: требующие его ответы отклоняются.
Openverse — источник изображений, а не проверка фактических утверждений.
ECAPA embeddings реально вычисляются локально, семейной калибровки пока нет.
Нет подтверждения всего нового сценария физический iPhone → OpenAI STT → Flash →
OpenAI TTS после последнего обновления.

XiaoZhi v1/v2/v3 сейчас fixture. Upstream Python voice server имеет blocker
закреплённого Torch с Python 3.14. ESP32 ещё нет, прошивка не выполнялась.

Следующие три действия при доставке:

1. Фото/ревизия, USB, flash/PSRAM и boot log.
2. Полный factory Flash dump с проверкой размера и сохранением резервной копии.
3. Сверка pin map/audio/display с upstream board profile до согласованной прошивки.

Подробные политики и результаты: CONTEXT_POLICY.md, MEMORY_ARCHITECTURE.md,
CONTEXT_EVALUATION.md, SPEECH_FORMATTING.md. Нижеуказанные старые отчёты отражают
исторические этапы; этот файл описывает текущее состояние.

Визуальные ответы: gobot.ui v2, восемь типов, отдельный Browser Renderer и compact
ESP32 DTO. Реальные фото через Openverse/Flickr: два Oxheart references, лабрадор,
Raspberry Pi. Credits/лицензии видны; точный сорт/ревизия не утверждаются без основания.
TTL/LRU кэш 128 объектов/128 MiB; device JPEG 240×240 ≤64 KiB. Таймер использует
SQLite deadline и остаётся при следующем вопросе. Погода/музыка — unavailable cards.
Локальная схема и карточка результата работают без LLM. Новых портов нет.
Текущий private HTTPS image E2E: 10 сценариев + повторный cache hit, без постоянных
сообщений теста и без CLI/STT/TTS. 426 pytest и Node DOM regressions прошли.
Safari UI пока не осмотрен: инструменты не предоставили доступный браузер.
Общий image search best-effort, качество не измерено; в пробе подсолнуха — fallback.
Физического ESP32 renderer/LAN media delivery пока нет. См. VISUAL_PIPELINE.md.

Исправлен разбор длительности таймера: единый parser для команды и pending-уточнения
принимает мин/сек/ч с точкой и без, полные слова, составные интервалы. Неоднозначные
варианты не выполняются по последнему найденному числу; диапазон 1 секунда–сутки
сохранён. Исправлены окончания ответа: 1 минуту / 2 минуты / 5 минут.
Фраза владельца «Таймер на 5 мин» проверена через действующий private HTTPS:
локальный timer_widget на 300000 мс; тестовый таймер затем остановлен. Ни STT/TTS,
ни CLI не вызывались. Регрессия: 426 pytest. Отчёт timer-abbreviation-check.json.
