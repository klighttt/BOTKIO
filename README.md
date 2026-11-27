# Дневник настроения 2.0

## Файлы

| Путь | Назначение |
| --- | --- |
| `server/server.py` | HTTP API, регистрация, вход, серверные сессии, чат и назначение роли |
| `server/schema.sql` | SQLite: пользователи, сессии, сообщения, активность и результаты |
| `app/src/main/assets/index.html` | Интерфейс, стили, опрос, настройки, поддержка и админ-панель |
| `app/src/main/java/ru/kyrsovaya/mood/MainActivity.kt` | Android WebView |
| `app/src/main/AndroidManifest.xml`, `app/src/debug/AndroidManifest.xml` | Настройки Android и сети |
| `app/src/debug/res/xml/local_network.xml` | Локальный HTTP для эмулятора только в debug-сборке |
| `app/src/main/res/values/styles.xml`, `app/src/main/res/drawable/ic_mood.xml` | Тема, адрес сервера для release и значок |
| `build.gradle.kts`, `settings.gradle.kts`, `app/build.gradle.kts`, `gradlew*`, `gradle/wrapper/` | Сборка Android Studio и Gradle Wrapper |

## Запуск на Windows

1. Установить Python 3.11 или новее. В PowerShell из папки проекта запустить `py -3 server/server.py` и оставить окно открытым. Сервер слушает только локальный адрес. База появится по пути `server/mood.sqlite3`.
2. Для проверки в браузере открыть `http://127.0.0.1:8080/`. Для Android открыть папку проекта в Android Studio, выбрать Pixel 7 и нажать Run для конфигурации app. Debug-сборка обращается к тому же серверу через адрес эмулятора 10.0.2.2. Вариант с готовым APK устанавливается перетаскиванием файла на экран эмулятора. Если Android сообщает о несовместимой подписи, используй сборку из Android Studio с той же подписью, что и предыдущая установка.
3. Создать аккаунт и пройти опрос. Оценка, тема и заметка сохраняются в новом аккаунте. Данные 1.3 из локального WebView автоматически не переносятся.
4. Для доступа сотрудника сначала зарегистрировать отдельный логин. Во втором PowerShell выполнить `py -3 server/server.py --grant-admin LOGIN` с фактическим логином. В аккаунте сотрудника отправить в «Поддержку» ровно `5051`. Вкладка «Админ» появится посередине. Команда не публикуется в чате. Для отзыва роли использовать `--revoke-admin LOGIN`.

Для доступа со смартфонов вне эмулятора настрой HTTPS-прокси перед локальным сервером, передай серверу `--https-origin https://your-domain.example` и тот же адрес укажи в ресурсе `server_url` release-сборки. Прокси должен сохранять исходный Host. В этом режиме cookie помечается Secure.
