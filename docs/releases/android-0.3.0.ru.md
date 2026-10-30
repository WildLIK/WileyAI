# WileyAI Android 0.3.0 — первый этап самостоятельного приложения

28 октября 2026. Windows остаётся на версии 0.14.0; код Windows-ядра и UI не изменён.

## Реализовано

Телефонный чат открывается без сопряжения, интернета и LLM. SQLite хранит сообщения,
ответы телефонных команд и черновики. Есть создание/выбор/переименование/удаление
чатов, ограниченная начальная загрузка истории, копирование и повторная отправка
своего текста. Текстовые команды приложений/громкости/музыки работают через прежний
детерминированный парсер и Android API.

Четыре темы используют исходные цвета `src/themes.css`; есть системный выбор темы,
навигатор разделов и информационный каталог компонентов. UI остаётся Java/Views;
переход к Kotlin/Compose вынесен в следующий проверяемый шаг. Сохранены сопряжение,
pinning, Keystore, компьютерные чаты/SSE/остановка, задачи/заметки и голос через ПК.

## Изменённые файлы

- `android/app/src/main/java/ru/wildlik/wileyai/mobile/MainActivity.java` — экран,
  навигация, явные режимы телефона/ПК и подключение контроллеров.
- В том же пакете добавлены `PcGateway.java`, `PhoneActionEngine.java`,
  `SettingsRepository.java`, `LocalChatRepository.java`, `LocalChatController.java`,
  `MobileUi.java`, `WileyTheme.java`, `MessageRenderer.java`, `ComponentCatalog.java`.
- `PhoneCommands.java` — вариант «какая сейчас громкость?».
- `android/app/build.gradle` — версия 0.3.0/code 3 и SDK-only instrumentation runner.
- `android/app/src/androidTest/java/ru/wildlik/wileyai/mobile/StageOneInstrumentation.java`
  — девять тестов настоящих Android API: SQLite, миграционный отказ, Keystore,
  валидация сопряжения, Markdown, открытие главного экрана.
- `tests/test_android_storage.py`, `tests/android/PhoneCommandsProbe.java` —
  сохранность схемы SQLite, палитры, границы команд.
- `scripts/build-android.ps1` — флаг `-Check`;
  `.github/workflows/check.yml` — отдельная сборка/lint Android и JVM-проба в CI.
- `README.md`, `docs/android.ru.md`, `docs/android-stage1.ru.md`,
  `docs/implementation-status.ru.md`, `docs/roadmap.ru.md` — актуальное описание.

## Проверено

- `build-android.ps1 -Offline -Check`: **BUILD SUCCESSFUL**.
  Собраны приложение и APK девяти инструментальных тестов.
- `lintDebug`: **0 ошибок, 4 предупреждения**. Остались CustomX509TrustManager
  (прежний pinning), DataExtractionRules (прежний manifest), UsableSpace
  (информационный снимок диска) и SetTextI18n (строка времени связи).
  Предупреждения не скрывались baseline-файлом или отключением проверок.
- Целевой pytest с включёнными `WILEYAI_MOBILE_NETWORK_TEST=1` и
  `WILEYAI_ANDROID_JVM_PROBE=1`: **169 passed in 10.76s**, без пропусков.
  Включены host SQLite, mobile gateway, команды, device audio и verified actions.
- `PhoneCommandsProbe`: **Phone command routing passed**.
- `npm run build`: TypeScript и Vite успешно; предупреждение Vite о крупных чанках
  осталось. Первая попытка была ограничена sandbox (`spawn EPERM`), повтор прошёл.
- `git diff --check`: нет ошибок пробелов; только уведомления Git LF/CRLF.
- `apksigner verify --print-certs`: APK валиден; SHA-256 сертификата совпадает с 0.2.0:
  `4643c2b21b75084b431880154c9417a1fa42c1759f089df50a88768e4537a521`.

## Не проверено и не реализовано

Подключённых Android-устройств и AVD нет. Инструментальные тесты **не выполнены**.
Визуальное качество, поворот, микрофон, запуск сторонних приложений, реальная
SQLite/Keystore после перезапуска и обновление поверх 0.2.0 ещё требуют устройства.
Совпадение подписи позволяет подписанное обновление, но не заменяет такой тест.
Полный desktop Playwright-набор не запускался: Windows UI не менялся.

Локальная речь, LLM/GGUF, прямые облака, установка/скачивание моделей, полный
Markdown, синхронизация, экспорт диагностики и системные дополнения ещё не готовы.
Поддержанных и испытанных на Android моделей сейчас **нет**. Для телефонных текстовых
команд модель не нужна. Интернет нужен для загрузки сайтов и облачных провайдеров
компьютера; локальная сеть с ПК не требует обязательного облака.

## Артефакты и следующий этап

APK: `local/releases/WileyAI-Android-0.3.0-debug.apk`, SHA-256 рядом в `.apk.sha256`.
Это локальная тестовая сборка; на устройство автоматически не устанавливалась.
Инструкции сборки/установки тестов: [Android](../android.ru.md).

Далее: проверка обновления и UI на телефоне, затем минимальный русский ASR/TTS-комплект
с явным размером, проверкой целостности и настоящим тестом работы. Модели без
подтверждения пользователя не устанавливались.
