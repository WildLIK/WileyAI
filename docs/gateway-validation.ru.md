# Проверки Gateway preview / Android 0.10.0

**Дополнение 30.10.2026:** S23+ подключён и обновлён. На физическом телефоне прошли
30 проверок, включая HTTPS/SSE, Keystore, миграцию, локальную модель и голос.
Владелец подтвердил живой фоновый вызов и ответ.
[Полный отчёт и актуальный APK](releases/android-0.10.0-device.ru.md).
Ниже сохранён исходный срез от 29.10, когда телефон ещё не был подключён.

29 октября 2026, Windows, Python 3.12, JDK 17.0.20, Android SDK 34 / Gradle 8.9.
Это отчёт о выполненных проверках, **не подтверждение работы всех веб-провайдеров**.

## Выполнено

Команда из корня проекта (в активированном Python/JDK окружении):

```sh
python -m pytest tests/test_gateway.py tests/test_gateway_wire.py \
  tests/test_android_media.py tests/test_android_speech.py tests/test_android_storage.py \
  tests/test_mobile.py tests/test_chatgpt.py tests/test_providers.py \
  -q -p no:cacheprovider --tb=short -rs
```

**149 passed, 2 skipped, 38.78 s**. Сохранённый вывод:
`local/review/gateway-final-regression.log`. Пропуски существующих opt-in тестов:
приватный desktop loopback HTTPS listener и native Windows Credential Manager.
Это не пропуски новой сетевой проверки Gateway.

| Проверка | Что фактически выполнялось |
| --- | --- |
| Настоящий транспорт | `test_gateway_wire.py` запускает uvicorn на TCP 127.0.0.1 и компилирует **тот же GatewayWire.java**, который входит в APK. Java делает аутентифицированные HTTP-запросы, создаёт аккаунт/диалог/job, читает SSE, проверяет историю, idempotency и replay. Upstream — явно тестовый, не нейросеть. |
| OAuth ChatGPT | Локально сгенерирован RSA-ключ, подписан mock identity token, вызваны реальные state/PKCE/nonce/issuer/audience/JWKS проверки, token refresh, revoke, каталог и Responses. Варианты completed/incomplete/quota/missing terminal. К реальному OpenAI аккаунту запросов не делалось. |
| Отмена и ошибки | Отмена до создания job/ACK, отмена ещё не запущенного task, partial rate-limit, server restart, отсутствие автоматического повтора/смены провайдера. |
| Хранение и права | Разные owner, закрытый admin mint, отзыв client token, AES-GCM и неверный ключ/AAD, отсутствие plaintext секрета в DB payload и validation response. |
| Каталог и вложения | Реальный маршрут динамического model discovery на mock upstream, unknown capability отказ, MIME/signature/owner gate, source URLs в SSE и истории, pagination/delete с owner isolation. |
| Парсеры | Bounded Java SSE, дубли ID, обрыв frame, oversized event; upstream line size до разбора, invalid UTF-8/truncated input. |
| Прежние функции | Тесты локальных команд/медиа/произношений/загрузчиков/тем/SQLite, desktop mobile protocol, providers и прежнего ChatGPT. Host SQLite проверяет сохранение v1-истории при добавлении v2 таблицы дедупликации и каскадное удаление. |
| CLI | `python -m gateway init` создаёт отдельную тестовую базу, случайный 32-byte master key и owner.token. Секреты не печатаются, личное хранилище не читается. |

Android проверен командой:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-android.ps1 -Offline -Check
```

**BUILD SUCCESSFUL**, assembleDebug + lintDebug + assembleDebugAndroidTest.
Lint: **0 errors, 30 warnings** (в основном SetTextI18n; также прежние предупреждения
о дисковом месте, network trust и backup rules). Native SDK XML warning сохраняется.
Instrumentation APK скомпилирован, **на телефоне не запускался**.
Вывод: `local/review/gateway-final-build.log`, отчёты:
`android/app/build/reports/lint-results-debug.xml` и `.html`.

Исходный APK от 29.10 (по этому пути теперь находится обновлённая сборка;
актуальный SHA указан в [проверке телефона](releases/android-0.10.0-device.ru.md)):
`local/releases/WileyAI-Android-0.10.0-debug.apk`, package
`ru.wildlik.wileyai.mobile`, versionCode **10**, versionName **0.10.0**,
minSdk26 / targetSdk34, **54 659 800 bytes**.

```text
SHA-256: 5cef1d7e6c99118d8e61cf717e12e4739670e6f4b38e37dfc69e906f9cfb391c
Signer SHA-256: 4643c2b21b75084b431880154c9417a1fa42c1759f089df50a88768e4537a521
```

`apksigner verify --verbose --print-certs` подтвердил v2 подпись; certificate
совпадает с прежней локальной debug-подписью. Это не release-signing для магазина.
`git diff --check` не обнаружил whitespace errors. CI добавлен отдельным Gateway
job с Python/JDK и изолированным сетевым тестом; **удалённый CI ещё не запускался**.

## Не выполнено

- Реальный OAuth/сообщение ChatGPT и допуск данного Android→VPS handoff.
- Реальные модели, квоты и мультимодальные запросы любого личного аккаунта.
- Docker build/Compose и публичный HTTPS VPS: Docker отсутствует, сервер/домен
  не предоставлены. Конфигурация и инструкция подготовлены, не выдаются за deployment.
- Физический S23+ в этом этапе: `adb devices -l` вернул пустой список. APK
  сохранён, но не установлен; background/voice Gateway и Keystore/migration на
  устройстве ещё не подтверждены. Старые живые проверки версии 0.8 не заменяют эти.
- Нагрузочный benchmark, vulnerability scan образа/всех транзитивных зависимостей,
  root-compromise hardening, backup/restore и key rotation.

Следующая приёмка: поднять собственный VPS/HTTPS, войти в разрешённый аккаунт
официальным браузером, получить реальный каталог и ответ, проверить отмену/обрыв,
затем установить APK на S23+ и проверить текст/голос через мобильный интернет.
Остальные web-аккаунты не включаются до поддержанного интерфейса и отдельной проверки.
