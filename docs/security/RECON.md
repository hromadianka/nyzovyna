# Фаза 1. Разведка: карта приложения «Низовина»

Источник: чтение кода (`app/*`, `anarchia/*`, `templates/*`, `requirements.txt`, `Procfile`, `.gitignore`, миграции, management-команда, `static/`). Код не менялся.

Особенности, влияющие на всё остальное:

- Модель `Editor` **нигде не используется** во вью (`grep Editor app/views.py` — только импорт). Права редактора = «любой залогиненный».
- `anarchia/settings.py` в `.gitignore`, но закоммичен; `django_heroku.settings(locals())` (settings.py:179) **перезаписывает** `ALLOWED_HOSTS` на `['*']`.
- В `static/` только `style.css`: собственного JS нет, весь JS инлайновый в шаблонах (вывод в разделе 3).
- Нет маршрутов регистрации, выхода и смены пароля: аккаунты создаются только через `/admin/`.

## 1. Маршруты, права и входные данные

| # | URL | Вью | Методы | Доступ | Входные данные | Запись в БД |
|---|-----|-----|--------|--------|----------------|-------------|
| 1 | `/admin/` | Django admin | GET/POST | staff | формы админки | любая модель |
| 2 | `/sitemap.xml` | sitemap | GET | публично | – | – |
| 3 | `/ckeditor/upload/` | ckeditor_uploader (`csrf_exempt`) | POST | staff | multipart `upload`, `?CKEditorFuncNum`, `?responseType` | файл в storage |
| 4 | `/ckeditor/browse/` | ckeditor_uploader | GET | staff | – | – |
| 5 | `/set-language/` | `django.views.i18n.set_language` | POST | публично | `language`, `next` | cookie `django_language` |
| 6 | `/` | `index` | GET | публично | – | – |
| 7 | `/about-us` | `about_us` | GET | публично | – | – |
| 8 | `/authors`, `/authors/<slug>` | `authors`, `author_detail` | GET | публично | slug (path) | – |
| 9 | `/authors/<slug>/edit` | `edit_author` | GET, POST | login | `name_ua/en`, `description_ua/en`, файл `author_image` | `Author` |
| 10 | `/all`, `/category/<slug>/` | `all_articles`, `category_articles` | GET | публично | slug | – |
| 11 | `/category/<slug>/delete/` | `delete_category` | **GET удаляет** | login | slug | DELETE `Category` (+каскад) |
| 12 | `/article/<slug>/` | `article_detail` | GET | публично | slug | `Article.views += 1` на каждый GET |
| 13 | `/article/<uuid>/` | `article_detail` (не принимает `id`) | GET | – | – | недостижим: UUID совпадает со `slug`-конвертером, маршрут №12 перехватывает |
| 14 | `/comment` | `comment` | POST (GET → redirect) | публично | `article_id`, `parent_comment_id`, `author`, `text`, reCAPTCHA | INSERT `Comment` |
| 15 | `/login/` | `user_login` | GET, POST | публично | `login`, `password` | сессия |
| 16 | `/editor-cabinet` | `editor_cabinet` | GET | login | – | – |
| 17 | `/publish` | `publish` | GET, POST | login | `article_name`, `article_text`, `article_image`(файл), `language`, `categories[]`, `article_author`, `publish_option`, `publish_datetime`, `article_slug` | INSERT `Article`, M2M |
| 18 | `/article/<slug>/edit/` | `edit_article` | GET, POST | login | те же поля | UPDATE `Article` |
| 19 | `/article/<slug>/delete/` | `delete_article` | **GET удаляет** | login | slug | DELETE `Article` |
| 20 | `/create-category/` | `create_category` | POST | login | `name_ua`, `name_en`, `parent_id` | INSERT `Category` |
| 21 | `/about-us-edit` | `about_us_edit` | POST (GET → 500) | login | `new_text_ua`, `new_text_en` | UPDATE `AboutUsText` |
| 22 | `/create_new_author/` | `create_new_author` | POST | login | `author_name_*`, `author_description_*`, файл | INSERT `Author` |
| 23 | `/feed/` | `LatestPostsFeed` | GET | публично | – | – |
| 24 | `/search/` | `article_search` | GET | публично | `q` | – |
| 25 | `/editor-cabinet/comments-moderation/` | `comments_moderation` | GET | login | – | – |
| 26 | `…/comments-moderation/<uuid>/delete/` | `delete_comment` | POST (`require_POST`) | login | uuid | DELETE `Comment` |
| 27 | `/editor-cabinet/categories/order/` | `category_order_editor` | GET | login (без `login_url`) | – | – |
| 28 | `…/categories/order/update/` | `update_category_order` | POST JSON | login (без `login_url`) | тело: `[{"id","order"}]` без валидации | UPDATE `Category.order` ×N |
| 29 | `/static/`, `/media/` | `static()` | GET | только при `DEBUG=True` (в проде он True) | путь | – |

Редиректы на логин: вью с `login_url='/login'` ведут на `/login` (→ 301 → `/login/`); `category_order_editor` и `update_category_order` используют `@login_required` без аргумента и ведут на `/accounts/login/`, которого нет (404).

## 2. Места вывода пользовательских данных

