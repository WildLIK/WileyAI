# Прямые облачные модели для Android-помощника

30.10.2026. Приоритет — model → проверенный Android tool → фактический результат.
Собственный VPS не является обязательным. Ниже различаются документированный
интерфейс, реализованный клиент и реально проверенный личный аккаунт. Ни один
непроверенный аккаунт не объявляется подключённым.

## ChatGPT / OpenAI

Официальный [SIWC для локальных/OSS приложений](https://developers.openai.com/siwc/token-sharing-open-source)
описывает собственную динамическую регистрацию, стабильный ID установки,
PKCE/nonce/state и loopback callback. Документы не требуют собственного proxy
для такого локального HTTP-клиента. Отдельное явное одобрение именно WileyAI Android
этим фактом **не подтверждается**. Публичный репозиторий WileyAI имеет license=null
в GitHub metadata; лицензию проекта мы не назначаем автоматически. Соответствие
всем условиям распространения/OSS и коммерческий выпуск требуют отдельной проверки.

Реализован прямой Android-клиент: системный браузер → одноразовый loopback →
официальный token endpoint → проверка JCA RSA/EC подписи и OIDC полей → Android
Keystore. Используется выданный своему приложению client_id, никакие регистрации
Codex/CLI и чужие credentials не заимствуются. Допуск/разрешения определяются
реальным входом, который mock/JVM тест не заменяет.
[Протокол входа](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).

Каталог запрашивается для текущего аккаунта; production model IDs не зашиты.
Inference идёт прямо в `/v1/responses`, `store=false`, `stream=true`, с проверкой
terminal acknowledgement. Клиентские функции допускаются в namespace; native
tools включаются только после безопасной проверки выбранной модели. До этого
план — строгий JSON с локальной валидацией.
[Модели и запросы](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference),
[ограничения preview](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).
Это не перенос истории chatgpt.com и не обещание функций всех платных планов.

## Сравнение остальных способов

«Не подтверждён» означает отсутствие установленного разрешённого прямого входа
в личный веб-аккаунт WileyAI, а не утверждение, что сервис никогда его не предложит.
Квоты/планы/регионы меняются и проверяются аккаунтом, численный безлимит не обещается.

| Сервис | Прямой программный путь и границы |
| --- | --- |
| DeepSeek | Официальный HTTP API требует API credential, совместим с Chat Completions/Anthropic; есть streaming и инструменты. Поддержанный Android OAuth личного web-чата не подтверждён. [Официальный старт](https://api-docs.deepseek.com/). |
| Qwen | В актуальном Qwen Code прежний бесплатный OAuth помечен прекращённым с 15.04.2026; текущие QwenCloud/ModelStudio способы используют keys/планы. Клиент веб-чата не подменяется CLI registration. International/China различаются. [Авторизация](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/). |
| GLM / Z.ai | Официальный REST/Java/OpenAI-compatible путь требует ключ. Вход chat.z.ai и китайский ChatGLM — отдельные сессии; поддержанный перенос веб-аккаунта в WileyAI не подтверждён. [Документация](https://docs.z.ai/guides/overview/quick-start). |
| Gemini | Документирован OpenAI-compatible API с каталогом и tools; используется credential Google AI Studio. Free tier существует для части моделей, это не личная подписка Gemini и не отсутствие авторизации. [Совместимость](https://ai.google.dev/gemini-api/docs/openai), [тарифы](https://ai.google.dev/gemini-api/docs/pricing). |
| Claude | API keys/WIF документированы; App Attest описан для iOS/macOS, Android таким допуском не объявляется. Веб-подписка не заимствуется. OpenAI compatibility есть, strict schema может игнорироваться — локальный валидатор обязателен. [Auth](https://platform.claude.com/docs/en/manage-claude/authentication), [compatibility](https://platform.claude.com/docs/en/cli-sdks-libraries/libraries/openai-sdk). |
| Kimi | Официальные API требуют key; доступны Chat Completions/Responses/Messages, streaming/JSON/tools. Kimi Code OAuth — отдельный coding продукт, не универсальный вход kimi.com. [Quickstart](https://platform.kimi.ai/docs/get-your-api-key). |
| Grok | Официальный inference с API credential, Responses и functions; перенос бесплатной/платной сессии grok.com не подтверждён. [API](https://docs.x.ai/docs/api-reference). |
| MiniMax | API и coding/agent планы отделены от пользовательского web login. Разрешённый прямой web OAuth для WileyAI не подтверждён; старые ссылки документации могут перенаправляться/быть недоступны. Личный аккаунт не проверен, адаптер не выдаётся за рабочий. |
| Mistral | Документирован собственный API; Studio предлагает Free mode с выдачей credential. Это допустимая API-альтернатива, не перенос cookies Le Chat. Реальная квота владельца не проверена. [Официальные quickstarts](https://docs.mistral.ai/). |
| Perplexity | Актуальные документы содержат миграцию Sonar→Agent API и изменённые endpoints. Нельзя закреплять старый адрес как вечный web-account bridge. API credential и quota обязательны согласно выбранному интерфейсу. [Миграция](https://docs.perplexity.ai/guides/chat-completions-guide). |
| Puter | Документированный JavaScript SDK имеет user auth, модельный каталог, streaming и tools. Это агрегатор; пользовательский бюджет/разрешения Puter не равны аккаунтам OpenAI/Qwen. Нативный Android account adapter пока не реализован; скрытый JS/серверный мост не добавляется. [Вход SDK](https://docs.puter.com/auth/signIn/), [AI chat](https://docs.puter.com/AI/chat/). |
| Pollinations | Рассматривался как отдельный агрегатор с авторизацией/бюджетом; готового keyless Android account adapter в выпуске нет. Старые анонимные URL не объявляются бесплатным безлимитом. [Официальная точка входа](https://enter.pollinations.ai). |
| OpenRouter | Есть документированный OAuth PKCE, выдающий пользовательский API credential, а также ограниченные `:free` модели. Это дополнительный агрегатор, не официальный вход DeepSeek/ChatGPT. Встроенный OAuth adapter OpenRouter пока не реализован. [PKCE](https://openrouter.ai/docs/use-cases/oauth-pkce), [free models](https://openrouter.ai/collections/free-models/). |

## Что реализуется на Android

LocalProvider использует существующие веса Qwen и грамматику llama.cpp с допустимыми
именами/аргументами. OfficialAPIProvider/DirectCloudProvider используют явный
совместимый endpoint пользователя. Native tools подтверждаются безопасным probe,
иначе StructuredActionAdapter валидирует JSON. AccountOAuthProvider реализует
официальный SIWC напрямую; RemoteGatewayProvider использует сохранённый Gateway.

Модель никогда не исполняет код/Intent сама. Все вызовы проверяются локально.
Результаты передаются только выбранному источнику при отдельном согласии.
При отказе/сбое нет автоматического перехода на другой облачный сервис.
Для прямого API каталог обновляется `GET /models`, где поддержан; при отсутствии
такого метода пользователь вводит ID из официальной документации. Статические
«актуальные модели» и неработающие provider buttons не добавляются.
