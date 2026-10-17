"""Declarative roadmap: a supported extension point is not an implemented integration."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    id: str
    name: str
    status: str
    description: str
    scopes: tuple[str, ...]
    adapters: tuple[str, ...] = ()


CAPABILITIES = [
    Capability("speech", "Распознавание и синтез речи", "available", "Whisper, Silero 5/5.6, Piper, системная озвучка и экспериментальный Qwen3-TTS в отдельном движке; выбор голоса и устройства, разговор по очереди, остановка кнопкой или Escape.", ("voice.input", "voice.output"), ("faster-whisper", "silero", "piper", "qwen3-tts", "windows-sapi")),
    Capability("language", "Понимание языка и контекста", "partial", "Потоковое общение, точные команды Windows и локальный разбор задач. Свободные команды открытия: модель предлагает ID из каталога, выбор подтверждается ответом «да» или номером. Произвольные действия из текста модели не исполняются.", ("model.chat",), ("ollama", "compatible-api", "local-intents", "catalog-intents")),
    Capability("tasks", "Задачи и напоминания", "available", "Локальные задачи, напоминания, таймеры и будильники; создание, перенос, отмена и завершение командами чата или через форму.", ("tasks.write",), ("local-scheduler",)),
    Capability("calendar", "Календарь и планирование", "partial", "Локальные события, расписание на неделю, пересечения, создание и перенос из чата; календарь каждого проекта независим. Напоминания привязаны к событиям и автоматически следуют за переносом; доступны в форме и командами чата. Синхронизация Google Calendar, Outlook и CalDAV ещё не подключена.", ("calendar.read", "calendar.write"), ("local-calendar",)),
    Capability("communications", "Сообщения, почта и контакты", "planned", "Будущие адаптеры почты, мессенджеров, звонков и контактов. Отправка потребует настроенного подключения.", ("messages.read", "messages.send", "contacts.read")),
    Capability("information", "Поиск, погода и информация", "partial", "Явный веб-поиск через SearXNG или Brave Search: выдержки, источники и время проверки. Погода, курсы и пробки как отдельные сервисы ещё не подключены.", ("web.search", "location.read"), ("searxng", "brave-search")),
    Capability("device", "Управление устройством", "partial", "Открытие приложений, сайтов, папок и файлов через общий реестр инструментов с настройкой доступа; сохранённые наборы запусков. Громкость, медиа, яркость и радиомодули ещё не подключены.", ("files.open", "apps.open", "web.open", "device.control"), ("windows-shell", "opening-tools")),
    Capability("notes", "Заметки и списки", "available", "Локальные заметки с редактированием и созданием командой чата; списки можно хранить в тексте или как задачи.", ("notes.write",), ("sqlite",)),
    Capability("personalization", "Персонализация и адаптация", "partial", "Личность, раздельные чаты и проекты со своей памятью, предложения с подтверждением, источники, редактирование, закрепление и поиск. Дообучения весов и извлечения любых привычек пока нет.", ("memory.write",)),
    Capability("integrations", "Внешние сервисы и умный дом", "partial", "Адаптеры SearXNG и Brave Search с отдельным доступом к поиску. Home Assistant, медиа и доски задач ещё не подключены.", ("integrations.connect",), ("searxng", "brave-search")),
    Capability("workflows", "Сценарии и уточнения", "partial", "Сохранённые сценарии до 12 открытий с проверкой, порядком шагов и остановкой; отдельные сценарии проектов. Уточнения и изменение недавней задачи с контекстом на 15 минут. Произвольный план действий LLM ещё не исполняется.", ("workflows.run",), ("local-dialogue", "local-routines")),
    Capability("privacy", "Безопасность и приватность", "partial", "Ключ локального сеанса, системное хранилище API-ключей, журнал, независимая память проектов, доступ к открытиям и поиску, резервные копии с защитой перед восстановлением. Пароль, шифрование и голосовая идентификация ещё не реализованы.", ("security.configure",)),
    Capability("proactivity", "Проактивность", "planned", "Будущие правила инициативы, тихие часы, предложения по контексту и явное отключение.", ("proactivity.suggest",)),
    Capability("multimodal", "Изображения, экран и камера", "partial", "Чат, голос, библиотека документов с поиском и явным выбором контекста, отдельные документы проектов и VRM работают; изображения, камера и чтение экрана требуют отдельных адаптеров.", ("images.read", "screen.read", "camera.read")),
]


def catalog():
    return [asdict(item) for item in CAPABILITIES]


class IntegrationAdapter:
    """Base contract. Concrete service adapters supply authentication and operations."""
    id: str
    required_scopes: tuple[str, ...] = ()

    async def check_connection(self) -> dict:
        raise NotImplementedError

    async def execute(self, operation: str, arguments: dict) -> dict:
        raise NotImplementedError
