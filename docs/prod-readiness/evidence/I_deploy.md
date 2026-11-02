# Группа I — развёртывание: измерения и доказательства

Дата: 2026-11-02. Всё локально (127.0.0.1). Tracked-файлы не менялись. Коммит-база: HEAD `a240822`, ветка main (рабочее дерево с чужими незакоммиченными правками шаблонов/тестов, измерения сделаны по состоянию дерева на момент запуска).
Scratchpad (`S`) = `/private/tmp/claude-501/-Users-d-Development-Projects-nyz/5c322686-adbe-4aba-b94e-0bb59a636e3f/scratchpad`.
Скрипты: `docs/prod-readiness/scripts/i_static_refs.py`, `i_gunicorn_probe.sh`, `i_menu_cache_workers.py`. Settings-обёртка: `S/wrap_settings.py` (settings_test + `CompressedManifestStaticFilesStorage` + STATIC_ROOT/MEDIA_ROOT/SQLite в `S`).

## 1. Окружение Python 3.13 и `pip install -r requirements.txt`

Окружение: `conda create -y -n nyz-py313 python=3.13.7` → `Python 3.13.7` (точная версия найдена; создание 14 с).

Установка `pip install -r requirements.txt` (69 строк) **целиком падает**, ошибки по порядку (логи `S/install1.log … install4.log`):

| # | Попытка | Время | Результат | Пакет / причина |
|---|---|---|---|---|
| 1 | как есть | 17 с | rc=1 | `psycopg2==2.9.11` (в requirements, строка `psycopg2==2.9.11`): `Error: pg_config executable not found` (сборка из sdist, wheel для macOS нет; `which pg_config` пусто) |
| 2 | без `psycopg2==` | 12 с | rc=1 | `mysqlclient>=2.0`: `Exception: Can not find valid pkg-config name` / `pkg-config: command not found` (нет `mysql_config`/`pkg-config`; бинарных колёс mysqlclient нет: `pip download mysqlclient --only-binary=:all:` → `No matching distribution found`; на PyPI последняя 2.3.0) |
| 3 | без psycopg2 и mysqlclient | 6 с | rc=1 | снова `psycopg2` (без пина, версия 2.9.13) — тянется как зависимость `django-heroku==0.3.1` (`Requires-Dist: psycopg2` в METADATA): `pg_config not found` |
| 4 | без psycopg2, mysqlclient, django-heroku | 61 с | **rc=0** | все 65 прочих пакетов ставятся (gcloud, google-crc32c, jwcrypto, python-firebase собираются из sdist без ошибок) |
| 5 | `pip install --no-deps django-heroku==0.3.1` | ~2 с | OK | |

Итоговый `pip check` (rc=1): `django-heroku 0.3.1 requires psycopg2, which is not installed.` — единственное нарушение.
`pip install --dry-run psycopg2-binary` → `Would install psycopg2-binary-2.9.13` (колесо для 3.13 есть; не ставил).
Отдельно: на Heroku `pg_config`/`libpq-dev` и `libmysqlclient-dev` (Aptfile) доступны для сборки — не проверено локально (см. раздел «не удалось проверить»).

Что именно «лишнее»: `psycopg2`/`mysqlclient` не используются кодом: `settings.py:14-15` делает `pymysql.install_as_MySQLdb()`; проверено:
```
$ python -c "import anarchia.settings, MySQLdb; print(MySQLdb.__name__, MySQLdb.version_info)"   # env заданы
MySQLdb module is pymysql (1, 4, 6, 'final', 1)
django mysql backend imports OK
```
То есть `mysqlclient` в requirements.txt (последние строки) и `libmysqlclient-dev` (Aptfile:4) не нужны для работы, `psycopg2` нужен лишь как формальная зависимость django-heroku (импорт `django_heroku` и `django_heroku.settings()` без psycopg2 проходят).

