"""Service identities, not a static list of models or supposedly working functions."""

SERVICES = [
    ("deepseek", "DeepSeek", "https://chat.deepseek.com", "web", "Разрешённый интерфейс веб-аккаунта для стороннего Gateway не подтверждён. Доступны официальный API как альтернатива и локальные модели."),
    ("qwen", "Qwen International", "https://chat.qwen.ai", "web", "Автоматический доступ к веб-чату ограничен условиями; бесплатный Qwen Code OAuth прекращён. Нужен разрешённый программный доступ."),
    ("qwen-cn", "Qwen China", "https://www.tongyi.com", "web", "Отдельная китайская система входа; международная сессия не переносится. Поддержанный вход для Gateway не подтверждён."),
    ("glm", "GLM / Z.ai", "https://chat.z.ai", "web", "Проверенные сторонние проекты используют приватные интерфейсы или обходные механизмы. Рабочий веб-адаптер не включён."),
    ("glm-cn", "GLM China", "https://chatglm.cn", "web", "Это отдельный сервис от Z.ai; совместимость авторизации не предполагается."),
    ("chatgpt", "ChatGPT", "https://chatgpt.com", "oauth", "Официальный вход с разрешением использовать план ChatGPT. Доступ и функции определяются после входа; это не полная копия веб-чата."),
    ("gemini", "Google Gemini", "https://gemini.google.com", "web", "Публичный интерфейс входа в веб-аккаунт для этого Gateway не подтверждён. Gemini CLI — отдельный продукт."),
    ("kimi", "Kimi", "https://www.kimi.com", "web", "Веб-чат и Kimi Code — разные подключения. Импорт веб-токенов не выполняется."),
    ("kimi-code", "Kimi Code", "https://github.com/MoonshotAI/kimi-code", "coding", "Есть официальный device OAuth и server API. Отдельный адаптер Kimi Code пока не установлен; нужен подходящий аккаунт и изоляция runtime."),
    ("claude", "Claude", "https://claude.ai", "web", "Для сторонних продуктов Anthropic указывает API/поддержанную платформу. Заимствование сессии Claude Code не выполняется."),
    ("grok", "Grok", "https://grok.com", "web", "Поддержанный сторонний интерфейс веб-аккаунта не подтверждён; приватные cookies/worker WebSocket не используются."),
    ("minimax", "MiniMax", "https://agent.minimax.io", "web", "Agent/Code/API имеют разные интерфейсы и изменяемые условия планов. Допустимый вход для Gateway пока не реализован."),
    ("perplexity", "Perplexity", "https://www.perplexity.ai", "web", "Найденные browser/MCP проекты не дают подтверждённого поддержанного входа; один архивирован после изменений сервиса."),
    ("doubao", "Doubao", "https://www.doubao.com", "web", "Автоматическое извлечение ограничено условиями. Регион и доступ аккаунта за пределами Китая не проверены."),
    ("mimo", "Xiaomi MiMo", "https://mimo.xiaomi.com", "web", "Официальные веб и API существуют. Разрешённый web-session интерфейс для Gateway не подтверждён."),
    ("copilot", "Microsoft Copilot", "https://copilot.microsoft.com", "web", "Пользовательский вход в веб-чат не считается разрешением на обратную разработку его протокола."),
    ("mistral", "Mistral", "https://chat.mistral.ai", "web", "Официальный API — допустимая альтернатива. Веб-сессия и доступ API не считаются взаимозаменяемыми автоматически."),
    ("huggingchat", "HuggingChat", "https://huggingface.co/chat", "web", "OIDC веб-пользователя и inference credential различаются. Нужен официальный программный источник."),
    ("meta", "Meta AI", "https://www.meta.ai", "web", "Поддержанный сторонний интерфейс личного веб-аккаунта для Gateway не подтверждён."),
    ("poe", "Poe", "https://poe.com", "web", "Есть отдельный официальный путь для внешних приложений; account quota и авторизация требуют отдельного адаптера."),
    ("puter", "Puter", "https://puter.com", "keyless", "Официальный SDK использует пользовательский аккаунт и его квоту. Native/server adapter ещё не подключён."),
    ("pollinations", "Pollinations", "https://enter.pollinations.ai", "keyless", "Сервис требует авторизации и доступного бюджета Pollen. Анонимный безлимит не предполагается."),
]


def catalog(api_profiles=(), test_mode=False):
    rows = [{"id": identifier, "name": name, "website": website, "category": category,
             "available": identifier == "chatgpt", "status": "authorization_required" if identifier == "chatgpt" else "unsupported",
             "description": description, "experimental": identifier == "chatgpt"}
            for identifier, name, website, category, description in SERVICES]
    for profile in api_profiles:
        rows.append({"id": profile["id"], "name": profile["name"], "website": "", "category": "official_api",
                     "available": True, "status": "authorization_required", "description": "Необязательный API-источник, заданный владельцем сервера.", "experimental": False})
    if test_mode:
        rows.append({"id": "test-provider", "name": "Тестовый провайдер — не нейросеть", "category": "keyless",
                     "website": "", "available": True, "status": "test_only", "description": "Только локальная проверка протокола.", "experimental": True})
    return rows
