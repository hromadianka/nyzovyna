# Низовина — инвентаризация (Фаза 1)

Код не менялся. Всё, что помечено «проба», воспроизведено скриптом вне репозитория на SQLite in-memory (`anarchia.settings_test`). Статус «гипотеза» — ещё не покрыто тестом, красный тест будет в Фазе 2.

## 1. Карта маршрутов

Права: `—` публично, `login` = `@login_required` (редирект на /login), `login*` = `@login_required` без `login_url`, уйдёт на `/accounts/login/` (в проекте нет такого маршрута → 404).

| URL | Имя | Методы (фактически) | Права | Шаблон | Модели | Внешнее |
|---|---|---|---|---|---|---|
| `/` | home | любой (нет ограничений) | — | index.html | Article, Category(menu) | БД, кэш, Cloudinary (image.url), CDN |
| `/about-us` | about_us | GET | — | about-us.html | AboutUsText(pk=1) | БД |
| `/authors` | authors | GET | — | authors.html | Author | Cloudinary |
| `/authors/<slug>` | author_detail | GET | — | author_detail.html | Author, Article | Cloudinary |
| `/authors/<slug>/edit` | edit_author | GET, POST | login | edit_author.html | Author | Cloudinary (upload) |
| `/all` | all_articles | GET | — | category.html | Article | Cloudinary |
| `/category/<slug>/` | category_articles | GET | — | category.html | Category, Article | Cloudinary |
| `/category/<slug>/delete/` | delete_category | **GET удаляет** | login | JSON | Category (+каскад) | — |
| `/article/<slug>/` | article | GET (HEAD/prefetch тоже считаются) | — | article.html, comment.html | Article, Comment, Category | reCAPTCHA (виджет), Cloudinary |
| `/article/<uuid>/` | article_by_id | недостижим: `slug`-конвертер перехватывает UUID раньше (проба: 404) | — | — | — | — |
| `/comment` | comment | POST (GET → redirect `/`) | — | redirect | Comment | reCAPTCHA siteverify (сеть) |
| `/login/` | login | GET, POST | — | login.html | User | — |
| `/editor-cabinet` | editor_cabinet | GET | login | editor-cabinet.html | Article, AboutUsText(pk=1), Author | — |
| `/publish` | publish | GET, POST (multipart) | login | editor-cabinet.html | Article, Author, Category | Cloudinary (upload) |
| `/article/<slug>/delete/` | delete | **GET удаляет** | login | JSON | Article (+comments) | — |
| `/article/<slug>/edit/` | edit_article | GET, POST | login | edit_article.html | Article, M2M | Cloudinary |
| `/create-category/` | create_category | POST | login | redirect | Category | — |
| `/about-us-edit` | about_us_edit | POST (GET → None → 500) | login | redirect | AboutUsText | — |
| `/create_new_author/` | create_new_author | POST | login | redirect | Author | Cloudinary |
| `/feed/` | post_feed | GET | — | RSS | Article | — |
| `/search/` | article_search | GET | — | search.html | Article | — |
| `/editor-cabinet/comments-moderation/` | comments_moderation | GET | login | comments_moderation.html | Comment | — |
| `/editor-cabinet/comments-moderation/<uuid>/delete/` | delete_comment | POST | login | redirect | Comment | — |
| `/editor-cabinet/categories/order/` | category_order_editor | GET | login* | category_order.html | Category | — |
| `/editor-cabinet/categories/order/update/` | update_category_order | POST (json.loads без валидации) | login* | JSON | Category | — |
| `/set-language/` | set_language | POST | — | redirect | сессия/cookie | — |
| `/sitemap.xml` | sitemap | GET | — | XML | Article, Author, AboutUsText | — |
| `/admin/`, `/ckeditor/...` | — | — | staff | — | все | — |
| `robots.txt`, `/healthz` | **нет** | — | — | — | — | — |

Шаблоны вне маршрутов (мёртвый код): `recursive_list.html` (используется только `editor-cabinet.html`, проверить), `comment.html` (рекурсивный include, используется), `category_order.html`.

## 2. Внешние зависимости