Импорты неиспользуемых пакетов под 3.13 (`python -c "import X"`): rethinkdb, pyrebase, gcloud, oauth2client, radicale, boto3, storages, passlib, jwcrypto, httplib2, vobject, google.cloud.storage — OK. **`import firebase` (python-firebase==1.2) → `SyntaxError: invalid syntax` в `firebase/__init__.py:3 from .async import process_pool`** (`async` — ключевое слово). Пакет проектом не импортируется (grep по `app/ anarchia/ manage.py fill_slugs.py` находит только `import pymysql`), ставится без ошибки.

## 2. `check --deploy`, `migrate`, `collectstatic` (settings_test + Manifest storage)

`DJANGO_SETTINGS_MODULE=wrap_settings PYTHONPATH=S:repo python manage.py ...`

`check --deploy` (с `SECURE_SSL_REDIRECT=True` как в реальном settings.py:206; settings_test выставляет False и даёт лишний W008):
```
ckeditor.W001 (CKEditor 4.22.1 unsupported)
security.W009 SECRET_KEY ... prefixed with 'django-insecure-'
security.W012 SESSION_COOKIE_SECURE not True
security.W016 CSRF_COOKIE_SECURE not True
security.W018 DEBUG True in deployment
System check identified 5 issues
```
(settings.py:32, 35; SESSION_/CSRF_COOKIE_SECURE в settings.py не заданы.)

`migrate` на пустой SQLite: все миграции (app 0001-0009, contenttypes, auth, admin, sessions, sites) `OK`, 0.4 с. Миграция 0007 на пустой БД проходит.

`collectstatic --noinput` → `1403 static files copied to '…/static_out', 3599 post-processed.` Ошибок манифеста нет (`staticfiles.json` version 1.1, 1403 путей, все `img/*` включены). `git status staticfiles` не изменился.

Проверка ссылок (`python docs/prod-readiness/scripts/i_static_refs.py`):
```
templates/base.html:11 static 'img/logo.svg' -> img/logo.5591e6e7feff.svg
templates/base.html:12 static 'style.css'    -> style.eeac1d0aa4a7.css
templates/base.html:19, :78 static 'img/logo.svg' OK
static/style.css:25 url(img/dark-theme-icon.svg) exists=True ; :43 light-theme-icon.svg ; :251 gradient.png
refs checked: 7, missing: 0
```
Все `{% static %}` (4 шт., только base.html) и `url()` в `static/style.css` (3 шт.) резолвятся; `{% static %}` на несуществующие пути — нет. Относительные `url(img/...)` в CSS при collectstatic переписаны на хешированные.

**Находка:** `bg.png` НЕ через `{% static %}`: `templates/index.html:10` и `templates/category.html:19` (inline `<style>`): `background: url('/static/img/bg.png')`. Манифест это не переписывает; в отрендеренном `/` — `background: url('/static/img/bg.png')` (нехешированный). Работает, пока нехешированная копия лежит в STATIC_ROOT (лежит, `bg.png` 969949 байт), но отдаётся с `Cache-Control: max-age=60` (см. п.4), а не `immutable` → файл ~1 МБ перепроверяется раз в минуту. 404 нет.
`app/models.py:19,80` `default='card-example.png'` — это путь для DEFAULT_FILE_STORAGE (Cloudinary), а не static: `img/card-example.png` в static существует, но `article.image.url` для default указывает на Cloudinary media. Какой URL реально строится — не проверял (нужна сеть/конфиг Cloudinary).

## 3. Поведение при отсутствии переменных окружения и DEBUG

`python -c "import anarchia.settings"` с 5 из 6 переменных (одну по очереди убирал; `env -u … `, остальные = dummy):

| Нет переменной | Результат | Место |
|---|---|---|
| (все есть) | `import OK` | |
| `DATABASE_URL` | `KeyError: 'DATABASE_URL'` | settings.py:106 |
| `DATABASE_NAME` | `KeyError: 'DATABASE_NAME'` | settings.py:111 |
| `DATABASE_USER` | `KeyError: 'DATABASE_USER'` | settings.py:112 |
| `DATABASE_PASSWORD` | `KeyError: 'DATABASE_PASSWORD'` | settings.py:113 |
| `DATABASE_HOST` | `KeyError: 'DATABASE_HOST'` | settings.py:114 |
| `CLOUDINARY_SECRET` | `KeyError: 'CLOUDINARY_SECRET'` | settings.py:187 |

