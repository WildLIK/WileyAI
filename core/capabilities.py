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
    Capability("speech", "Распознавание и синтез речи", "available", "Whisper, Silero и системная озвучка; отдельный выбор компонентов, разговор по очереди и прерывание кнопкой.", ("voice.input", "voice.output"), ("faster-whisper", "silero", "windows-sapi")),
    Capability("language", "Понимание языка и контекста", "partial", "Потоковое общение, контекст, команды Windows и локальный разбор русских команд для задач. Произвольные намерения LLM ещё не исполняются.", ("model.chat",), ("ollama", "compatible-api", "local-intents")),
    Capability("tasks", "Задачи и напоминания", "available", "Локальные задачи, напоминания, таймеры и будильники; создание, перенос, отмена и завершение командами чата или через форму.", ("tasks.write",), ("local-scheduler",)),
    Capability("calendar", "Календарь и планирование", "planned", "Контракт для событий и адаптеров Google Calendar, Outlook и CalDAV. Синхронизация ещё не реализована.", ("calendar.read", "calendar.write"), ("google-calendar", "outlook", "caldav")),
    Capability("communications", "Сообщения, почта и контакты", "planned", "Будущие адаптеры почты, мессенджеров, звонков и контактов. Отправка потребует настроенного подключения.", ("messages.read", "messages.send", "contacts.read")),
    Capability("information", "Поиск, погода и информация", "partial", "Явный веб-поиск через SearXNG или Brave Search: выдержки, источники и время проверки. Погода, курсы и пробки как отдельные сервисы ещё не подключены.", ("web.search", "location.read"), ("searxng", "brave-search")),
    Capability("device", "Управление устройством", "partial", "Открытие приложений, сайтов, папок и файлов. Громкость, медиа, яркость и радиомодули ещё не подключены.", ("files.open", "apps.open", "web.open", "device.control"), ("windows-shell",)),
    Capability("notes", "Заметки и списки", "available", "Локальные заметки с редактированием и созданием командой чата; списки можно хранить в тексте или как задачи.", ("notes.write",), ("sqlite",)),
    Capability("personalization", "Персонализация и адаптация", "partial", "Личность, история, предложения памяти с подтверждением, источники, редактирование, закрепление и поиск. Дообучения весов и извлечения любых привычек пока нет.", ("memory.write",)),
    Capability("integrations", "Внешние сервисы и умный дом", "partial", "Адаптеры SearXNG и Brave Search с отдельным доступом к поиску. Home Assistant, медиа и доски задач ещё не подключены.", ("integrations.connect",), ("searxng", "brave-search")),
    Capability("workflows", "Сценарии и уточнения", "partial", "Уточнение времени или названия задачи, перенос и отмена недавней записи; контекст на 15 минут. Произвольные многошаговые сценарии ещё не реализованы.", ("workflows.run",), ("local-dialogue",)),
    Capability("privacy", "Безопасность и приватность", "partial", "Ключ локального сеанса, системное хранилище API-ключей, журнал действий, ручные резервные копии с защитой перед восстановлением. Пароль, шифрование и голосовая идентификация ещё не реализованы.", ("security.configure",)),
    Capability("proactivity", "Проактивность", "planned", "Будущие правила инициативы, тихие часы, предложения по контексту и явное отключение.", ("proactivity.suggest",)),
    Capability("multimodal", "Изображения, экран и камера", "partial", "Чат, документы и голос работают; изображения, камера и чтение экрана требуют отдельных адаптеров.", ("images.read", "screen.read", "camera.read")),
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
