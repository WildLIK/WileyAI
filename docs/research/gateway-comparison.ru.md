# Сравнение решений для WileyAI Gateway

Аудит 29 октября 2026 года. Проверены 24 указанных репозитория: метаданные,
точный commit, последние изменения/Issues, лицензии и выбранные исходники
авторизации, транспорта, моделей и хранения. Полный перечень прочитанных файлов,
commit SHA и ссылок на Issues: [машинный инвентарь](gateway-source-inventory.json).
Снимки исходников для повторной проверки находятся в игнорируемом
`local/review/gateway-research/`; сторонний код не добавляется в продукт.

**Проверено в работе** ниже означает только собственные тесты WileyAI, а не
работоспособность аккаунта из README чужого проекта. Реальных тестовых аккаунтов
для этих проектов не предоставлено. Статический аудит не заменяет pentest,
анализ всех транзитивных зависимостей или заключение об условиях сервиса.

Обозначения: **К** — подтверждено просмотренным кодом; **З** — заявление автора,
не подтверждённое этим аудитом; **Н** — нет подтверждения; **О** — ограничение /
отключено. Наличие файла теста само по себе не означает успешного тестирования.

## Критерии допуска

Рассматривались все 22 пункта задания: состояние проекта, провайдеры,
авторизация/ключи, бесплатные аккаунты/подписки, Linux/ресурсы/браузер/Docker,
streaming/история/вложения/генерация/размышления/поиск/tools/MCP, ограничения,
лицензия, хранение, риск блокировки и совместимость.

Для **всех 24 проектов** CPU/RAM на VPS **не измерены**. Браузерные варианты
требуют дополнительного бюджета процессов и профилей; численные требования
не выдумываются. Поддержка Docker — это наличие конфигурации в коде, а не
проведённый запуск. Бесплатность и квоты без реального аккаунта не подтверждены.
Веб-подписка не считается разрешением на сторонний автоматический интерфейс.
Автоматические пулы чужих/новых аккаунтов для обхода квот не допускаются.

## 1. Многопровайдерные шлюзы

### OpenToken — kai648846760/opentoken

- Снимок: `9e67b39e36a82dc5b9b65622aa02bfe31bdc0768`, обновление 4 июня 2026,
  MIT, Python >=3.13. Последний commit удаляет MiniMax как больше не подходящий
  обычному чат-адаптеру. Значит, старый список README нельзя считать каталогом.
- **К:** независимые провайдеры, HTTP/SSE, нормализованный запрос, модельный
  discovery, fallback-каталог и разбор эмулированных tool calls. Есть DeepSeek,
  Qwen, GLM, ChatGPT и браузерные клиенты других систем. Международные и китайские
  ветви различаются. Из просмотренного Qwen-кода не следует полноценная загрузка
  файлов: поле `files: []` не является работающим vision-интерфейсом.
- Авторизация: веб-токены/cookies и собственный gateway bearer. `auth_profiles.py`
  сохраняет credential record в JSON; шифрование этого значения не обнаружено.
  Нужны Camoufox и wasmtime. В DeepSeek есть реализация challenge/PoW; она не
  переносится в WileyAI. Код discovery содержит статические аварийные fallback ID.
- Linux технически подходит; browser lifecycle надо изолировать. Текст/stream и
  архитектурный контракт полезны, но аккаунты и мультимодальность не проверены.
  Решение: самостоятельный контракт WileyAI, без подключения OpenToken целиком.