| Зависимость | Где | Если упадёт |
|---|---|---|
| MySQL (PyMySQL) | все вью, `DATABASE_*` env (5 переменных, `DATABASE_URL` читается, но `django_heroku` перезаписывает DATABASES) | 500 на всём сайте |
| LocMemCache | `{% cache %}` меню/футер, ключи по языку | кэш на процесс; после рестарта холодный старт; инвалидация сигналом работает только в том процессе, где был save |
| Cloudinary | `DEFAULT_FILE_STORAGE`; `.url` у каждой карточки | `.url` строится локально (без сети), но загрузка при publish/edit — сетевой вызов, без таймаута/обработки |
| reCAPTCHA | `CommentCaptchaForm`, siteverify на каждый корневой комментарий | синхронный HTTP внутри запроса; недоступность → форма невалидна, комментарий молча теряется (redirect без ошибки) |
| CDN fonts.cdnfonts.com | base.html `<link>` | шрифт не грузится (render-blocking CSS) |
| CDN cdn.ckeditor.com (CKEditor 5 39.0.1) | base.html `<script>` на КАЖДОЙ странице | блокирует рендер; на публичных страницах не используется нигде (grep `ClassicEditor` — проверить в Фазе 2) |
| ajax.googleapis.com jQuery | `CKEDITOR_JQUERY_URL` | редактор админки |
| WhiteNoise манифест | `CompressedManifestStaticFilesStorage` | отсутствующий в манифесте файл → `ValueError` на рендер шаблона → 500 |

## 3. Единые точки отказа и «работает, пока не сломается»

1. **Пустой slug у категории/автора = 500 на ВСЕХ страницах.** Проба: `Category(name_ua='Політика')` → `slug=''`, следующая `'-1'`; `{% url 'category_articles' category.slug %}` в меню → `NoReverseMatch`; `/` вернул 500 сразу после создания такой категории. Автор с кириллическим `name_en`: slug `''` → `/authors` 500. Путь «Редактор → создать категорию» (create_category, `name_ua` на украинском) приводит к этому штатно.
2. `AboutUsText.objects.get(pk=1)`: `/about-us` и `/editor-cabinet` дают 500 на пустой БД (проба).
3. Нет `robots.txt`, `/healthz`, LOGGING, Sentry. `DEBUG = True` захардкожен в settings.py; `django_heroku` его не переопределяет → в проде показываются трейсбеки (влияет на надёжность: утечка, нагрузка, ответ 500 с мегабайтным HTML).
4. LocMemCache + несколько воркеров: инвалидация меню (`invalidate_menu_cache`) чистит кэш только своего процесса; остальные воркеры держат старое меню до 3600 с.
5. Procfile без `release:` (миграции вручную), без `--workers/--threads/--timeout`, без `--preload`.
6. Планировщик публикаций: `app/management/commands/publish_articles.py` существует, но **вызывающего нет** (Procfile — только `web`; нет Heroku Scheduler в репозитории, нет cron). Гипотеза 5 подтверждается частично: команда есть, автозапуска в репозитории нет. Остаётся неизвестным, настроен ли Heroku Scheduler вне репозитория — не проверяемо локально.
7. Загрузка картинок: `create_new_author` передаёт `image=None` → в БД `''` (проба: `image.name == ''`); `authors.html` страхуется `{% if author.image %}`, но `index/category/search/article` вызывают `article.image.url` безусловно.

## 4. Предварительные наблюдения по гипотезам (проба или чтение кода)

| № | Статус | Основание |
|---|---|---|
| 1 | не проверено (нет MySQL) | Docker daemon не запущен; нужен локальный MySQL. Уже видно: `max_length=200` у slug, `Author.slug` 100 при `name_en` 100 — на SQLite длину не контролируют; проба: slug статьи 405 символов сохраняется на SQLite (на MySQL strict → DataError) |
| 2 | частично опровергнута | slug существующей статьи при save **не меняется**, если не очищен (models.py Article.save: `base_source = self.slug or self.name`). Подтверждено: кириллица → `'article'`, `'article-1'`; длинное имя → slug 405 > max_length |
| 3 | подтверждена, критично | см. п.1 раздела 3 |
| 4 | подтверждена | проба: about_us 500, cabinet 500 |
| 5 | подтверждена частично | см. п.6 раздела 3 |
| 6 | частично опровергнута | `locale/ua` и `locale/en` существуют (25 msgid каждый); `get_language_info('ua')` → `KeyError` (проба); `Content-Language: ua` отдаётся (невалидный BCP-47, правильно `uk`) |
| 7 | подтверждена и шире | `id="ticker"` и `.ticker` не существуют ни в одном шаблоне и CSS; `getElementById("ticker").addEventListener` и `ticker.style` бросают TypeError на **каждой** странице. `themeToggle` есть только в article.html → на остальных страницах первый inline-скрипт падает |
| 8 | подтверждена кодом | `category_articles`, `all_articles`, `article_search`, `authors`, `author_detail` — без `Paginator`/слайса |
| 9 | подтверждена кодом | `text__icontains` по HTML, без `order_by`; шаблон делает `{% for ... reversed %}` по неупорядоченному QuerySet — порядок на MySQL не определён |
| 10 | подтверждена | проба: `HEAD` увеличил views до 1 |
| 11 | гипотеза | нужен тест с моком хранилища |
| 12 | гипотеза | нужен gunicorn -w 4 |
| 13 | гипотеза | 0006 добавляет slug (null), 0007 `fill_slugs` использует `slugify(...)` без fallback, пустой slug → коллизия `'-1'`; обратная операция отсутствует (`RunPython` без `reverse_code`, откат 0007 невозможен); 0008 → `default=0` в unique (`preserve_default=False`) затем 0009 откатывает к null |
| 14 | подтверждена | `fill_slugs.py` в корне: ручной скрипт, нигде не импортируется, при запуске обнуляет slug всем объектам (`update(slug=None)`) → ломает все внешние ссылки; `db.sqlite3` в git, `.gitignore` перечисляет `settings.py` (уже закоммичен, игнор бесполезен) |
| 15 | подтверждена и шире | `article_by_id` недостижим (shadowing); `article.html`: `{% if author.image %}` — переменной `author` в контексте нет, фото автора в статье никогда не показывается; `{% url 'author_detail' article.author.slug %}` падает при `slug=None` (поле nullable) |
| 16 | не проверено в Фазе 1 | нужен чистый env Py3.13.7 (Фаза 2, группа I) |
| 17 | подтверждена | в git: 667 файлов, из них `staticfiles/` 500+, `__pycache__` (.pyc ×40+), `.vs/`, `.idea/`, `media/`, `db.sqlite3` |