| Поле | Где выводится | Экранирование |
|------|---------------|---------------|
| `Article.text` (RichTextField, HTML) | `article.html:64` | **нет**: `{% autoescape off %}…|safe` |
| `Article.text` | карточки: `index.html:55,96,144,185`, `category.html:46,71`, `search.html:24,43`, `author_detail.html:50,75`, `editor-cabinet.html:230,280`, `article.html:97,108` | `autoescape off` + `|linebreaks|striptags|truncatechars` (защита только `striptags`) |
| `Article.text` | RSS `feeds.py:20` (`item_description`) | XML-экранирование, но получатель трактует как HTML |
| `<oembed url>` внутри `Article.text` | `article.html:182-194`: JS создаёт `iframe.src = url` | DOM-sink без проверки схемы |
| `AboutUsText.text_ua/en` | `about-us.html:10,12` | **нет**: `autoescape off` |
| `Article.name`, `Author.*`, `Category.name_*`, `Comment.author/text` | остальные шаблоны | автоэкранирование |
| `request.path` | `base.html:47` (`<input value>`) | автоэкранирование |
| `q` | `base.html:101` (`value="{{ query }}"`) | автоэкранирование |
| `image.url` | `style="background: url('{{ … }}')"` в `article.html:51,70,93,104`, `search.html:15` и др. | автоэкранирование; имена файлов чистит storage |
| `comment.id`, `category.id`, `article.slug` | inline JS: `article.html:127`, `comment.html:12`, `editor-cabinet.html:153,155,235,287`, `recursive_list.html:5` | UUID / slug-символы, но контекст JS-строки |
| `{{ csrf_token }}` | `category_order.html:103` в JS | токен |
| внешние ресурсы | `base.html:13` (cdnfonts), `base.html:14` (cdn.ckeditor.com ckeditor5@39.0.1 на **каждой** странице), `category_order.html:70` (jsdelivr Sortable), `settings.py:195` (googleapis jQuery 2.1.1) | без `integrity=` |

`mark_safe`, `format_html`, `.raw()`, `.extra()`, `cursor()` в коде проекта не встречаются.

## 3. Матрица «эндпоинт × угроза»

Обозначения: ✖ подтверждено красным тестом (ID находки), ✔ проверено, безопасно, – не применимо.

| Эндпоинт | CSRF | XSS | Доступ / IDOR | Инъекции / валидация | Файлы | Rate limiting | Раскрытие информации |
|----------|------|-----|---------------|----------------------|-------|---------------|----------------------|
| `/login/` | ✔ | ✔ | – | ✔ SQLi; ✔ мусор | – | ✖ NYZ-011 | ✔ нет enumeration |
| `/admin/login/` | ✔ | – | – | – | – | ✖ NYZ-011 | – |
| `/comment` | ✔ | ✔ | ✖ NYZ-006 (ответ к чужой ветке, капча) | ✖ NYZ-013 (500, нет длин) | – | ✖ NYZ-006 | ✖ NYZ-007 (черновики) |
| `/article/<slug>/` | – | ✖ NYZ-003 | ✖ NYZ-007 | ✔ SQLi | – | ✖ NYZ-016 (views) | ✖ NYZ-007 |
| `/` `/all` `/category/` `/authors/<slug>` | – | ✔ (`striptags`) | ✖ NYZ-007 (отложенные) | ✔ | – | – | ✖ NYZ-007 |
| `/search/` | – | ✔ | ✔ черновики скрыты | ✔ SQLi/ReDoS | – | ✖ NYZ-016 | ✔ |
| `/feed/`, `/sitemap.xml` | – | ✖ NYZ-003 (RSS) | ✔ черновики скрыты | ✔ | – | – | ✔ |
| `/about-us` | – | ✖ NYZ-003 | – | ✖ NYZ-013 (500 без строки) | – | – | – |
| `/set-language/` | ✔ | – | – | ✔ | – | – | ✖ NYZ-009 (Host) |
| `/editor-cabinet`, `/publish`, `/article/<slug>/edit/`, `/authors/<slug>/edit`, `/create-category/`, `/create_new_author/`, `/about-us-edit`, `/comments-moderation/`, `…/delete/` | ✔ POST | ✖ NYZ-003 (хранение) | ✖ NYZ-004 | ✖ NYZ-013 | ✖ NYZ-014 | – | ✖ NYZ-008 (DEBUG) |
| `/article/<slug>/delete/`, `/category/<slug>/delete/` | ✖ NYZ-005 (GET) | – | ✖ NYZ-004 | ✖ NYZ-013 (POST → 500) | – | – | – |
| `/…/categories/order/`, `…/update/` | ✔ | – | ✖ NYZ-004; ✖ NYZ-017 (логин-редирект 404) | ✖ NYZ-013, NYZ-016 | – | ✖ NYZ-016 (N запросов) | – |
| `/ckeditor/upload/` | ✖ NYZ-015 (`csrf_exempt`) | – | ✔ только staff | – | ✖ NYZ-015 | – | – |
| `/ckeditor/browse/`, `/admin/` | ✔ | – | ✔ аноним → 302 | – | – | – | – |
| глобально (все страницы) | – | ✖ NYZ-018 (нет CSP) | – | – | – | – | ✖ NYZ-008, NYZ-009 |
| глубокие данные: меню (категории), комментарии, циклы | – | – | – | – | – | – | ✖ NYZ-010 (отказ в обслуживании), ✖ NYZ-012 (кириллица → пустой slug → 500 на всех страницах) |