- [Исходники и лицензия](https://github.com/kai648846760/opentoken/tree/9e67b39e36a82dc5b9b65622aa02bfe31bdc0768).

### Chat2API — xiaoY233/Chat2API

- `59f03ab2988867a4d7bacb97d98f3ee018b0e4d0`, 28 мая 2026; package объявляет
  GPL-3.0, файл LICENSE содержит GPLv3 (GitHub metadata даёт NOASSERTION).
- **К:** Electron, таблица провайдеров DeepSeek/GLM/Z.ai/Qwen/Kimi/MiniMax и др.,
  локальный proxy server, управление входом. Название каталога `oauth` не означает
  стандартный OAuth: `tokenExtractionConfig.ts` читает network headers,
  localStorage и cookies. `inAppLogin.ts` логирует начало Set-Cookie header —
  такой шаблон неприемлем для секретов WileyAI.
- Текущий commit помечает Z.ai как CAPTCHA-limited; Issues #200 о безопасности,
  #202 об ограничениях DeepSeek. Эти сообщения — свидетельства авторов Issues,
  не самостоятельно воспроизведённые уязвимости. Z.ai-настройка предлагает HAR
  verification parameter; этот путь исключён.
- Linux VPS без GUI требует выделения backend и замены Electron login/runtime.
  Streaming/tools/models требуют аудита соответствующих реализаций, а не только
  builtin-конфигураций. Мультимодальность и реальная бесплатная квота — Н.
  GPLv3-код не копируется; при будущем повторном использовании потребуются
  отдельная проверка совместимости и выполнение условий распространения.
- [Снимок](https://github.com/xiaoY233/Chat2API/tree/59f03ab2988867a4d7bacb97d98f3ee018b0e4d0).

### CLIProxyAPI — router-for-me/CLIProxyAPI

- `90c447d3a8727d115aa7552ec93ce023736ed492`, актуальные изменения 29 октября,
  MIT, Go, есть Dockerfile. Это сильнее подходит headless VPS, чем Electron.
- **К:** отдельные auth/executor/translator/registry, SSE и совместимые протоколы,
  credential sessions, управление маршрутизацией. Просмотрены Codex OAuth/SIWC,
  executor Codex/Gemini и management callback/session handlers.
- Важно: Codex/Gemini CLI и похожие источники — не полный ChatGPT/Gemini веб-чат.
  Не все OAuth client ID можно заимствовать для другого продукта. Модельные
  capabilities и законность конкретного upstream требуют отдельного допуска.
- Последние Issues затрагивают WebSocket access и утечку reasoning-полей при
  fallback; автоматический fallback WileyAI должен быть выключен без согласия.
  Файлы auth-volume сами по себе не равны зашифрованному vault. Бесплатный веб-
  аккаунт и полный набор медиа не подтверждены. Полезен как пример разграничения
  протоколов, не как гарантия доступа ко всем сайтам.
- [Снимок](https://github.com/router-for-me/CLIProxyAPI/tree/90c447d3a8727d115aa7552ec93ce023736ed492).

### OpenHinge — openhinge/openhinge

- `d04d49e8d8087312813412014535d416e197767f`, 20 апреля 2026, MIT, TypeScript/
  Fastify. **К:** BaseProvider, health/models/chat/stream, унифицированные tools,
  reasoning-поля, admin middleware, шифрование credentials перед записью SQLite.
- OpenAI provider читает `~/.codex/auth.json` и отдельно старается не расходовать
  его refresh token; последний fix связан именно с этим. WileyAI не будет читать
  чужое приложение или разделять его сессию. Поддержка Claude/OpenAI/Gemini/Ollama
  здесь не доказывает поддержку их браузерных чатов.
- Возможности и подписки зависят от типа upstream; вложения/генерация/веб-история
  не подтверждены просмотренными файлами. Полезны интерфейсы и контроль admin,
  а не импорт локальных credentials. VPS возможен без browser для API-ветвей.
- [Снимок](https://github.com/openhinge/openhinge/tree/d04d49e8d8087312813412014535d416e197767f).

## 2. ChatGPT, Gemini, Grok

| Проект / состояние / лицензия | Что подтверждено кодом | Ограничения, авторизация и решение |
| --- | --- | --- |
| [Browser LLM API](https://github.com/StaticB1/browser-llm-api/tree/232608d0cace72000d8016a47b13d8040a7ff46c), 22.10, MIT | Python provider lifecycle, ChatGPT/Gemini DOM polling, input images, generated images/MCP methods, bearer для удалённых клиентов | Постоянный Chromium/профиль, недокументированный DOM, browser auth. Код authz отдельно предупреждает об опасности server-side paths и cross-origin loopback. Публичные image URLs не подходят для приватного многопользовательского Gateway. Квоты/подписки/CPU — Н. Не включён. |
| [CatGPT Gateway](https://github.com/FlameFront-end/chatgpt-gateway/tree/83ed19bd8ad9716fe805b5b767e678dd0d2e8395), 13.05, MIT, Dockerfile | Загрузка локальных изображений/файлов в composer, извлечение generated images, prompt/parser эмуляция инструментов | `openai_routes.py:543` явно отклоняет stream=true. Playwright-stealth/human simulation исключены из продукта. API errors могут включать exception text; не копировать обработчик. Веб-история и account quotas — Н. |
| [GPT Web Gateway](https://github.com/stufently/gpt-web-gateway/tree/e1b1bd87d0f009ea8a0ce472814ceca485043280), 29.10, MIT, Docker/Helm | Node browser lifecycle, SSE transform, login/session-health, image routes, capabilities probe | Есть Cloudflare/Turnstile/auto-login/fingerprint modules. Не копировать их механизмы. `login.js` сохраняет browser state JSON; диагностические screenshots и JSON требуют отдельной redaction-политики. Постоянный browser, headless-вход не равен поддержанному OAuth. |
| [Web2API](https://github.com/glidea/web2api/tree/d76375f71248ec07da7bd1feff338751baaf1f3c), 10.08, лицензия не обнаружена | Chrome extension + daemon, ChatGPT/Gemini/Grok DOM adapters, image payload, модель/effort capabilities, Responses API/tool protocol | Без текста лицензии исходники не заимствовать. Для VPS нужны Chrome и управляемые профили, не только Node daemon. DOM capabilities — наблюдение UI, не подтверждение успешного vision/media. Tools эмулированы; личные cookies остаются browser state. |
| [webllm-proxy](https://github.com/SamuelHaidu/webllm-proxy/tree/b8b78ea699a3187fe447ccfbf924a90664bf2c7c), 16.07, MIT | Python providers ChatGPT/Copilot/Databricks, SSE/research parsers, tag-based tools, model discovery | Chrome/Edge real profile или CloakBrowser; backend-api/in-page fetch и чужие профили не допускаются автоматически. Copilot — отдельный SignalR/web upstream. Мультимодальность полного веб-чата — Н. |
| [ChatGPT Web Session Proxy](https://github.com/cromat/chatgpt-web-session-proxy/tree/753d7d8c5f0fa3fe5f342839b016dfb18b781b0b), 20.09, MIT | TypeScript browser/session lifecycle, transcript, OpenAI compatibility, validated tool protocol; session JSON атомарно с mode0600 | Права файла не являются encryption-at-rest. Browser/Xvfb, API key опционален в просмотренном server.ts — нельзя выносить как есть в интернет. Генерация медиа/vision/поиск — Н. Не включён. |

## 3. DeepSeek и Qwen

| Проект | Код, возможности и эксплуатация | Решение |
| --- | --- | --- |
| [FreeDeepseekAPI / ForgetMeAI](https://github.com/ForgetMeAI/FreeDeepseekAPI/tree/648e708498bfae54cce085015fe5cf6e3e02b414), 07.10, MIT | Node SSE/keepalive, per-user sessions, timeouts/cancel, OpenAI/Anthropic, TOOL_CALL parser; commit заявляет проверенные автором image uploads. `server.js` импортирует solvePOW, auth script получает browser cookies. Issues: слишком много чатов/пустые ответы | Пользовательский live-тест отсутствует. Challenge/credential harvesting не переносится. Хорошие идеи cancellation/idempotency, но не готовый допустимый DeepSeek upstream. |
| [FreeDeepSeekAPI / afterburnerr](https://github.com/afterburnerr/FreeDeepSeekAPI/tree/8b787f680c5bb62a9503ad30196eae893ef50d01), 13.05, LICENSE с MIT и атрибуциями | Python FastAPI + Docker. Это преимущественно browser/cookie bridge: `CloudflareBypasser` и cookie response в server.py; не равно первому проекту | Не использовать обход и cookie endpoint. Полный SSE/chat/media не подтверждён выбранным кодом. GitHub NOASSERTION требует читать LICENSE/происхождение отдельно. |
| [Zourcewell](https://github.com/gyatstian/zourcewell/tree/dcae1aafd3c50ec4fc752a5bc228bdef0b7c310b), 26.10, MIT | Python DeepSeek/Qwen clients, prompt/DSML/JSON tool parsers, transport/account manager, MCP. `obscura_bridge.py` прямо описывает WAF-cleared cookies | Ветка с таким обходом исключена. Изолированно оценивать типизированные события/парсер; не переносить transport/login. Web-context и размышления не дают права на скрытые chain-of-thought данные. |
| [QwenProxy](https://github.com/FmcStore/qwen-api/tree/3670c1d7228775e761e0595107ae48f6c07c7f37), 28.09, package MIT, отдельный LICENSE не найден | Node22, Puppeteer + stealth, Docker; server/upload/toolparse содержат streaming, temporary-credential file upload, image/video-related handling, resume state. TTS — З/отдельно не проверен | Token pool читает farmer/output, есть challenge handling и debug payload dump. Не запускать farmer/stealth и не переносить секреты/логи. Небольшой эксперимент, требуется отдельная проверка лицензии и upstream permission. |
| [Qwen Code](https://github.com/QwenLM/qwen-code/tree/939f795eaaff173271d46acfbf9a8b67a4571bb2), 29.10, Apache-2.0 | Официальный CLI/daemon, device-flow registry, SSE, credential redaction и runtime API; большое число тестов | Официальная документация: бесплатный OAuth прекращён 15.04.2026. Наличие legacy qwen-oauth handler не означает работающий бесплатный вход. Текущий вход — QwenCloud/ModelStudio plans/keys/custom providers. Не показывать Qwen Code как бесплатный веб-аккаунт. |

## 4. GLM, Kimi и дополнительные системы

| Проект | Подтверждения из кода | Ограничения и совместимость |
| --- | --- | --- |
| [FreeGLMKimiAPI](https://github.com/ForgetMeAI/FreeGLMKimiAPI/tree/8aa1db707b2ffa2e44393f4e7bc40b71cefc35b9), 20.06, LICENSE не найден | JS: отдельные GLM China, Z.ai Intl, Kimi; refresh/backend calls, SSE/session store, mockProvider, prompt tools | `accounts.js:96` сохраняет токены JSON. Browser fallback/CAPTCHA handling, старые private endpoints. Не путать GLM China credentials с Z.ai. Не включён; mock-архитектура полезна без копирования кода. |
| [GLM-Free-API](https://github.com/izaart95-jpg/GLM-Free-API/tree/3b23a69833a29f3275a255858850adbe8cfd1abf), 22.10, MIT, **архивирован** | Go: dynamic models/capabilities, vision, session pool, tool parser/tests, web-search flags | Есть captcha/WAF modules. Issues #49/#47 сообщают WAF failures после работы; #51 — tool problems. Guest login не считать бесконечным разрешением. Не подключать в рабочий каталог. |
| [Kimi Code](https://github.com/MoonshotAI/kimi-code/tree/be89803bc6db08ff8335c1dc12ade79e3bbed56e), 29.10, MIT | Официальный device OAuth, региональные endpoints, managed credentials, REST/WebSocket server, schemas и quota endpoints | Это Kimi Code membership, не kimi.com web-chat. Возможна отдельная поддержанная интеграция через его локальный server с собственной изоляцией; нужны pinned runtime/schema и проверка account tier. Секреты напрямую из его файлов не импортировать. |
| [GPT4Free](https://github.com/xtekky/gpt4free/tree/8bdab3152e2d4f16fcced8c73ee842f346a8073f), 29.10, GPL-3.0, Docker | Большой registry, разные auth modes, Qwen/Copilot/Pollinations implementations, multimodal value types и streaming | Слишком неоднородный upstream для обещания поддержки всего каталога. Например Pollinations.py уже использует Authorization. Есть browser/error/retry paths, требуется отдельный допуск каждого. Не импортировать GPL-код или случайные публичные proxies. |
| [AndroidHarness](https://github.com/Sanuu7/AndroidHarness/tree/628f6aabfdf995fdcbf02e7617e2385251019739), 29.10, MIT | Kotlin model capability tri-state, local catalog, Responses implementation, MCP OAuth и public-address checks | Полезен как пример Android типов/состояний. Его root/Shizuku/agent shell не переносится в WileyAI. encrypted reasoning content — непрозрачное служебное поле, не текст для отображения/расшифровки. Не сервер для VPS. |
| [MobMock](https://github.com/wamynobe/mobmock/tree/5b3d0bd0b2554424d7149921004b19087b89fb6e), 15.04, MIT | Kotlin PKCE/refresh, upstream translation, local sessions, SSE translator в дереве | `AuthStorage.kt` пишет JSON в filesDir без Keystore; app sandbox не заменяет шифрование. Есть статическая нормализация моделей и Codex-подобный upstream: не полный веб-чат. Не заимствовать auth storage. |
| [Perplexity Web API MCP](https://github.com/mishamyrt/perplexity-web-api-mcp/tree/4604fee2e358f8f4ce0c1af547dd8883d701f545), 15.04, MIT, **архивирован**, Docker | Rust auth cookies, SSE search, structured sources/uploads, MCP wrappers | Issue #15 прямо сообщает о поломке после изменений Perplexity. Имитация веб HTTP client и cookies не являются официальным API. Research/Pro требуют account credentials и реальной проверки. Не включён. |
| [Perplexity Web MCP](https://github.com/quequiere/perplexity-web-mcp/tree/44863367bb545c462cfc1be871563e3cee3a7247), 06.03, MIT | Playwright/CDP, DOM search, сбор ссылок/sources; ожидает завершения ответа | `search.ts` логирует запрос. MCP возвращает законченный search result; это не доказательство потокового Chat Completions интерфейса. Тяжёлый browser profile, селекторы/локаль нестабильны. Нет подтверждения uploads/media. |
| [Hermes Web CLIs](https://github.com/lesterppo/hermes-web-clis/tree/ee0f9bbbbd96594d8d20832b3e6c95b7a415ec37), 01.09, MIT | Разные HTTP/browser CLIs для Qwen/Kimi/MiniMax/Grok/Claude; отдельные file/reasoning paths | Код читает Firefox cookies.sqlite; capture_ff_session и token extraction исключены. Grok commit признаёт browser/worker WebSocket вместо универсального HTTP. Единого VPS lifecycle/account manager нет. Использовать только идеи декомпозиции. |

## 5. Что допускается в WileyAI

1. Собственный независимый Gateway, строгая авторизация владельца, шифрование
   sessions, сохранение потока и динамический каталог. Ни один из 24 проектов
   не включается автоматически в runtime.
2. ChatGPT: официальный Sign in with ChatGPT для open-source apps с собственным
   выданным client ID и разрешением `chatgpt.tokens.use.direct`, если интеграция
   и аккаунт допущены. Это доступ к разрешённым функциям Responses, а не к полной
   истории и всем функциям chatgpt.com. Реальные scope/модели проверяются после входа.
3. Kimi Code — перспективный отдельный официальный OAuth/server адаптер; coding
   account явно отделён от web account. Gemini CLI headless по официальной
   документации не обещает простой Google OAuth без API-источника.
4. Официальные API и свои разрешённые сервисы — необязательная альтернатива;
   ключ не является обязательным для самого Gateway. Локальный Android Qwen
   работает независимо.
5. Keyless/WebSession контракты предусмотрены; конкретный upstream появляется
   только после подтверждения поддержанного интерфейса. Никаких фиктивных
   активных DeepSeek/Qwen/GLM подключений или моделей из статического README.

## Первичные условия и официальные альтернативы

- [OpenAI: регистрация и scopes](https://developers.openai.com/siwc/token-sharing-open-source/sign-in),
  [ошибки допуска](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).
- [Qwen Code: прекращение OAuth](https://qwenlm.github.io/qwen-code-docs/en/users/quickstart/),
  [Qwen Terms](https://qwen.ai/termsservice): автоматическое извлечение запрещено.
- [DeepSeek Terms](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html):
  ограничения автоматического копирования и reverse engineering.
- [Claude: сторонние приложения](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account):
  использовать API/поддержанную платформу; не представляться нативным приложением.
- [Z.ai Terms](https://chat.z.ai/legal-agreement/terms-of-service).
- [Kimi Code server API](https://github.com/MoonshotAI/kimi-code/blob/main/docs/en/reference/server-api.md).
- [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/).
- [MiMo official](https://mimo.xiaomi.com/), [актуальная продуктовая страница](https://mimo.mi.com/):
  веб и API существуют отдельно; отсутствие документов разрешённого web-session
  API не компенсируется обратной разработкой.
- [Doubao terms](https://www.doubao.com/legal/terms): права на извлечение/публикацию
  контента ограничены; доступ за пределами Китая не проверен.
- [Poe external applications](https://creator.poe.com/docs/resources/frequently-asked-questions):
  официальный программный путь требует отдельной проверки credential/quota.
- [Hugging Face Chat UI](https://huggingface.co/docs/chat-ui/configuration/overview):
  OIDC для пользователей и inference credential — разные уровни.
- [Mistral subscriptions](https://docs.mistral.ai/admin/billing-usage/subscriptions):
  актуальная страница описывает общий monthly usage; более старые материалы о
  раздельном биллинге не использовать как гарантию.
- [MiniMax billing](https://agent.minimax.io/doc/en/billing-upgrade-en.html):
  планы/credits изменились; «бесплатный старый веб-чат» не фиксируется в коде.
- Дополнительные кандидаты: [Puter, квоты аккаунта](https://docs.puter.com/user-pays-model/)
  и [Pollinations, официальный API](https://github.com/pollinations/pollinations).
  Они требуют собственного пользовательского допуска и не являются безлимитными
  заменами личных аккаунтов всех перечисленных провайдеров.

Полный технический протокол, реализация и реально пройденные проверки описываются
отдельно: этот отчёт фиксирует результат исследования **до** интеграции.