## 5. Новые находки Фазы 1 (не были в списке гипотез)

- `article_detail` отдаёт неопубликованные/отложенные статьи любому по slug (проба: 200 для `is_published=False`) и учитывает им просмотр.
- `delete_article` / `delete_category` удаляют по **GET** (проба: `draft still exists: False`), т.е. prefetch/краулер/ссылка из письма удаляет данные; для других методов вью возвращает `None` → 500.
- `index`, `category_articles`, `all_articles`, `author_detail` фильтруют только `is_published`, `article_search`/sitemap/feed ещё и `publish_at<=now()` — несогласованность.
- `edit_article`: `categories.clear()` и `add()` выполняются до `save()` и до валидации картинки; при неверном типе файла категории уже стёрты (частичная запись, нет `@transaction.atomic`).
- `comment`: нет проверок `author`/`text` (None → `IntegrityError` для `author` NOT NULL → 500), нет лимита длины (`author` max 100 → DataError на MySQL), нет проверки, что parent относится к той же статье, нет глубины.
- `update_category_order`: `json.loads(request.body)` без try → 500 на мусор; `item['id']` не UUID → `ValidationError` 500; нет атомарности.
- `about_us_edit`: GET возвращает `None` → 500 (`The view didn't return an HttpResponse`).
- `category_order_editor`/`update_category_order`: `@login_required` без `login_url` → редирект на `/accounts/login/`, которого нет → 404.
- `Category.save`/`Author.save`: проверка уникальности `exists()` + запись без блокировки — гонка при конкурентном создании.
- Sitemap: `AboutUsSitemap` и `AuthorSitemap.lastmod` возвращают `now()` — lastmod всегда «сейчас», поисковики теряют сигнал.
- Feed: `item_description` отдаёт полный HTML, `item_pubdate` = `created_at` вместо `publish_at` (отложенная статья попадёт с датой создания).
- `requirements.txt`: 15+ неиспользуемых тяжёлых пакетов (rethinkdb, Pyrebase4, gcloud, Radicale, pybind11, psycopg2, firebase, oauth2client…), `mysqlclient>=2.0` без верхней границы одновременно с PyMySQL, пины 2023 года (Pillow 12.1.0 при Django 4.2.4), Python 3.13.7 в runtime.txt при Django 4.2.4 (официально до 3.12 для 4.2.x по матрице поддержки — проверить в Фазе 2).
- Секреты в репозитории: `SECRET_KEY`, `RECAPTCHA_*`, `CLOUDINARY_STORAGE.API_KEY` захардкожены (передано в отдельный аудит безопасности; здесь важно как риск эксплуатации: ротация потребует деплоя).

## 6. Состояние инструментов для Фазы 2

| Нужно | Статус |
|---|---|
| Python 3.11 (conda `nyz`), Django 4.2.4, ckeditor, cloudinary-storage, recaptcha, PyMySQL | есть |
| hypothesis, coverage, ruff/flake8, bandit, vulture, radon, mutmut, feedparser, pip-audit, deptry, djlint, mypy, locust, playwright | **нет**, ставить в `nyz` |
| Docker / MySQL | Docker-клиент есть, **daemon не запущен** → группа MySQL заблокирована, пока вы его не запустите |
| wrk, k6 | нет (locust через pip) |
| Node/npx | есть (Playwright, Lighthouse, axe) |
| Python 3.13.7 env `nyz-py313` | отсутствует, надо создать |