Во всех случаях голый `KeyError: '<NAME>'` из `os.environ[...]` (traceback указывает строку, пояснения «какая настройка не задана» нет; `ImproperlyConfigured` не используется).

Взаимодействие `DATABASE_URL` и `DATABASE_*` (реальный `anarchia.settings`, `django_heroku.settings(locals())` на строке 179, `django_heroku/core.py:65-69`):
```
DATABASE_URL=mysql://u:p@dbhost:3306/dbname DATABASE_NAME=envname DATABASE_HOST=envhost ...
-> ENGINE django.db.backends.mysql, NAME dbname, HOST dbhost, PORT 3306, OPTIONS {}
```
То есть при заданном `DATABASE_URL` блок `DATABASES` из settings.py:108-120 полностью заменяется `dj_database_url.config(conn_max_age=600, ssl_require=True)`; значения `DATABASE_NAME/USER/PASSWORD/HOST` игнорируются (но обязаны быть заданы, иначе KeyError), `OPTIONS.init_command="SET sql_mode='STRICT_TRANS_TABLES'"` **теряется** (OPTIONS пуст), а `sslmode`, добавленный `ssl_require=True`, удаляется строкой settings.py:180 (`del ...['sslmode']`; при его отсутствии был бы KeyError, но dj-database-url 2.1.0 добавляет его для любой схемы, в т.ч. mysql://). Какой именно URL стоит в проде — неизвестно.

`django_heroku.settings()` ещё: `ALLOWED_HOSTS = ['*']` (core.py:106) — перезаписывает список хостов из settings.py:37; проверено `ALLOWED_HOSTS ['*']` в реальном settings; `SECRET_KEY` берётся из env `SECRET_KEY`, если задан (core.py:146-149; проверено `SECRET_KEY from env: True`), иначе остаётся захардкоженный `django-insecure-…`.

**DEBUG:** `DEBUG = True` литерально (settings.py:35); env не читается. Проверка: `DEBUG=0 DJANGO_DEBUG=False … import anarchia.settings` → `DEBUG True`. Для сравнения использована обёртка `WRAP_DEBUG=0/1`.

Ответы gunicorn (1 воркер), `S/probe_w1_d0.txt`, `S/probe_w1_d1.txt`:

| URL | DEBUG=False | DEBUG=True |
|---|---|---|
| `/no-such-page` | 404, 179 байт, text/html (дефолтный минимальный Django, шаблона 404.html нет: в `templates/` нет 404/500) | 404, **6269 байт** (технический debug-экран) |
| `/about-us` (пустая БД → `DoesNotExist`, views.py:38) | 500, 145 байт | 500, **62057 байт** debug-страница с трейсбеком/настройками |
| `/static/missing.css` | 404, 179 | 404, 6439 |
| `/media/test.txt` | **404** (urls.py:68-70 раздают media/static только при DEBUG) | 200 `text/plain` (Django `static()`) |
| `/static/style.css` | WhiteNoise из STATIC_ROOT | WhiteNoise из finders, `Cache-Control: max-age=0`, без gzip |

**Логирование ошибок при DEBUG=False:** лог gunicorn (`S/gunicorn_w1_d0.log`) после 500 на `/about-us` содержит только `[INFO] Starting/Booting/Handling signal` — **ни строки об ошибке, ни трейсбека**. При DEBUG=True (`S/gunicorn_w1_d1.log`) в stderr есть `Internal Server Error: /about-us` + полный traceback. Причина (проверено): у логгера `django` два обработчика — `StreamHandler` с фильтром `RequireDebugTrue` и `AdminEmailHandler` с `RequireDebugFalse` при `ADMINS == []`. Т.е. в проде (после включения DEBUG=False) 500 были бы «немыми».

## 4. gunicorn 21.2.0, 1 и 4 воркера, 127.0.0.1:8123 (скрипт `i_gunicorn_probe.sh`)

Запуск: `gunicorn anarchia.wsgi -b 127.0.0.1:8123 -w {1|4}`, DEBUG=False, SQLite после migrate, STATIC_ROOT после collectstatic. Вывод для `-w 1` и `-w 4` идентичен (за вычетом cookie/Date/ETag). Все процессы остановлены (`pgrep gunicorn` пусто).

- `/` → 200, 9508 байт, `Vary: Cookie, Accept-Language`, `Content-Language: ua`, `Set-Cookie: csrftoken=…; SameSite=Lax` (без `Secure`). HTML ссылается на `/static/style.eeac1d0aa4a7.css` и `/static/img/logo.5591e6e7feff.svg` (хешированные).
- `/static/style.css` (нехешированный) → 200, `Cache-Control: max-age=60, public`, 16508 байт; с `Accept-Encoding: gzip` → `Content-Encoding: gzip`, 3538 байт (WhiteNoise берёт `.gz`).
- `/static/style.eeac1d0aa4a7.css` (хешированный) → `Cache-Control: max-age=315360000, public, immutable`, gzip.
- `/static/img/bg.png` → `max-age=60, public`, 969949 байт.
- `/media/test.txt` → 404 (см. п.3).
- `/robots.txt` → 404. `/healthz` → 404 (маршрутов нет, `anarchia/urls.py`).
- `/no-such-page`, `/article/does-not-exist/` → 404.
- Заголовки безопасности (HTTP, без X-Forwarded-Proto): `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy: same-origin`. С `X-Forwarded-Proto: https` добавляется `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (settings.py:208-211). CSP нет. `csrftoken` cookie без `Secure` (CSRF_COOKIE_SECURE не задан); сессии `signed_cookies` (settings.py:218), SESSION_COOKIE_SECURE не задан.
- Нагрузка-дым: 200 GET `/` при `-P8`, 4 воркера: 200×200, 0.39 с (`xargs curl`).
- Два `WhiteNoiseMiddleware` в `MIDDLEWARE`: settings.py:70 (последним) и перед `SecurityMiddleware` — вставлен `django_heroku` (core.py:95-98), всего 2 (проверено `whitenoise count 2`); работает первый, второй — лишний.
- Запуск `-w 4` — без ошибок в логе, все 4 воркера `Booting worker`.

**Гипотеза 12 (LocMemCache + несколько воркеров) — подтверждена** (`i_menu_cache_workers.py`): прогрев `/` 60 запросами, затем `POST /create-category/` под залогиненным `probeadmin` (создан только в scratch-БД), затем 60 анонимных GET `/` и подсчёт, в скольких есть новая категория:
```
workers=4: create_category status 302 ; 8/60 show new category ; YYYYY....................................................YYY
workers=1: create_category status 302 ; 60/60 show new category
```
При 4 воркерах после изменения меню остальные воркеры держат старый фрагмент (`{% cache 3600 …%}` base.html:27, :87; `invalidate_menu_cache` в `app/menu_cache.py` чистит только локальный LocMemCache процесса) — до 3600 с. Сид-данных в scratch-БД нет, поэтому «`/` → 200» проверено без статей.

Gunicorn-дефолты без флагов (`gunicorn --print-config`): `worker_class=sync, workers=1 (WEB_CONCURRENCY=3 переопределяет → 3), threads=1, timeout=30, graceful_timeout=30, keepalive=2, preload_app=False, max_requests=0, accesslog=None, errorlog=-`. Access-лог отключён по умолчанию.

## 5. Procfile / runtime.txt / Aptfile

- `Procfile:1` `web: gunicorn anarchia.wsgi` — единственный процесс; **нет `release:`** (migrate вручную), нет `--workers/--threads/--timeout/--preload/--access-logfile`, нет процесса для `app/management/commands/publish_articles.py` (в репозитории вызывающего нет: ни `clock`/`worker` процесса, ни cron/scheduler-конфига).
- `runtime.txt:1` `python-3.13.7`. Что делает 3.13 с Django 4.2.4: в метаданных пакета (`Django-4.2.4.dist-info/METADATA`) классификаторы только Python 3.8–3.11 (`Requires-Python: >=3.8`), т.е. 3.13 официально не заявлена. **Реально падающего нет:** `python manage.py test app.test_findings` под 3.13.7 → `Ran 24 tests in 0.795s OK` (2 `RemovedInDjango51Warning` о `DEFAULT_FILE_STORAGE`/`STATICFILES_STORAGE`); `check`, `migrate`, `collectstatic`, gunicorn, логин и POST `/create-category/` в `i_menu_cache_workers.py` работают (multipart-загрузка не проверялась). В Django/ckeditor/cloudinary/captcha/whitenoise/gunicorn/pymysql нет импортов удалённых в 3.13 модулей (`cgi`, `crypt`, `imghdr`, `telnetlib`, `pipes`… — grep пуст). Единственная реальная несовместимость 3.13 — `python-firebase` (п.1), но он не импортируется.
- `Aptfile:1-4`: `libjpeg-dev libpng-dev zlib1g-dev libmysqlclient-dev`. `libmysqlclient-dev` нужен только для сборки `mysqlclient` (бессмысленной при `pymysql.install_as_MySQLdb()`, п.1). Aptfile работает только если подключён `heroku-buildpack-apt` — из репозитория не определить.

## 6. Логирование / мониторинг

Проверено `grep -rniE "sentry|ADMINS|MANAGERS|LOGGING|logging\.|getLogger|healthz|health" anarchia app/*.py app/management manage.py requirements.txt Procfile` (исключая тесты): **ни одного совпадения**. В `requirements.txt` нет sentry-sdk.
- `LOGGING` в settings.py отсутствует; его выставляет `django_heroku.settings()` (core.py:108-141): handlers `null`, `console` (formatter verbose) и единственный логгер `testlogger` (INFO). Ни `django`, ни `django.request`, ни `app` в нём нет → эффективно действует дефолт Django (см. п.3: при DEBUG=False ошибки не пишутся нигде).
- `ADMINS = []`, `EMAIL_BACKEND = smtp`, `SERVER_EMAIL = root@localhost`; `mail_admins` неработоспособен, EMAIL_* настроек нет.
- Health-check: маршрута нет (`/healthz` → 404), `/` ходит в БД и кэш. Sentry/APM: нет. `print`/`logger` в `app/*.py` не используются.
- Heroku-уровень (router-логи, метрики, алерты) из репозитория не виден.

## Не удалось проверить и почему

1. Реальная сборка на Heroku (buildpack, наличие `libpq-dev`/`libmysqlclient-dev`, поддержка `python-3.13.7`, `runtime.txt` vs `.python-version`, автозапуск `collectstatic` при деплое) — запрещены запросы к Heroku; локально нет pg_config/mysql_config/pkg-config.
2. Сборка `mysqlclient` и `psycopg2` на этой машине — не удалась (причины выше); `mysqlclient` и без того не импортируется (замещён PyMySQL), `psycopg2-binary` не ставил.
3. Работа с настоящей MySQL (strict mode, потеря `init_command` при `DATABASE_URL` — показана только на уровне собранного `DATABASES`; соединений нет), тип схемы реального `DATABASE_URL` в проде.
4. Cloudinary (`DEFAULT_FILE_STORAGE`): `.url`, загрузка и URL для `default='card-example.png'` — нужна сеть/секрет; тесты идут на FileSystemStorage.
5. reCAPTCHA siteverify, шрифты/CKEditor CDN — внешние сети.
6. Наличие Heroku Scheduler для `publish_articles` и настройки config vars на проде (в т.ч. `SECRET_KEY`, `DATABASE_URL`) — не в репозитории.
7. Поведение под реальной нагрузкой и с данными (БД пуста, статей нет): время ответа/память воркеров не мерялись; `timeout=30` и таймауты внешних вызовов под нагрузкой не воспроизводились.
8. Время `collectstatic` не замерялось (завершился без ошибок).
