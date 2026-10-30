# Аудит Android-помощника перед этапом 0.11

30.10.2026. Новое ТЗ: модель планирует действия Android, собственный сервер
не обязателен. Gateway preview сохраняется как дополнительный режим.

## Что уже есть

- Java17/Views, SDK34/min26; тема MobileUi/WileyTheme, локальная SQLite-история,
  Android Keystore, ASR Vosk/system, TTS Android, VoiceInteractionService и FGS.
- `PhoneCommands` разбирает простые команды без модели. `PhoneActionCore` проверяет
  громкость AudioManager/время/дату/заряд. `PhoneActionEngine` использует AppCatalog
  и безопасные launch intents. `PlayerControl` обращается к выбранным медиасессиям
  и проверяет изменение, `MediaNavigation` открывает поддержанный поиск.
- `LocalLlm`/llama.cpp/Qwen3 0.6B — CPU inference на телефоне. До нового этапа
  модель только пишет текст и не получает инструментов. Native runtime можно
  дополнить JSON grammar sampler без скачивания новых весов.
- `CloudChat` — добровольный прямой Chat Completions API без обязательного VPS;
  `GatewayClient` — отдельный HTTPS/SSE job protocol с восстановлением и AEAD.
  Ни один из них ранее не исполнял tool calls.
- MainActivity и HandsFreeService имеют отдельные точки вызова модели; их
  нужно направить в общий ModelManager/BrainController, сохранив быстрый parser.

## Изменения

Общий контракт `BrainProvider`: LocalProvider, DirectCloudProvider,
AccountOAuthProvider, OfficialAPIProvider, RemoteGatewayProvider. Режимы не
загружают модели/серверы автоматически. Функции сайта и OAuth CLI не считаются
доказательством доступа в Android. Прямой вход ChatGPT требует отдельного
исследования и реальной проверки владельцем.

`AndroidTools` — один allowlist и строгие аргументы; `StrictJson` отклоняет
повторные поля, лишний текст и неизвестные значения. `StructuredActionAdapter`
используется отдельно от native tools. JSON не содержит shell, имён методов,
Intent URI, произвольных классов или исполняемого кода.

`BrainController` ограничивает модельные раунды, действия и время, сохраняет
исходную просьбу и получает подтверждение плана перед изменениями. Каждый шаг
снова проверяет Android permission/lock state. Отложенный callback не может
запустить действие после отмены/истечения scope. Передача результатов облачной
модели требует отдельного согласия для выбранного источника.

`AndroidToolExecutor` повторно использует каталог/медиасессии. Запрос запуска
приложения отличается от проверенного foreground; системный будильник открывает
приложение часов для проверки, без обещания чтения его закрытой базы. Защищённые
настройки не переключаются. Notes/reminders — собственные данные WileyAI;
календарь открывается без чтения событий, usage stats требуют явного special access.

ASR/TTS продолжают работать на телефоне. До физической приёмки новый инструментальный
цикл не объявляется рабочим. Ранее проверенный фоновый вызов 0.10 сохраняется.
