# Безопасность

Обновление 10 ноября: private HTTPS Tailscale ограничен peer/Host/Origin, personal
scope — PIN; Bridge loopback/HMAC. AUTO Flash, без тяжёлого fallback. Gemini CLI/API
выключены. Архивный доступ фильтруется SQL по owner; память не даёт полномочий на
инструменты. См. CONTEXT_POLICY.md / MEMORY_ARCHITECTURE.md для удаления/backup.
Платные memory workers выключены. Биометрия и API-ключ — Windows DPAPI.

Дополнение по просьбе владельца проверить GoBot с iPhone: отдельный gateway на конкретном
Wi-Fi IPv4:18785 допускает только несекретные health-статусы и три фиксированных mock-сценария.
Он доступен без логина другим клиентам разрешённого Wi-Fi subnet; ключи, история, терминал и CLI
не публикуются. Срок теперь без TTL до остановки владельцем, Host/Origin/subnet/rate/concurrency ограничения. Brain/Bridge
по-прежнему loopback. Router/firewall не изменены. Это исключение из прежнего loopback-only режима;
подробности в PHONE.md.

Только GoBotHome и его git. Прошивка и домашнее управление выключены.
Основные services слушают 127.0.0.1. Health/ready минимальны, /api/v1/* требует локальный 384-bit Bearer.
CORS/Swagger не включены. Сервис однопользовательский; device_id — контекст владельца, не multi-tenant auth.

Bridge: HMAC-SHA256 над фиксированным методом/путём, timestamp, nonce и телом. Окно ±15 s,
одноразовые nonce и ограниченный replay cache. Ответы подписаны по nonce/seq/payload; Brain проверяет
порядок. Неверная подпись/replay/tampering протестированы. Это mutual authentication по loopback,
без шифрования памяти. Администратор и код той же Windows-учётной записи остаются доверенной границей.
HTTPX trust_env=False исключает случайный системный HTTP proxy для этих вызовов.

run/keys.json — только новые ключи GoBot, ACL run ограничен владельцем. .env*, SQLite, data/run/vendor
исключены из git. Auth homes CLI не копировались/не монтировались. Status CLI сохранён без аккаунтов и ключей.

Bridge допускает Codex/Gemini только с usage_consent и matching binary/policy evidence.
Codex offline compiled tool list пуст; shell/apply_patch/MCP/web/skills/hooks отключены,
approval requests всегда decline. Gemini core tools пуст, wildcard admin deny и MCP/extensions/hooks off;
@file preprocessing нейтрализовано в JSON context. Cursor live выключен.
Native subprocess argv, sanitized env и Windows Job Object kill-on-close завершают потомков при отмене.
Job Object отвечает за lifecycle, это не файловый sandbox. Ограничение ввода модели обеспечивается
отсутствием tools и deny policy; сам доверенный официальный CLI должен читать собственный OAuth cache.
Произвольные исполняемые файлы/CLI config из HTTP не принимаются; upstream CVE/компрометация trusted CLI
не изолируются отдельной Windows-учётной записью. Evidence инвалидируется при смене code/policy/binary.
ProcessRunner: create_subprocess_exec, argv, отдельный ограниченный/redacted stderr, timeout и cleanup.
Доступен только для fixtures; .cmd/.bat/.ps1 отклоняются. Tests проверяют потомка до первого stdout,
не универсальную изоляцию произвольного CLI. Codex approvals всегда decline, неизвестные tools отклоняются.

Приватный browser transport привязан к 100.90.228.125:18786, допускает только два конкретных tailnet peer IP,
точные Host/Origin и same-origin POST. proxy_headers=False, CORS нет, CSP same-origin, no-store.
Он передаёт только валидированные chat/audio/history операции в Brain, не в CLI и не в произвольный URL.
OpenAI key form bounded 4096 bytes, generic errors не отражают вход, Windows DPAPI current-user encrypt,
run/ под owner ACL и в gitignore. GET только bool. CLI env не получает этот ключ. TTS WS server-to-server;
ключ не передаётся браузеру. Платный синтез требует отдельного per-request consent, без fallback.
TLS не публикует приложение в интернет; Tailscale Serve/Funnel, ACL, firewall и router не менялись.

Upstream patch: строгий allowlist AND token(client_id,device_id,ts), пустой allowlist закрывает всё.
Whitelist token bypass и future timestamp исправлены, header dump удалён. Отдельный patch + regression tests.
Генерируемый base очищает demo providers/credentials/plugins/manager-api/MCP: одного plugins: {} в override
недостаточно из-за recursive merge. Production voice config fail-closed до ASR/TTS/device provisioning.

Images: minted local origin, baseline JPEG 240x240 <=64 KiB, image/jpeg, TTL 1..60 s, случайный 192-bit URL,
<=16 объектов. Произвольные URL не загружаются. MCP builder требует capability и user permission,
только minted URL; traversal/query/fragment/внешние адреса отклоняются. До LAN нужен firmware guard
MIME/Content-Length/origin/redirect: имеющийся preview tool сам этих гарантий не даёт.

HA/Music пока read-only interfaces/mocks. Замки, critical power, remote files и shell запрещены даже
при простом human_confirmation flag: полноценный permission layer ещё нужен. Memory purge удаляет
записи/WAL, не обещает физическое стирание блоков SSD/backup.
# Дополнение: публичные визуальные материалы

Visual Pipeline использует фиксированные Openverse/Wikimedia HTTPS endpoints;
нет произвольного URL proxy, redirects, cookie или ключей в image запросах.
Проверяются разрешённые хосты/пути, public DNS, MIME, размер загрузки и decoded pixels.
Browser media выдаётся через прежний защищённый Tailscale gateway; Brain/Bridge
остаются loopback. Внешний поиск получает только запрос изображения, не ContextPacket.
Явные личные фотографии/планы не ищутся наружу. Настройки позволяют выключить источник.
Нормализованные JPEG не содержат EXIF; TTL/LRU и лимиты media/source ограничены.
Подробности и оставшиеся ограничения: [VISUAL_PIPELINE.md](VISUAL_PIPELINE.md).
