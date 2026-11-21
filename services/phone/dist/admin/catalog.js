/* Static capability descriptions. Availability and settings come from the owner API. */
window.SOPHIA_ADMIN = {
  "schemaVersion": 2,
  "navigation": [
    {
      "group": "СОФИЯ",
      "items": [
        [
          "overview",
          "Обзор",
          "grid"
        ],
        [
          "skills",
          "Умения",
          "spark"
        ],
        [
          "voice",
          "Разговор и голос",
          "wave"
        ]
      ]
    },
    {
      "group": "СИСТЕМА",
      "items": [
        [
          "home",
          "Дом и погода",
          "home"
        ],
        [
          "connections",
          "Серверы и сервисы",
          "server"
        ],
        [
          "devices",
          "Устройства",
          "speaker"
        ]
      ]
    },
    {
      "group": "УПРАВЛЕНИЕ",
      "items": [
        [
          "privacy",
          "Люди и память",
          "users"
        ],
        [
          "costs",
          "Расходы",
          "wallet"
        ],
        [
          "diagnostics",
          "Диагностика",
          "pulse"
        ],
        [
          "history",
          "Изменения",
          "history"
        ]
      ]
    }
  ],
  "statuses": {
    "configured": {
      "label": "Настроено",
      "className": "green",
      "help": "Параметры прочитаны с сервера. Само по себе это не подтверждает качество голосового ответа."
    },
    "check": {
      "label": "Нужна проверка",
      "className": "amber",
      "help": "Реализация есть. Нужна проверка источника, связи или голосового результата."
    },
    "available": {
      "label": "Есть в системе",
      "className": "blue",
      "help": "Обработчик существует в системе; индивидуальная проверка на колонке не выполнена."
    },
    "restricted": {
      "label": "Ограничено",
      "className": "violet",
      "help": "Возможность зависит от режима, устройства или подтверждения владельца."
    },
    "missing": {
      "label": "Не подключено",
      "className": "gray",
      "help": "Для этой возможности нет подключённого исполнителя. Настройки — проект будущей интеграции."
    },
    "unknown": {
      "label": "Не проверено",
      "className": "gray",
      "help": "Свежих данных о доступности этого умения нет."
    }
  },
  "categories": [
    "Все умения",
    "Разговор",
    "Дом и время",
    "Информация",
    "Медиа",
    "Личное"
  ],
  "skills": [
    {
      "id": "fast",
      "name": "Быстрый разговор",
      "description": "Повседневные вопросы и продолжение беседы",
      "icon": "wave",
      "category": "Разговор",
      "status": "unknown",
      "service": "OpenAI Realtime",
      "mode": "Быстрый",
      "settings": "Русский · marin",
      "page": "voice",
      "example": "«София, сколько будет два плюс три?»",
      "detail": "Прямой голосовой маршрут. Текущая готовность показана по ответу сервера; качество речи проверяется отдельно.",
      "fields": [
        "voice.language",
        "voice.responseLength"
      ],
      "evidence": "services/brain/gobot/realtime_ws.py"
    },
    {
      "id": "expert",
      "name": "Эксперт",
      "description": "Разбор сложного вопроса с озвучиванием",
      "icon": "spark",
      "category": "Разговор",
      "status": "unknown",
      "service": "Antigravity CLI",
      "mode": "Эксперт",
      "settings": "Выбранный профиль — из состояния сервера",
      "page": "voice",
      "example": "«София, спроси у эксперта…»",
      "detail": "Задача передаётся выбранному на сервере CLI-эксперту после явной просьбы. Готовность входа и внешний остаток квоты не определяются наличием профиля.",
      "fields": [
        "expert.confirm",
        "expert.fallback"
      ],
      "evidence": "services/brain/gobot/realtime_ws.py"
    },
    {
      "id": "interrupt",
      "name": "Пробуждение и прерывание",
      "description": "Имя «София», касание и остановка ответа",
      "icon": "hand",
      "category": "Разговор",
      "status": "check",
      "service": "Колонка Spotpear",
      "mode": "Оба режима",
      "settings": "Локальное имя «София» и касание",
      "page": "devices",
      "example": "Сказать «София» или коснуться во время ответа",
      "detail": "Слово «София» и касание должны останавливать ответ. Панель сохраняет действующую основу пробуждения. Акустическая проверка проводится на колонке.",
      "fields": [],
      "evidence": "firmware/spotpear; docs/CURRENT_STATUS.md"
    },
    {
      "id": "weather",
      "name": "Погода",
      "description": "Сейчас, прогноз и вопросы о том же месте",
      "icon": "weather",
      "category": "Дом и время",
      "status": "unknown",
      "service": "Open-Meteo",
      "mode": "Быстрый",
      "settings": "Домашний город и проверка источника",
      "page": "home",
      "example": "«София, какая погода завтра?»",
      "detail": "Погода использует подтверждённое домашнее место и Open-Meteo. Поиск города, проверка источника и сохранение доступны в этой панели.",
      "fields": [
        "weather.enabled",
        "home.city",
        "weather.provider",
        "weather.temperature",
        "weather.wind"
      ],
      "evidence": "services/brain/gobot/settings_tools.py; services/brain/gobot/quick_intents.py; services/brain/gobot/weather_queries.py"
    },
    {
      "id": "clock",
      "name": "Время и дата",
      "description": "Текущее время, дата и день недели",
      "icon": "clock",
      "category": "Дом и время",
      "status": "check",
      "service": "Локальный сервер",
      "mode": "Быстрый",
      "settings": "Проверить часовой пояс ответа",
      "page": "home",
      "example": "«София, сколько времени?»",
      "detail": "Локальный обработчик есть. Нужно проверить соответствие часов домашнему месту: отдельное постоянное поле IANA для часов пока не реализовано.",
      "fields": [
        "home.timezone",
        "home.clockFormat"
      ],
      "evidence": "services/brain/gobot/local_tools.py"
    },
    {
      "id": "timer",
      "name": "Таймеры",
      "description": "Запуск, оставшееся время и отмена",
      "icon": "timer",
      "category": "Дом и время",
      "status": "available",
      "service": "Локальный сервер",
      "mode": "Быстрый",
      "settings": "Базовые команды · доставка на проверке",
      "example": "«София, поставь таймер на пять минут»",
      "detail": "Базовый таймер реализован. Имена, пауза, продление и гарантированное уведомление на нынешней колонке не объявляются готовыми.",
      "fields": [
        "timer.display",
        "timer.signal"
      ],
      "evidence": "services/brain/gobot/local_tools.py"
    },
    {
      "id": "utility",
      "name": "Вычисления и единицы",
      "description": "Арифметика и простые преобразования",
      "icon": "calculator",
      "category": "Информация",
      "status": "available",
      "service": "Локальные инструменты",
      "mode": "Быстрый",
      "settings": "Без внешнего сервиса",
      "example": "«София, сколько сантиметров в двух метрах?»",
      "detail": "Есть детерминированные операции. Поддерживаемые величины нужно показывать по реальному реестру, без обещания любых вычислений.",
      "fields": [
        "utility.precision"
      ],
      "evidence": "services/brain/gobot/local_tools.py"
    },
    {
      "id": "web",
      "name": "Свежие сведения и поиск",
      "description": "Новости, последние фильмы и новые события",
      "icon": "globe",
      "category": "Информация",
      "status": "missing",
      "service": "Источник не подключён",
      "mode": "—",
      "settings": "Нужен проверенный веб-поиск",
      "example": "«Какой последний фильм с Леонардо Ди Каприо?»",
      "detail": "Нельзя подменять поиск ответом из знаний модели. У изолированного эксперта доступ к вебу запрещён; самостоятельного разрешённого поискового адаптера здесь нет.",
      "fields": [
        "web.source",
        "web.citations"
      ],
      "evidence": "services/agent-bridge/policies/antigravity-settings.json"
    },
    {
      "id": "visuals",
      "name": "Картинки к ответу",
      "description": "Изображения из разрешённых источников",
      "icon": "image",
      "category": "Медиа",
      "status": "restricted",
      "service": "VisualService",
      "mode": "По разрешению",
      "settings": "Проверить доставку на экран",
      "example": "«Покажи фотографию капибары»",
      "detail": "Есть существующий визуальный сервис и подтверждение декодирования. Доступность на текущем устройстве и разрешения проверяются отдельно.",
      "fields": [
        "visuals.accompaniment"
      ],
      "evidence": "services/brain/gobot/visual.py"
    },
    {
      "id": "imagegen",
      "name": "Создание изображений",
      "description": "Генерация новой картинки по просьбе",
      "icon": "palette",
      "category": "Медиа",
      "status": "restricted",
      "service": "OpenAI Image",
      "mode": "Выключено для колонки",
      "settings": "Отдельное разрешение",
      "example": "«Нарисуй дом у моря»",
      "detail": "Генерация изображений имеет отдельный допуск. Эта панель не меняет действующее разрешение на расходы.",
      "fields": [],
      "evidence": "services/brain/gobot/owner_terminal.py"
    },
    {
      "id": "music",
      "name": "Музыка и радио",
      "description": "Сервис, библиотека и устройство вывода",
      "icon": "music",
      "category": "Медиа",
      "status": "missing",
      "service": "Нет адаптера",
      "mode": "—",
      "settings": "Предусмотрено место для подключения",
      "example": "«Включи музыку»",
      "detail": "Музыкальный провайдер и исполнитель на устройстве пока не подключены. Поля ниже описывают будущую интеграцию.",
      "fields": [
        "music.service",
        "music.output"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "smartHome",
      "name": "Умный дом",
      "description": "Комнаты, устройства и разрешённые действия",
      "icon": "bulb",
      "category": "Дом и время",
      "status": "missing",
      "service": "Нет адаптера",
      "mode": "—",
      "settings": "Нужен контроллер и список устройств",
      "example": "«Выключи свет в гостиной»",
      "detail": "Сценарии в каталоге не являются подключением. Нужны контроллер, проверенные устройства и явные права на действия.",
      "fields": [
        "smarthome.controller",
        "smarthome.confirm"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "alarms",
      "name": "Будильники и напоминания",
      "description": "Расписание и надёжное оповещение",
      "icon": "bell",
      "category": "Дом и время",
      "status": "missing",
      "service": "Нет надёжного планировщика",
      "mode": "—",
      "settings": "Не путать с простым таймером",
      "example": "«Напомни завтра в девять»",
      "detail": "Нужны постоянное расписание, часовой пояс, доставка и восстановление после перезагрузки. Базовый таймер этого не заменяет.",
      "fields": [
        "reminders.channel",
        "reminders.quietHours"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "calendar",
      "name": "Календарь",
      "description": "События и выбранные календари",
      "icon": "calendar",
      "category": "Личное",
      "status": "missing",
      "service": "Аккаунт не подключён",
      "mode": "—",
      "settings": "Раздельные права чтения и записи",
      "example": "«Что у меня завтра в календаре?»",
      "detail": "Подключения календаря колонки пока нет. Доступ к личным событиям должен быть отдельным от обычного разговора.",
      "fields": [
        "calendar.service",
        "calendar.write"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "lists",
      "name": "Заметки и списки",
      "description": "Покупки, задачи и место хранения",
      "icon": "list",
      "category": "Личное",
      "status": "missing",
      "service": "Хранилище не подключено",
      "mode": "—",
      "settings": "Нужен владелец списка",
      "example": "«Добавь молоко в список покупок»",
      "detail": "Нет подтверждённого исполнительного адаптера для этого сценария. Нужны выбор хранилища, доступ и подтверждение записи.",
      "fields": [
        "lists.storage",
        "lists.scope"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "family",
      "name": "Люди и личные настройки",
      "description": "Кто говорит и к чему разрешён доступ",
      "icon": "users",
      "category": "Личное",
      "status": "restricted",
      "service": "Существующие профили GoBot",
      "mode": "Отдельное подтверждение",
      "settings": "Голос не подтверждает личность",
      "page": "privacy",
      "example": "Личные данные доступны после проверки прав",
      "detail": "Нельзя считать владельцем каждого, кто подошёл к колонке. Профиль браузера также не подтверждает личность говорящего.",
      "fields": [
        "privacy.guestName"
      ],
      "evidence": "services/brain/gobot/family.py"
    },
    {
      "id": "memory",
      "name": "Память разговора",
      "description": "Текущий контекст и отдельная личная память",
      "icon": "memory",
      "category": "Личное",
      "status": "restricted",
      "service": "GoBot Brain",
      "mode": "Текущий диалог",
      "settings": "Долговременная память не включена",
      "page": "privacy",
      "example": "Уточнение после прозвучавшего ответа",
      "detail": "Контекст ответа пополняется после playback_finished. Личная долговременная память требует отдельной идентификации и согласия.",
      "fields": [
        "privacy.memory"
      ],
      "evidence": "services/brain/gobot/realtime_ws.py"
    },
    {
      "id": "journal",
      "name": "Диагностика разговора",
      "description": "События, ошибки и подтверждение воспроизведения",
      "icon": "pulse",
      "category": "Разговор",
      "status": "available",
      "service": "Журнал на PLAN",
      "mode": "Оба режима",
      "settings": "Текстовый журнал — отдельный выбор",
      "page": "diagnostics",
      "example": "Посмотреть, где остановился ответ",
      "detail": "Технические события и текстовый журнал различаются. Панель показывает доступные безопасные сводки; личные реплики не загружает.",
      "fields": [
        "privacy.debug",
        "privacy.retention"
      ],
      "evidence": "services/brain/gobot/debug_journal.py"
    },
    {
      "id": "translation",
      "name": "Перевод и объяснения",
      "description": "Объяснить мысль или перевести фразу",
      "icon": "language",
      "category": "Информация",
      "status": "available",
      "service": "Разговорная модель",
      "mode": "Быстрый",
      "settings": "Русский язык по умолчанию",
      "example": "«Как сказать спасибо по-португальски?»",
      "detail": "Это ответ разговорной модели, без отдельной внешней интеграции. Точность не определяется индикатором подключения.",
      "fields": [
        "voice.language",
        "voice.responseLength"
      ],
      "evidence": "services/brain/gobot/realtime.py"
    },
    {
      "id": "messages",
      "name": "Сообщения и звонки",
      "description": "Кому и через какой сервис отправлять",
      "icon": "message",
      "category": "Личное",
      "status": "missing",
      "service": "Нет адаптера",
      "mode": "—",
      "settings": "Отправка только после подтверждения",
      "example": "«Отправь сообщение…»",
      "detail": "Пока нет подключённого сервиса и адресной книги. Каждая отправка требует выбранного получателя и подтверждения содержания.",
      "fields": [
        "messages.service",
        "messages.confirm"
      ],
      "evidence": "services/brain/gobot/skill_catalogue.py"
    },
    {
      "id": "narrator",
      "name": "Единый голос и диктор",
      "description": "Клип ожидания и чтение ответа эксперта",
      "icon": "volume",
      "category": "Разговор",
      "status": "available",
      "service": "marin · голосовой сервис",
      "mode": "Эксперт",
      "settings": "Один голос на всей цепочке",
      "page": "voice",
      "example": "Озвучивание готового экспертного ответа",
      "detail": "Клип ожидания и чтение ответа эксперта используют голос marin. Подтверждение подключения не заменяет проверку всей цепочки на колонке.",
      "fields": [
        "expert.speechLength"
      ],
      "evidence": "services/brain/gobot/realtime_ws.py"
    },
    {
      "id": "followup",
      "name": "Продолжение беседы",
      "description": "Уточняющий вопрос без повторного имени",
      "icon": "message",
      "category": "Разговор",
      "status": "available",
      "service": "GoBot Brain + Spotpear",
      "mode": "Оба режима",
      "settings": "После подтверждённого окончания ответа",
      "page": "voice",
      "example": "После ответа спросить: «А почему?»",
      "detail": "Продолжение привязано к реальному завершению воспроизведения. Настройки legacy-профиля не доказывают их применение в текущей прошивке.",
      "fields": [
        "conversation.followup",
        "conversation.followupSeconds"
      ],
      "evidence": "services/brain/gobot/realtime_ws.py"
    },
    {
      "id": "display",
      "name": "Экран и внешний вид",
      "description": "Лицо Софии, движение и экран ожидания",
      "icon": "monitor",
      "category": "Медиа",
      "status": "available",
      "service": "Экран Spotpear",
      "mode": "Оба режима",
      "settings": "Часть настроек ещё требует применения",
      "page": "devices",
      "example": "Уменьшить анимацию и настроить экран ожидания",
      "detail": "Экран получает состояние от голосового тракта. Настройки оформления и яркости появятся после подключения проверенного управления текущей прошивкой.",
      "fields": [
        "display.face",
        "display.reduceMotion"
      ],
      "evidence": "services/brain/gobot/device_contract.py"
    },
    {
      "id": "speakerIdentity",
      "name": "Узнавание говорящего",
      "description": "Локальное распознавание и его ограничения",
      "icon": "mic",
      "category": "Личное",
      "status": "restricted",
      "service": "Локальный SpeakerIdentity",
      "mode": "Экспериментально",
      "settings": "Не даёт доступ к личной памяти",
      "page": "privacy",
      "example": "Узнавание голоса после отдельной настройки",
      "detail": "Механизм требует отдельного включения, обучения и калибровки. Совпадение голоса не заменяет подтверждение прав. Панель не записывает голос.",
      "fields": [],
      "evidence": "services/brain/gobot/family.py"
    }
  ],
  "fields": {
    "home.city": {
      "label": "Домашний город",
      "type": "city",
      "scope": "Колонка Spotpear",
      "kind": "existing",
      "description": "Текущее место выбранной колонки хранится на PLAN. Новый город проверяется перед сохранением."
    },
    "home.timezone": {
      "label": "Часовой пояс часов",
      "type": "select",
      "options": [
        [
          "America/Sao_Paulo",
          "Бразилия · Сан-Паулу (UTC−3)"
        ],
        [
          "Europe/Moscow",
          "Москва (UTC+3)"
        ],
        [
          "Europe/Lisbon",
          "Лиссабон"
        ],
        [
          "UTC",
          "UTC"
        ]
      ],
      "kind": "proposal",
      "description": "Для погоды пояс приходит от источника. Постоянная настройка часов потребует расширения сервера. Редактирование пока не подключено."
    },
    "home.clockFormat": {
      "label": "Формат времени",
      "type": "select",
      "options": [
        [
          "24",
          "24 часа · 18:30"
        ],
        [
          "12",
          "12 часов · 6:30 PM"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "weather.enabled": {
      "label": "Погода для домашнего места",
      "type": "toggle",
      "kind": "existing",
      "description": "Использовать сохранённое место, когда в вопросе не назван другой город."
    },
    "weather.provider": {
      "label": "Погодный сервис",
      "type": "select",
      "options": [
        [
          "open_meteo",
          "Open-Meteo · адаптер есть"
        ],
        [
          "weather_com",
          "Weather.com · нужен адаптер и официальный доступ",
          true
        ],
        [
          "openweather",
          "OpenWeather · адаптер не реализован",
          true
        ]
      ],
      "kind": "existing",
      "description": "Наличие сервиса в списке не означает, что интеграция подключена."
    },
    "weather.temperature": {
      "label": "Температура",
      "type": "select",
      "options": [
        [
          "celsius",
          "Градусы Цельсия · °C"
        ],
        [
          "fahrenheit",
          "Градусы Фаренгейта · °F"
        ]
      ],
      "kind": "proposal",
      "description": "В отдельных вопросах обе единицы поддерживаются. Постоянное предпочтение пока проектируется. Редактирование пока не подключено."
    },
    "weather.wind": {
      "label": "Скорость ветра",
      "type": "select",
      "options": [
        [
          "kmh",
          "Километры в час · км/ч"
        ],
        [
          "ms",
          "Метры в секунду · м/с"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "voice.language": {
      "label": "Язык ответов",
      "type": "select",
      "options": [
        [
          "ru",
          "Русский"
        ],
        [
          "pt-BR",
          "Português · Brasil"
        ],
        [
          "en",
          "English"
        ]
      ],
      "kind": "proposal",
      "description": "Язык интерфейса и язык ответов — отдельные настройки. Редактирование пока не подключено."
    },
    "voice.responseLength": {
      "label": "Длина обычного ответа",
      "type": "select",
      "options": [
        [
          "short",
          "Кратко"
        ],
        [
          "normal",
          "По существу"
        ],
        [
          "detailed",
          "Подробно"
        ]
      ],
      "kind": "proposal",
      "description": "Предпочтение длины, без искусственного обрыва на середине слова. Редактирование пока не подключено."
    },
    "expert.confirm": {
      "label": "Подтверждение задачи эксперту",
      "type": "fixed",
      "value": "Для каждой задачи",
      "kind": "fixed",
      "description": "Явная просьба «спроси у эксперта» подтверждает задачу. Если переход предлагает София, она ждёт согласия. Фоновых запусков нет."
    },
    "expert.fallback": {
      "label": "Если выбранный эксперт недоступен",
      "type": "select",
      "options": [
        [
          "ask",
          "Предложить доступного и спросить"
        ],
        [
          "stop",
          "Объяснить причину и остановиться"
        ]
      ],
      "kind": "proposal",
      "description": "Не запускать другую модель и не повторять платный запрос без действия пользователя. Редактирование пока не подключено."
    },
    "timer.display": {
      "label": "Показывать обратный отсчёт",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "timer.signal": {
      "label": "Сигнал окончания",
      "type": "select",
      "options": [
        [
          "gentle",
          "Мягкий сигнал"
        ],
        [
          "voice",
          "Голосовое уведомление"
        ]
      ],
      "kind": "proposal",
      "description": "Доставка сигнала на колонку должна пройти отдельную проверку. Редактирование пока не подключено."
    },
    "utility.precision": {
      "label": "Точность результата",
      "type": "select",
      "options": [
        [
          "auto",
          "По смыслу вопроса"
        ],
        [
          "2",
          "До двух знаков после запятой"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "web.source": {
      "label": "Сервис поиска",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключён"
        ]
      ],
      "kind": "proposal",
      "description": "Выбор провайдера и проверка источников — следующий этап интеграции. Редактирование пока не подключено."
    },
    "web.citations": {
      "label": "Показывать источник и дату",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "visuals.accompaniment": {
      "label": "Иллюстрации к обычным ответам",
      "type": "toggle",
      "kind": "proposal",
      "description": "Не даёт разрешения на платную генерацию изображений. Редактирование пока не подключено."
    },
    "music.service": {
      "label": "Музыкальный сервис",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключён"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "music.output": {
      "label": "Устройство воспроизведения",
      "type": "select",
      "options": [
        [
          "spotpear",
          "Колонка Spotpear"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "smarthome.controller": {
      "label": "Контроллер умного дома",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключён"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "smarthome.confirm": {
      "label": "Подтверждать важные действия",
      "type": "toggle",
      "kind": "proposal",
      "description": "Замки, отопление и другие чувствительные действия должны иметь отдельные правила. Редактирование пока не подключено."
    },
    "reminders.channel": {
      "label": "Куда доставлять уведомление",
      "type": "select",
      "options": [
        [
          "spotpear",
          "Колонка Spotpear"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "reminders.quietHours": {
      "label": "Учитывать тихие часы",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "calendar.service": {
      "label": "Сервис календаря",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключён"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "calendar.write": {
      "label": "Разрешать создание событий",
      "type": "toggle",
      "kind": "proposal",
      "description": "Отдельно от чтения; каждое создание подтверждается пользователем. Редактирование пока не подключено."
    },
    "lists.storage": {
      "label": "Хранилище заметок и списков",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключено"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "lists.scope": {
      "label": "Кому виден список",
      "type": "select",
      "options": [
        [
          "household",
          "Семье"
        ],
        [
          "personal",
          "Только подтверждённому владельцу"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "privacy.guestName": {
      "label": "Обращение к неподтверждённому собеседнику",
      "type": "text",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "privacy.memory": {
      "label": "Предложение: личная долговременная память",
      "type": "toggle",
      "kind": "proposal",
      "description": "Личная память требует отдельной идентификации и согласия. Управление из этой панели пока не подключено."
    },
    "privacy.debug": {
      "label": "Предложение: текстовый журнал для отладки",
      "type": "toggle",
      "kind": "proposal",
      "description": "Настройка текстового журнала требует отдельного подтверждения владельца. Текущий opt-in в этой панели не редактируется."
    },
    "privacy.retention": {
      "label": "Срок хранения текстовой диагностики",
      "type": "select",
      "options": [
        [
          "1",
          "1 день"
        ],
        [
          "3",
          "3 дня"
        ],
        [
          "7",
          "7 дней"
        ]
      ],
      "kind": "proposal",
      "description": "Это срок хранения данных, не окно доступности разговора. Редактирование пока не подключено."
    },
    "messages.service": {
      "label": "Сервис сообщений",
      "type": "select",
      "options": [
        [
          "unconnected",
          "Не подключён"
        ]
      ],
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "messages.confirm": {
      "label": "Подтверждать получателя и текст",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "device.name": {
      "label": "Название в интерфейсе",
      "type": "text",
      "kind": "proposal",
      "description": "Переименование не меняет слово пробуждения. Редактирование пока не подключено."
    },
    "device.room": {
      "label": "Комната",
      "type": "text",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "device.brightness": {
      "label": "Яркость экрана",
      "type": "select",
      "options": [
        [
          "auto",
          "Автоматически"
        ],
        [
          "low",
          "Низкая"
        ],
        [
          "normal",
          "Обычная"
        ]
      ],
      "kind": "proposal",
      "description": "Управление на этой прошивке нужно подтвердить перед подключением настройки. Редактирование пока не подключено."
    },
    "device.nightDisplay": {
      "label": "Приглушать экран ночью",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    },
    "device.volume": {
      "label": "Предпочтительная громкость",
      "type": "range",
      "min": 0,
      "max": 100,
      "kind": "proposal",
      "description": "Фактическая громкость не загружена. Управление требует подтверждения устройства."
    },
    "costs.notify": {
      "label": "Показывать изменения расхода",
      "type": "toggle",
      "kind": "proposal",
      "description": "Информационное уведомление, без остановки терминала по бюджету или времени. Редактирование пока не подключено."
    },
    "expert.speechLength": {
      "label": "Как озвучивать длинный ответ",
      "type": "select",
      "options": [
        [
          "summary",
          "Сначала краткая суть"
        ],
        [
          "full",
          "Читать целиком"
        ]
      ],
      "kind": "proposal",
      "description": "Проект предпочтения, не изменение лимита модели и не обрыв ответа. Редактирование пока не подключено."
    },
    "conversation.followup": {
      "label": "Продолжать разговор без имени",
      "type": "toggle",
      "kind": "proposal",
      "description": "Изменение этой настройки на текущей колонке ещё требует серверного контракта. Редактирование пока не подключено."
    },
    "conversation.followupSeconds": {
      "label": "Ожидать уточняющий вопрос",
      "type": "select",
      "options": [
        [
          "5",
          "5 секунд"
        ],
        [
          "10",
          "10 секунд"
        ],
        [
          "20",
          "20 секунд"
        ],
        [
          "30",
          "30 секунд"
        ]
      ],
      "kind": "proposal",
      "description": "Управление ожиданием уточняющей реплики пока не подключено."
    },
    "display.face": {
      "label": "Стиль лица",
      "type": "select",
      "options": [
        [
          "classic",
          "Классическое"
        ],
        [
          "soft",
          "Мягкое"
        ],
        [
          "minimal",
          "Минималистичное"
        ]
      ],
      "kind": "proposal",
      "description": "Стили есть в визуальном языке GoBot; применение на установленной прошивке нужно проверить. Редактирование пока не подключено."
    },
    "display.reduceMotion": {
      "label": "Уменьшить движение",
      "type": "toggle",
      "kind": "proposal",
      "description": " Редактирование пока не подключено."
    }
  }
};
