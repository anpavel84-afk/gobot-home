# Безопасность

Дополнение по просьбе владельца проверить GoBot с iPhone: отдельный временный gateway на конкретном
Wi-Fi IPv4:18785 допускает только несекретные health-статусы и три фиксированных mock-сценария.
Он доступен без логина другим клиентам разрешённого Wi-Fi subnet; ключи, история, терминал и CLI
не публикуются. Срок <=120 минут, Host/Origin/subnet/rate/concurrency ограничения. Brain/Bridge
по-прежнему loopback. Router/firewall не изменены. Это исключение из прежнего loopback-only режима;
подробности в PHONE.md.

Только новый GoBotHome и его git. Реальные модели/CLI tasks/LAN/прошивка/домашнее управление выключены.
Host listeners только 127.0.0.1. Health/ready минимальны, /api/v1/* требует новый локальный 384-bit Bearer.
CORS/Swagger не включены. Сервис однопользовательский; device_id — контекст владельца, не multi-tenant auth.

Bridge: HMAC-SHA256 над фиксированным методом/путём, timestamp, nonce и телом. Окно ±15 s,
одноразовые nonce и ограниченный replay cache. Ответы подписаны по nonce/seq/payload; Brain проверяет
порядок. Неверная подпись/replay/tampering протестированы. Это mutual authentication по loopback,
без шифрования памяти. Администратор и код той же Windows-учётной записи остаются доверенной границей.
HTTPX trust_env=False исключает случайный системный HTTP proxy для этих вызовов.

run/keys.json — только новые ключи GoBot, ACL run ограничен владельцем. .env*, SQLite, data/run/vendor
исключены из git. Auth homes CLI не копировались/не монтировались. Status CLI сохранён без аккаунтов и ключей.

Bridge допускает только mock/auto; запрос provider=codex/cursor/gemini получает 403.
Причина: OS containment, запрет shell/чужих файлов и настроенных MCP на этом Windows ещё не доказаны.
Cursor print сам допускает write/shell. Для live нужны проверенная изоляция, deny tools, ограниченный
workspace, Windows Job Object kill-on-close или эквивалент и разрешение владельца на расход лимитов.
ProcessRunner: create_subprocess_exec, argv, отдельный ограниченный/redacted stderr, timeout и cleanup.
Доступен только для fixtures; .cmd/.bat/.ps1 отклоняются. Tests проверяют потомка до первого stdout,
не универсальную изоляцию произвольного CLI. Codex approvals всегда decline, неизвестные tools отклоняются.

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
