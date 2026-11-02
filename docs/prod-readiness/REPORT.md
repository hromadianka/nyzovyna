# Низовина (nyzovyna) — готовность к боевой нагрузке

Аудит: QA/SRE, только локально (localhost, SQLite, Docker MySQL 8.0). Боевой код не менялся.
База аудита: коммит `a240822` (состояние репозитория на старте), окружение — Python 3.13.7 + Django 4.2.4 + пины из `requirements.txt` (conda `nyz-py313`, из них не ставились `psycopg2` и `mysqlclient`: не собираются).

> **Оговорка о воспроизводимости.** Во время аудита параллельный аудит безопасности менял боевой код, коммитил (HEAD ушёл с `a240822` на `508ddfd`) и обновил общее окружение `nyz` до Django 5.2.18. Поэтому все числа ниже получены на снимке `a240822` (`git worktree`) в окружении с пинами из requirements. Числа текущего HEAD не мерились. После исправлений их надо переснять теми же скриптами (`docs/prod-readiness/scripts/`).

> **Статус после Фазы 4 (2026-11-02).** Все 7 блокирующих и все важные находки закрыты (раздел 16): 34 коммита, на SQLite и MySQL 1200 тестов без красных (29 пропущены как MySQL-only, 14 — «известно открытые» из набора безопасности). Вердикт ниже описывает состояние до исправлений.

## 1. Вердикт

**НЕ ГОТОВ в текущем виде. Путь к «готов с условиями» — закрыть 7 блокирующих находок (≈1 рабочий день, см. раздел 3).**

| Класс | Кол-во | Что это |
|---|---|---|
| Блокирующие | 7 | P-01, P-02, P-09, P-10, P-27, P-34, P-40 |
| Важные | 29 | ошибки данных, 500 на невалидный ввод, отсутствие пагинации и индексов, N+1 в кабинете, JS-ошибки, SEO/a11y/i18n, зависимости |
| Желательные | 18 | косметика, согласованность, гигиена репозитория |

Почему не готов:
1. **Редактор может положить весь сайт одним действием.** Категория с украинским названием получает пустой slug, меню падает с `NoReverseMatch`, и все страницы отдают 500 (P-01). То же с автором (P-02).
2. **Эмодзи в комментарии, заголовке или поиске дают 500 на MySQL.** Соединение открывается в `utf8mb3` (P-27, только с Django 4.2.4).
3. **Данные удаляются по GET** (P-10), а отложенные публикации **никто не запускает** (P-09).
4. **Нет эксплуатационного минимума:** `DEBUG=True` захардкожен, нет логирования 500, health-check, брендированных 404/500 (P-40).
5. **Кнопка «Відповісти» мертва** на всех статьях (P-34).
6. **Нагрузка:** страницы без пагинации. `/all` при 6 668 статьях — 1,4 с, 7 МБ HTML, пик памяти 351 МБ. Sitemap — 414 МБ, это риск R14 на dyno 512 МБ (раздел 5).

## 2. Что сделано

| | |
|---|---|
| Тесты (`prod_tests/`, 12 модулей) | **558 методов** + 24 прежних из `test_findings.py` = **582 теста** (28 помечены skip на SQLite: MySQL-only). Параметризация через `subTest`, hypothesis (`derandomize=True`), детерминированные данные |
| Красные (подтверждённые проблемы) | SQLite: **224 метода / 291 красный подтест**. MySQL: **238 методов / 297 подтестов**. Группируются в **54 находки** (раздел 4) |
| Зелёные | 358 (SQLite) / 344 (MySQL): в том числе 14 регрессионных замков на уже исправленные проблемы (`test_regressions.py`) |
| Покрытие `app/` | **97,3 % строк, 95,9 % ветвей** (521 стейтмент, 98 ветвей); цель ≥85 / ≥75 выполнена. Непокрыто: `views.py` 240, 355-356, 361-362, 395→398; `templatetags/app_tags.py` (мёртвый код) |
| Мутационное тестирование | 139 AST-мутантов (`views.py`, `models.py`, `context_processors.py`): **132 убито (95,0 %)**, 7 выжили. Ещё один из 7 ловится только текущим красным тестом (строка 297). Подробности в разделе 6 |
| Нагрузка | 10 000 статей / 500 категорий / 50 000 комментариев, gunicorn + locust (раздел 5) |
| Браузеры | Chromium, Firefox, WebKit × 375/768/1440, Lighthouse, axe-core (раздел 7) |
| Развёртывание | чистая установка на 3.13.7, `check --deploy`, collectstatic с манифестом, gunicorn 1/4 воркера (раздел 8) |
| Статанализ | раздел 9 |

Пакет тестов по модулям (методов / красных на SQLite): A-редактор 135/66, A-публичная 93/33, B-контракты 54/17, C-данные 77/29, D-бюджеты 17/6, E-надёжность 26/13, F-фронтенд-статика 14/11, G-SEO 46/30, H-i18n 46/19, I-MySQL 21/0 (на MySQL 11), K-мутации 15/0, регрессии 14/0.

Запуск:
```
PYTHONDONTWRITEBYTECODE=1 DJANGO_SETTINGS_MODULE=anarchia.settings_test python manage.py test prod_tests            # SQLite in-memory
PYTHONDONTWRITEBYTECODE=1 NYZ_DB=mysql DJANGO_SETTINGS_MODULE=anarchia.settings_test python manage.py test prod_tests   # Docker MySQL 8.0 на 127.0.0.1:33306
```
Красный тест = найденная проблема (тест описывает желаемое поведение). Для воспроизведения любой находки запустите тест из колонки «Красных тестов».

## 3. Блокирующие находки и минимальный путь к запуску

| ID | Что | Усилие |
|---|---|---|
| P-01 / P-02 | Slug для кириллицы (транслитерация + fallback), починить уже созданные пустые slug | 3 ч |
| P-27 | `OPTIONS: {'charset': 'utf8mb4'}` (при обновлении Django ≥5 — проверить) | 15 мин |
| P-10 | Удаление только по POST с подтверждением | 1 ч |
| P-09 | Heroku Scheduler на `publish_articles` (или фильтр по `publish_at` вместо флага) | 30 мин |
| P-34 | Определить `toggleReplyForm` | 15 мин |
| P-40 | `DEBUG` из env, `LOGGING` в stdout, Sentry, `/healthz`, 404/500 | 3 ч |

Строго после «приступай» (Фаза 4): по одной находке, красный тест → зелёный, отдельный коммит.

## 4. Таблица находок

Колонка «Красных тестов (SQLite / MySQL)» — число красных тестов из группы и пример имени; это и есть доказательство. Для P-43, P-44, P-45 доказательство — измерение в `evidence/` (ссылки в разделах 5, 8). P-50 — прочтение кода.
Серьёзность: блокирующая / важная / желательная. Трудоёмкость — грубая оценка.

| ID | Группа | Серьёзность | Где | Находка | Красных тестов (SQLite / MySQL) | Рекомендация | Трудоёмкость |
|---|---|---|---|---|---|---|---|
| P-01 | C | блокирующая | app/models.py:50-58 Category.save; templates/base.html:34,43 | Категория с украинским названием получает пустой slug (`""`, затем `-1`); меню падает с NoReverseMatch, 500 на ВСЕХ страницах | 7 / 7 (напр. `test_crawl_with_cyrillic_content_finds_no_errors, test_create_category_with_cyrillic_name_has_usable_slug_and_site_survives`) | Транслитерация (unidecode/uk→lat) или slug из name_en + запрет пустого slug (fallback на uuid) | 2 ч |
| P-02 | C | блокирующая | app/models.py:25-33 Author.save | Автор с кириллическим `name_en` получает пустой slug; `/authors` и страница статьи автора — 500 (NoReverseMatch) | 3 / 3 (напр. `test_create_author_cyrillic_en_name_has_slug, test_cyrillic_english_name_has_nonempty_slug`) | Тот же генератор slug; в шаблонах не вызывать url без slug | 1 ч |
| P-03 | C | важная | app/models.py:92-103 Article.save | Украинские заголовки → slug `article`, `article-1`…: нечитаемые URL, потеря SEO | 3 / 3 (напр. `test_cyrillic_titles_get_meaningful_slugs, test_explicit_cyrillic_slug_is_not_destroyed`) | Транслитерация | 1 ч |
| P-04 | C | важная | app/models.py:25,50,92 (slug max_length 100/100/200) | Slug не усекается и суффикс `-N` не учитывается: >max_length. SQLite молчит, MySQL (STRICT) даёт DataError 500 | 6 / 7 (напр. `test_collision_suffix_never_exceeds_max_length, test_collision_suffix_respects_max_length`) | Усекать base до max_length - len(suffix) | 1 ч |
| P-05 | E | важная | app/models.py check-then-write в save() | Гонка при одновременном создании объектов с одинаковым названием: IntegrityError 1062 (подтверждено на MySQL, 8 потоков) | 0 / 3 (напр. `test_parallel_article_creation_with_same_title_yields_distinct_slugs, test_parallel_author_creation_with_same_name_yields_distinct_slugs`) | Ловить IntegrityError и повторять, либо блокировка/ретрай в save() | 2 ч |
| P-06 | A | важная | app/views.py:38,192,415 | Свежая установка: AboutUsText.get(pk=1) — 500 на /about-us, /editor-cabinet, /about-us-edit; data-миграция с дефолтной строкой отсутствует | 6 / 6 (напр. `test_about_us_edit_on_fresh_install_creates_row, test_about_us_on_fresh_install`) | get_or_create(pk=1) или миграция с начальными данными | 30 мин |
| P-07 | A | важная | app/views.py:63-65 article_detail | Неопубликованная/отложенная статья открывается любому по URL и накручивает просмотры | 4 / 4 (напр. `test_publish_schedule_creates_hidden_article, test_scheduled_article_is_not_public`) | 404 для is_published=False (кроме staff) | 30 мин |
| P-08 | A | важная | app/views.py:26-61,148 vs 158-161 | Списки (главная, категория, /all, автор) игнорируют publish_at; поиск/sitemap/feed учитывают — несогласованность; публикация по расписанию зависит только от команды | 4 / 4 (напр. `test_author_detail_hides_future_dated, test_category_hides_future_dated`) | Единый менеджер `Article.objects.live()` | 1 ч |
| P-09 | I | блокирующая | Procfile; app/management/commands/publish_articles.py | Команда публикации отложенных статей нигде не запускается (Procfile только web; нет app.json/scheduler в репозитории) | 1 / 1 (напр. `test_publish_command_is_wired_to_a_scheduler`) | Heroku Scheduler (каждые 5–10 мин) или фильтр по publish_at вместо флага | 30 мин |
| P-10 | A | блокирующая | app/views.py:295-299,317-321 | Удаление статьи/категории выполняется по GET (prefetch/краулер/ссылка удаляют данные); POST возвращает None → 500; удаление категории каскадом сносит подкатегории | 5 / 5 (напр. `test_get_does_not_delete_article, test_get_does_not_delete_category`) | @require_POST + подтверждение; protect вместо cascade | 1 ч |
| P-11 | B | важная | app/views.py:65 | HEAD, prefetch, поисковые боты и повторные обновления увеличивают счётчик просмотров | 5 / 5 (напр. `test_crawler_user_agents_do_not_count_views, test_head_does_not_change_state`) | Считать только GET, фильтровать ботов, дедуп по сессии/cookie | 1 ч |
| P-12 | B | важная | app/views.py (нет @require_http_methods), anarchia/urls.py | Публичные страницы принимают POST/PUT/PATCH/DELETE (200), POST-only эндпоинты принимают GET/PUT/… (200/500) вместо 405 | 4 / 4 (напр. `test_about_us_edit_get_is_not_server_error, test_get_on_post_only_endpoints_is_405`) | @require_GET / @require_POST | 1 ч |
| P-13 | A | желательная | app/views.py:476,484; settings без LOGIN_URL | `@login_required` без login_url у порядка категорий: редирект на несуществующий /accounts/login/ (404); /login без слеша даёт лишний 301 | 2 / 2 (напр. `test_anonymous_get_redirected_to_login_page_that_exists, test_login_url_setting_points_to_real_route`) | LOGIN_URL = "/login/" | 10 мин |
| P-14 | B | важная | app/views.py:204-292,324-406,302-314,422-460,410-420,486-494 | Невалидный ввод редакторских форм → 500: мусорные id автора/категории/родителя, пустые/длинные поля, неверная дата/язык, битый JSON порядка категорий | 28 / 29 (напр. `test_about_us_edit_missing_fields_keeps_text, test_create_author_missing_fields_is_client_error`) | Django Forms/ModelForm с валидацией | 1–2 дня |
| P-15 | A | важная | app/views.py:109-142 comment | Комментарии: нет валидации (None/пустые/длинные → 500 или мусор), ответ на комментарий другой статьи, комментарии к неопубликованным, дубли при двойной отправке, нет ограничения длины | 11 / 11 (напр. `test_blank_values_rejected, test_comment_on_unpublished_article_rejected`) | CommentForm + проверки принадлежности | 3 ч |
| P-16 | E | важная | app/views.py:118-122 | Неудачная капча молча отбрасывает комментарий (редирект без сообщения пользователю). Сбой сервиса reCAPTCHA обработан библиотекой (опровергнуто) | 1 / 1 (напр. `test_bad_captcha_tells_the_user`) | messages.error при невалидной капче | 30 мин |
| P-17 | E | важная | app/views.py:259-287,375-398 | Нет транзакций: publish сохраняет статью дважды и оставляет «осиротевшую» запись при плохой картинке; edit стирает категории до валидации; сбой на save оставляет частичные данные | 6 / 6 (напр. `test_edit_save_failure_keeps_categories, test_failure_on_second_save_leaves_no_half_published_article`) | @transaction.atomic + валидация до записи | 2 ч |
| P-18 | E | важная | app/views.py:398 article.save() | Редактирование статьи записывает всю строку и затирает параллельно накрученный счётчик просмотров; блокирует публикацию | 2 / 3 (напр. `test_edit_form_save_updates_only_changed_columns, test_editing_article_does_not_overwrite_concurrent_view_count`) | save(update_fields=[...]) | 30 мин |
| P-19 | C | важная | app/models.py:46,68 (CASCADE) | Удаление автора удаляет все его статьи; удаление родительской категории — все подкатегории | 4 / 4 (напр. `test_delete_author_does_not_delete_articles, test_deleting_author_keeps_articles`) | on_delete=PROTECT/SET_NULL | 1 ч |
| P-20 | C | важная | app/views.py:83-86,243-246; models (нет валидации parent) | Цикл в дереве категорий (parent=self/цикл из двух) допускается и вешает страницу статьи (бесконечный while) и publish | 5 / 5 (напр. `test_article_page_survives_category_cycle, test_category_cannot_be_its_own_parent`) | Model.clean() / проверка цикла, ограничение глубины | 1 ч |
| P-21 | C | желательная | templates/comment.html, recursive_menu.html (рекурсивный include) | Ветка комментариев/категорий глубиной ≥~400 → RecursionError, 500 | 2 / 2 (напр. `test_very_deep_category_tree_renders, test_very_deep_thread_does_not_crash`) | Ограничить глубину при записи/выводе | 1 ч |
| P-22 | A | важная | templates/category.html, author_detail.html, search.html (`reversed` по QuerySet без order_by); app/views.py:42,464 | Порядок карточек определяется порядком хранения (на MySQL — по UUID PK): «новые первыми» не гарантируется; авторы и модерация без сортировки | 6 / 6 (напр. `test_all_articles_order_newest_first_regardless_of_insert_order, test_author_page_order_newest_first_regardless_of_insert_order`) | order_by("-publish_at") в вью, убрать reversed | 30 мин |
| P-23 | A | желательная | templates/index.html (`popular_articles reversed`) | Блок «Найпопулярніші» выводится в обратном порядке (наименее популярная первой) | 1 / 1 (напр. `test_popular_section_most_viewed_first`) | Убрать reversed | 5 мин |
| P-24 | D | важная | app/views.py:45-61,146-172 | Нет пагинации: категории, /all, поиск, автор, авторы выводят всё; размер HTML и время растут линейно с числом статей | 5 / 5 (напр. `test_comments_page_html_is_bounded_with_many_comments, test_listing_html_size_is_bounded_with_many_articles`) | Paginator (12–24 на страницу) | 3 ч |
| P-25 | A | желательная | app/views.py:155-172 | Поиск: ищет по HTML-разметке, пустой запрос выводит весь каталог, без лимита; без индекса; на SQLite icontains регистрозависим для кириллицы; 100k символов → 500 (SQLite) | 7 / 5 (напр. `test_empty_query_does_not_dump_catalog, test_huge_query_string_is_not_500`) | Поиск по очищенному тексту / FULLTEXT; лимит; обработка пустого запроса | 1 день |
| P-26 | D | важная | app/views.py:190-201,204-206,324-327; templates/editor-cabinet.html, comments_moderation.html | N+1 в кабинете редактора: запросов 91 при 40 статьях против 11 при 3 (кабинет), 87/7 (/publish), 48/8 (edit), 51/11 (модерация) | 2 / 2 (напр. `test_editor_pages_do_not_grow_with_data, test_editor_pages_have_a_ceiling`) | select_related/prefetch_related | 2 ч |
| P-27 | I | блокирующая | anarchia/settings.py:106-120 (OPTIONS без charset), django_heroku | Соединение с MySQL открывается в utf8mb3: любой эмодзи в комментарии, заголовке или поиске → DataError 1366 → 500 (воспроизведено на MySQL 8) | 0 / 4 (напр. `test_emoji_comment_is_stored_with_production_connection_options, test_emoji_in_article_title_is_stored_with_production_connection_options`) | OPTIONS: {'charset': 'utf8mb4'} | 15 мин |
| P-28 | B | важная | app/views.py (нет валидации длины), models max_length | На MySQL (STRICT) превышение длины полей (комментарий-автор >100, имя категории/автора >100) → DataError 500; SQLite молча принимает | 2 / 5 (напр. `test_create_category_too_long_name_is_client_error, test_overlong_author_is_client_error`) | Формы с max_length | 1 ч |
| P-29 | D | важная | app/models.py (нет db_index/Meta.indexes) | Нет индексов под основные фильтры: is_published, language, publish_at, views, comment.created_at (только PK, slug, FK) | 0 / 2 (напр. `test_comment_lookup_by_article_is_indexed, test_listing_filter_columns_are_indexed`) | Meta.indexes: (is_published, language, -publish_at), views | 1 ч |
| P-30 | C | желательная | app/models.py:35-36 Author.get_absolute_url | `/authors/<slug>/` — маршрут без завершающего слеша → 404 (ссылка «Смотреть на сайте» в админке) | 1 / 1 (напр. `test_absolute_url_resolves`) | reverse("author_detail") | 5 мин |
| P-31 | B | желательная | anarchia/urls.py:41-42 | Маршрут `article_by_id` недостижим (slug-конвертер перехватывает UUID), редиректа со старых URL по id нет | 4 / 4 (напр. `test_edit_slug_change_leaves_redirect_from_old_url, test_every_route_is_reachable`) | Поставить uuid-маршрут выше и делать 301 на slug | 30 мин |
| P-32 | F | желательная | templates/article.html (`{% if author.image %}`) | Переменной `author` в контексте нет: фото автора в статье не показывается никогда | 1 / 1 (напр. `test_article_author_photo_rendered_when_present`) | article.author.image | 5 мин |
| P-33 | F | важная | templates/base.html:116,139,204 | JS падает на каждой странице: нет #ticker и .ticker (TypeError на load/resize), themeToggle только в article.html; на 768px контент уходит под шапку на 28–48 px | 4 / 4 (напр. `test_base_scripts_guard_against_missing_elements, test_every_element_used_by_base_scripts_exists_on_every_page`) | Удалить мёртвый код или добавить null-проверки | 30 мин |
| P-34 | F | блокирующая | templates/article.html:127, comment.html:12 | `toggleReplyForm` нигде не определена: кнопка «Відповісти» не работает, ответы на комментарии невозможны через UI | 1 / 1 (напр. `test_toggle_reply_form_function_is_defined`) | Добавить функцию | 15 мин |
| P-35 | G | важная | templates/base.html:105,22,66; карточки | a11y (axe-core): button-name (critical), image-alt (critical), link-name, html-has-lang, color-contrast (статья), heading-order; меню недоступно с клавиатуры и тача (только hover) | 10 / 10 (напр. `test_content_images_have_alt_text, test_exactly_one_h1_per_page`) | aria-label, alt, tabindex/кнопки | 1 день |
| P-36 | G | важная | templates/base.html:5-14; app/sitemaps.py; app/feeds.py; settings SITE_ID | SEO: один и тот же title, нет description/canonical/og/hreflang/JSON-LD/lang; нет robots.txt; sitemap и RSS с хостом example.com (django.contrib.sites), без категорий/главной, lastmod=now(); RSS: язык `ua`, pubDate=created_at | 23 / 23 (напр. `test_article_has_og_image_and_type_article, test_article_has_structured_data`) | Site.domain, мета-теги в шаблонах, CategorySitemap | 1 день |
| P-37 | H | важная | anarchia/settings.py:149 LANGUAGE_CODE="ua"; templates; app/views.py | LANGUAGE_CODE/LANGUAGES "ua" невалиден (uk): get_language_info KeyError, Content-Language: ua, нет <html lang>; часть строк не переведена/захардкожена (base.html, login.html, flash-сообщения вью), msgid с хвостовым пробелом; переключение языка теряет query; даты d.m.Y | 16 / 16 (напр. `test_content_language_header_is_valid_bcp47, test_date_format_follows_language`) | Перейти на `uk` + миграция cookie; обернуть строки в trans | 1 день |
| P-38 | H | желательная | app/models.py, anarchia/urls.py, publish_articles.py, authors.html, edit_author.html (UTF-8 BOM) | BOM в .py и .html: перед <!DOCTYPE> в /authors выводится U+FEFF; ломает radon/ast-инструменты | 3 / 3 (напр. `test_files_with_bom_still_import_and_render, test_python_files_have_no_bom`) | Убрать BOM | 5 мин |
| P-39 | F | важная | templates/base.html:13-14 | Блокирующие внешние ресурсы на каждой странице: ckeditor5 (нужен только в кабинете) и шрифты fonts.cdnfonts.com; секунда задержки CDN = +1 с к FCP, при недоступности FCP не наступает за 12 с; кабинет на CKEditor 5, бэкенд на CKEditor 4, загрузка `/ckeditor/upload/` — контракт CK4 | 6 / 6 (напр. `test_background_images_use_static_urls_through_manifest, test_ckeditor_cdn_script_is_loaded_only_where_used`) | Вынести CKEditor в шаблоны кабинета; шрифты self-host/async | 2 ч |
| P-40 | I | блокирующая | anarchia/settings.py:35 DEBUG=True; нет LOGGING/ADMINS/Sentry; нет 404.html/500.html; нет /healthz | DEBUG захардкожен True: debug-страницы в проде, рост памяти (connection.queries); 500 не пишутся нигде; нет health-check; при падении БД — 500, не 503; сбой кэша ломает все страницы; нет брендированных 404/500 | 9 / 9 (напр. `test_404_page_has_menu_and_link_home, test_cache_backend_failure_does_not_break_pages`) | DEBUG из env, LOGGING в stdout, Sentry, /healthz, шаблоны 404/500 | 3 ч |
| P-41 | E | важная | templates (article.image.url без проверки), app/views.py:431-437 | Пустое поле image (создание автора без файла пишет `""`) → `.url` ValueError → 500 на главной/категориях/поиске/статье; сбой storage.url() и upload не обработаны | 5 / 5 (напр. `test_article_without_image_ok, test_article_without_image_renders_home`) | `{% if article.image %}` + плейсхолдер | 1 ч |
| P-42 | C | важная | app/migrations/0007_fill_slugs.py | Миграция 0007: необратима (RunPython без reverse), на кириллице создаёт slug `""`, `-1`, `-2`…, не ограничивает длину; нет начальной строки AboutUsText | 5 / 5 (напр. `test_0007_gives_cyrillic_articles_nonempty_slugs, test_0007_gives_cyrillic_authors_nonempty_slugs`) | reverse_code=noop, общий генератор slug | 1 ч |
| P-43 | D | важная | settings.py CACHES (LocMemCache) | Кэш меню в памяти процесса: после правки категории при 4 воркерах только 8 из 60 запросов видят новое меню (до 3600 с) | 0 / 0 | Redis/Memcached или короткий TTL | 2 ч |
| P-44 | I | важная | requirements.txt, runtime.txt, Procfile | Установка requirements на Python 3.13.7 падает целиком (psycopg2, mysqlclient); Django 4.2.4 официально ≤3.11 (4.2.x ≤3.12); 16 пакетов с известными уязвимостями (Django 4.2.4, Pillow, urllib3, cryptography …); 15+ неиспользуемых тяжёлых пакетов; нет release-фазы и параметров gunicorn | 0 / 0 | Почистить зависимости, обновить Django 4.2.x LTS→5.2, release: migrate | 1 день |
| P-45 | J | желательная | репозиторий | Мусор в git: .pyc, staticfiles/, db.sqlite3, .vs/, .idea/, media/ (часть удалена параллельным аудитом); fill_slugs.py в корне обнуляет slug у всех объектов при запуске; settings.py в .gitignore при том что отслеживается | 0 / 0 | Удалить fill_slugs.py, .gitignore | 30 мин |
| P-46 | F | желательная | templates/index.html:10, category.html:19 | bg.png (970 КБ) подключён в обход манифеста WhiteNoise: max-age=60, без хеша | 1 / 1 (напр. `test_background_images_use_static_urls_through_manifest`) | static-тег | 10 мин |
| P-47 | E | желательная | app/views.py:205-292 | Двойная отправка форм создаёт дубли (категория, автор, статья) | 3 / 3 (напр. `test_double_posted_article_is_deduplicated, test_double_posted_author_is_deduplicated`) | Идемпотентность/уникальность | 1 ч |
| P-48 | A | желательная | app/views.py:250-254 | Время отложенной публикации интерпретируется как UTC, а не локальное время редактора (+2/3 ч) | 1 / 1 (напр. `test_publish_scheduled_time_interpreted_in_editor_timezone`) | Использовать Europe/Kyiv | 30 мин |
| P-49 | A | желательная | app/views.py:176-186 | Логин игнорирует `next` | 1 / 1 (напр. `test_login_has_next_support`) | redirect(request.GET.get("next")) | 15 мин |
| P-51 | A | желательная | app/views.py:372-373 | Редактирование уже опубликованной статьи сбрасывает publish_at в now(): статья «прыгает» на верх ленты и меняется lastmod | 1 / 1 (напр. `test_edit_does_not_bump_publish_date_of_live_article`) | Менять publish_at только при смене режима публикации | 30 мин |
| P-52 | B | желательная | app/views.py:276-285,384-393 | Файл принимается по заявленному content_type: «png» с произвольным содержимым сохраняется в хранилище и ломает вывод | 1 / 1 (напр. `test_publish_with_fake_image_content_rejected`) | Проверять содержимое (Pillow verify) | 30 мин |
| P-53 | B | желательная | anarchia/urls.py | Смешанные завершающие слеши (`/about-us`, `/authors`, `/all` без слеша, остальные со слешем) → лишние 301 и дубли URL | 1 / 1 (напр. `test_trailing_slash_consistency`) | Единое правило, 301 на канон | 30 мин |
| P-54 | I | желательная | MySQL collation utf8mb4_0900_ai_ci + slug lookup | На MySQL `/article/SEED-0/` отдаёт ту же статью (регистронезависимый поиск по slug): дубли URL; на SQLite 404 — поведение различается | 0 / 1 (напр. `test_uppercase_slug_redirects_or_404`) | Канонический redirect/lowercase slug | 30 мин |
| P-50 | D | желательная | app/test_findings.py:table_queries | Тестовый хелпер ищет `"app_category"` в двойных кавычках: на MySQL (обратные кавычки) даёт ложно-зелёное «0 запросов» | 0 / 0 | Искать подстроку app_category | 5 мин |

Итого по серьёзности: {'блокирующая': 7, 'важная': 29, 'желательная': 18}


## 5. Производительность и масштаб (группа D)

Подробности, команды и ограничения: [evidence/D_performance.md](evidence/D_performance.md). Данные: 200 авторов, 500 категорий, 10 000 статей (9 463 опубликовано, 6 668 на `ua`), 50 000 комментариев, MySQL 8.0 в Docker, macOS (не Linux/Heroku: RSS отличается). Замеры шумные (параллельно работали другие процессы).

**Число SQL-запросов не зависит от N** (N+1 на публичных страницах нет): `/` 4, статья 7, категория 2, поиск 1, `/all` 1, sitemap 6. Растут время, размер HTML и память:

| Страница | N=100: мс / КБ | N=10 000: мс (p50) / HTML | RSS пик |
|---|---|---|---|
| `/` | 9 / 40 | 25 мс / 103 КБ | 71 МБ |
| `/all` (6 668 статей) | 14 / 77 | **1 409 мс / 7,1 МБ** | **351 МБ** |
| категория-корень (2 137) | 11 / 57 | 499 мс / 2,3 МБ | 300 МБ |
| статья, 5 000 комментариев | 33 / 582 | 464 мс / 9,4 МБ | 285 МБ |
| поиск «стаття» (6 666 совпадений) | 15 / 71 | 1 468 мс / 6,5 МБ | 349 МБ |
| поиск пустой запрос | 21 / 92 | **2 421 мс / 8,7 МБ** | 350 МБ |
| `/sitemap.xml` (9 463) | 11 / 14 | 738 мс / 1,4 МБ | **414 МБ** |
| `/feed/`, `/about-us`, `/authors` (200) | 1–2 мс | 9 / 1 / 14 мс | ≤75 МБ |

Линейная модель ≈0,21 мс на статью даёт 30-секундный `timeout` gunicorn при 35–140 тыс. статей.

**Индексы (EXPLAIN, MySQL).** На `language`, `is_published`, `views`, `publish_at` индексов нет: полный скан + filesort. Пробные составные индексы `(language, is_published, publish_at|views)` ускоряют главную и блок «рекомендованные» с 8 до 0,6 мс; для `/all` с `LIMIT 20` — с 8 до 1 мс. Без `LIMIT` индексы не помогают (нужны все строки: нужна пагинация). `LIKE '%q%'` btree не ускоряет (FULLTEXT ускоряет редкое слово 140→0,6 мс, но меняет семантику). Когда все пять пробных индексов стояли одновременно, feed и sitemap стали медленнее: индексы проверять по одному.

**Нагрузка (gunicorn + locust, 20 пользователей, 90 с, ошибок 0):**

| Конфигурация | RPS | p50 | p95 | p99 |
|---|---|---|---|---|
| 1 воркер (как Procfile), тяжёлый микс с `/all` и поиском | 4,0–4,2 | 4,8 с | 8 с | 9 с |
| 4 воркера, тяжёлый микс | 10,6–14,6 | 1,0–1,3 с | 2,9–4,0 с | 3,5–5,8 с |
| 1 воркер, лёгкий микс (главная + статья) | ≈38 | 340 мс | 420 мс | — |
| 4 воркера, лёгкий микс | ≈89 | 44 мс | 86 мс | — |

**Память.** 10 минут, 4 воркера: ошибок 0, RSS воркера пилообразный 37–294 МБ, сумма до 911–937 МБ. Устойчивой утечки не видно, но медленную (до 10 МБ/мин) отсечь нельзя. Различия `DEBUG=True`/`False` — 1–2 % (гипотеза о накоплении SQL в памяти **опровергнута**: в Django 4.2 `reset_queries` подписан на `request_started`, лог ограничен 9 000 записей).

**Кэш меню (LocMemCache), `-w 4`:** после `POST /create-category/` новое меню видит только воркер, принявший запрос: **8 из 60** последующих `GET /` (при 1 воркере 60 из 60). Остальные 3 воркера отдавали старое меню весь период наблюдения (323 с); верхняя граница 3 600 с взята из TTL в коде (не измерена). Холодный первый запрос воркера 34–62 мс против 27 мс тёплого.

**Оценка лимитов хостинга** (допущения: общие знания о Heroku, не измерения): один воркер ≈4 RPS на тяжёлом миксе; один запрос к `/all` или sitemap поднимает процесс до 350–414 МБ (**риск R14 на 512 МБ dyno**); публичная страница тратит 1–7 SQL-запросов и 1–60 мс БД. Пагинация, `LIMIT`, индексы и кэш sitemap возвращают нагрузку в безопасную зону.

## 6. Мутационное тестирование (группа K)

`mutmut` 3 требует pytest-обвязки и на этом наборе зависает; использован собственный детерминированный AST-прогон ([scripts/mutate.py](scripts/mutate.py), [mutate_survivors.py](scripts/mutate_survivors.py)). Мутанты «убивает» только тест, зелёный на неизменённом коде (иначе ~220 красных тестов обесценили бы метрику). Перед прогоном — контрольный запуск без мутации.

| Файл | Мутантов | Убито | Выжило |
|---|---|---|---|
| `app/models.py` | 50 | 50 | 0 |
| `app/context_processors.py` | 3 | 3 | 0 |
| `app/views.py` | 86 | 79 | 7 |
| **Итого** | **139** | **132 (95,0 %)** | **7** |

Первый прогон давал 117/139 (84,2 %). 22 выживших разобраны; для значимых добавлено 15 тестов (`test_k_mutation.py`): лимиты 10/5/2 на главной и «рекомендованных», фильтр опубликованного в рекомендациях, `and`→`or` при расписании, редиректы после POST, JSON-ответ порядка категорий, ответы на неверный тип файла, `__str__` моделей.

Оставшиеся 7 (`views.py` 299, 314, 321, 440, 478): ветки GET-удаления и GET-рендеров POST-only эндпоинтов — это ровно поведение, которое находки P-10/P-12 требуют убрать; тесты на него писать бессмысленно. Мутант на строке 297 (`==`→`!=`) ловит красный тест `test_get_does_not_delete_article`.

## 7. Фронтенд, a11y и SEO (группы F, G)

Подробности и скриншоты: [evidence/FG_frontend.md](evidence/FG_frontend.md) (12 PNG в `evidence/screens/`). Все внешние хосты в браузере блокировались.

- **JS-ошибки: ожидание «0» не выполнено.** 3 `pageerror` на каждой странице (на статье 2) в 153 загрузках во всех трёх браузерах и трёх вьюпортах: `themeToggle` = null (base.html:116), `#ticker` нет нигде (base.html:139), `ticker.style` (base.html:204, на `load` и каждом `resize`). На 768 px шапка 130 px, контент уходит под неё на 28–48 px. Гипотеза «ломается margin-top везде» опровергнута частично: на 375 и 1440 спасает CSS-фоллбэк (`style.css:975-981`).
- **`toggleReplyForm` не определена:** ответы на комментарии недоступны через UI (серверный путь работает).
- **Меню:** hover на десктопе работает, включая вложенное. На 375 тап по категории с детьми раскрывает подменю, но перейти в саму категорию нельзя (`preventDefault`). Режим «тап» включается по `innerWidth <= 768`, бургер по CSS при ≤1000: на 900 px с тачем подменю недоступно. С клавиатуры подменю и бургер недоступны.
- **Язык:** переключение на `/search/?q=…` теряет query; на статье меняется меню, текст остаётся украинским. **Тема** только на статье, не запоминается. **Капча:** без токена комментарий молча отбрасывается.
- **Внешние ресурсы:** CKEditor 5 и шрифт на каждой странице блокируют рендер (FCP 70 мс → ≈2 070 мс при задержке CDN 2 с; при недоступности CDN FCP не наступает за 12 с). `ClassicEditor` нужен только в кабинете. CKEditor 5 (фронт) и CKEditor 4 (пакет `ckeditor`) — два разных редактора, загрузка идёт на `/ckeditor/upload/` (контракт CK4).
- **Lighthouse** (CDN недоступен: perf оптимистичнее реального):

| Страница | Perf mobile | Perf desktop | A11y | Best practices | SEO |
|---|---|---|---|---|---|
| Главная | 75 | 96–100 | 55–65 | 96 | 73–82 |
| Категория | 76 (LCP 7,5 с) | 96–100 | 55–65 | 96 | 73–82 |
| Статья | 95 | 96–100 | 55–65 | 96 | 73–82 |

Предлагаемые пороги ≥90 по всем четырём метрикам не проходят: a11y и SEO на всех страницах; perf mobile на главной и категории. `static/img/bg.png` 970 КБ в обход манифеста WhiteNoise (`max-age=60`).
- **axe-core** (все публичные страницы): `button-name` (critical, кнопка поиска), `image-alt` (critical, логотипы), `html-has-lang`, `link-name` (2–14 узлов), на статье `color-contrast` (19–20 узлов, напр. 3,92:1), `heading-order`; нет `h1` на `/login/`, два `h1` на `/`.
- **SEO:** одинаковый `<title>` везде; нет description, canonical, og:*, hreflang, JSON-LD, `<html lang>`; `robots.txt` и `favicon.ico` — 404. Sitemap валиден, без черновиков (утечка **опровергнута**), но без главной/категорий/`/authors`, lastmod автора и about = «сегодня», хост из `django.contrib.sites` (`example.com`). RSS валиден (`feedparser`, bozo=0), язык канала `ua`, дата `created_at` вместо `publish_at`.
- **Опровергнуто:** смешанный контент (0 http-ресурсов), локальные 404 по static/media, горизонтальный скролл, JS-ошибка на странице 404, недоступность hover-подменю для мыши.

## 8. Развёртывание и эксплуатация (группа I)

Подробности: [evidence/I_deploy.md](evidence/I_deploy.md).

- **Установка `requirements.txt` на Python 3.13.7 падает целиком:** `psycopg2==2.9.11` (нет `pg_config`), `mysqlclient>=2.0` (нет бинарных колёс, нужен `mysql_config`), а `django-heroku` тянет `psycopg2` без пина. Без этих трёх всё ставится за 61 с; единственное нарушение `pip check`: `django-heroku requires psycopg2`. На Heroku эти пакеты могут собираться (есть libpq и Aptfile) — **не проверено**. `mysqlclient` и `libmysqlclient-dev` не нужны: `pymysql.install_as_MySQLdb()` подменяет модуль.
- **Django 4.2.4 на 3.13** официально не заявлен (классификаторы до 3.11, ветка 4.2 — до 3.12), но `check`, `migrate`, `collectstatic`, gunicorn и 24 прежних теста работают.
- **`check --deploy`:** 5 предупреждений (ckeditor W001, W009 `SECRET_KEY`, W012, W016, W018 `DEBUG=True`).
- **collectstatic с боевым Manifest-хранилищем:** без ошибок (1 403 файла); все `{% static %}` и `url()` в CSS резолвятся. `bg.png` подключён мимо манифеста (`index.html:10`, `category.html:19`).
- **Окружение:** отсутствие любой из шести переменных даёт голый `KeyError` без пояснения. При заданном `DATABASE_URL` `django_heroku` заменяет `DATABASES` целиком: `DATABASE_NAME/USER/PASSWORD/HOST` игнорируются, `init_command` со `STRICT_TRANS_TABLES` теряется, `ALLOWED_HOSTS` становится `['*']`. `WhiteNoiseMiddleware` стоит в `MIDDLEWARE` дважды.
- **DEBUG** захардкожен `True` (`settings.py:35`); при `False` `/media/` отдаётся только при DEBUG (404).
- **Логирование:** при `DEBUG=False` 500 не пишется нигде (`ADMINS=[]`, консольный handler Django фильтруется `RequireDebugTrue`); access-лог gunicorn выключен; нет Sentry, health-check, `robots.txt`.
- **Заголовки:** X-Frame-Options DENY, nosniff, Referrer-Policy, COOP, HSTS (при `X-Forwarded-Proto: https`); нет CSP; `csrftoken` без `Secure`. WhiteNoise: хешированный CSS `max-age=315360000, immutable`, нехешированный `max-age=60` + gzip. Ответы идентичны на 1 и 4 воркерах.
- **Procfile:** только `web: gunicorn anarchia.wsgi`: нет `release:` для `migrate`, нет `--workers/--threads/--timeout` (sync, 1 воркер), нет процесса/планировщика для `publish_articles`.
- **MySQL (проверено локально):** `STRICT_TRANS_TABLES` включён, все таблицы InnoDB/utf8mb4, ключи `slug` укладываются в лимит индекса InnoDB, свежая БД мигрирует с нуля, `makemigrations --check` чист.
- **Бэкапы, миграции без простоя, откат релиза:** в репозитории нет ничего (ни `app.json`, ни скриптов); проверить можно только на уровне конфигурации Heroku (раздел 12).

## 9. Статический анализ (группа J)

Запуск на `a240822`, `app/` и `anarchia/` без тестов и миграций.

| Инструмент | Результат |
|---|---|
| ruff (E,F,W,B,UP,C90; 120 символов) | 34 замечания: W291×7, W293×5, E501×5, W292×4, **F401×4** (`User`, `slugify`, `Editor` в `views.py`, `TestCase`), E702×3, C901×2, F841×2 (`new_category`, `new_author`), F811×1 (`AboutUsText` импортирован дважды), B007×1 |
| radon cc | средняя A (2,19); C(13): `views.publish`, `views.edit_article`. Не разбирает файлы с BOM (`models.py`, `publish_articles.py`) |
| vulture | мёртвое: `fill_slugs.py` (корень), `templatetags/app_tags.py` (`comment_depth`, `multiply` не используются), `Editor` (модель не используется кодом); шаблоны `recursive_list.html` и `comment.html` **используются** (подозрение на мёртвый код опровергнуто; `recursive_list.html` рекурсивно обращается к `category.children.all` — один из источников N+1 в кабинете); остальное — константы settings (шум) |
| bandit | значимое: захардкоженный `SECRET_KEY` (`settings.py:32`; для отдельного аудита безопасности) |
| deptry | 15+ неиспользуемых: `rethinkdb`, `Pyrebase4`, `gcloud`, `Radicale`, `pybind11`, `psycopg2`, `python-firebase`, `oauth2client`, `google-*` и др. (часть «неиспользуемых» — косвенные зависимости, проверять по одной) |
| pip-audit (66 пакетов) | **16 пакетов с известными уязвимостями**: Django 4.2.4, Pillow 12.1.0, urllib3 1.26.16, cryptography 41.0.4, pyasn1, sqlparse, requests 2.29.0, jwcrypto, certifi, gunicorn 21.2.0, idna, protobuf, setuptools, httplib2 и др. (число записей 262 включает дубли по алиасам). Запрос к базе советов шёл к внешнему сервису PyPI |
| djlint | 165 замечаний по 17 шаблонам (H021 ×113 inline-стили, H014 ×28, H029 ×13) |
| mypy (мягкий) | 34 замечания в 3 файлах (напр. `apps.py:4` переопределение `AppConfig`) |
| django-upgrade | упал на файле с BOM (`SyntaxError`), по остальным правок нет |

Другое: файлы с UTF-8 BOM (`models.py`, `urls.py`, `asgi.py`, `publish_articles.py`, `authors.html`, `edit_author.html`); `fill_slugs.py` обнуляет slug всем объектам при запуске; `.gitignore` перечисляет `settings.py`, который отслеживается.

## 10. Гипотезы

| № | Исход | Основание |
|---|---|---|
| 1 | **Подтверждена** (частично опровергнута по индексам) | Расхождения: `utf8mb3` для эмодзи (P-27), длина полей в STRICT (P-04, P-28), регистронезависимость кириллицы в `icontains` (SQLite красный, MySQL зелёный), порядок по PK на MySQL (P-22), URL без учёта регистра (P-54), гонки slug (P-05), `LIKE` 100 КБ (SQLite 500). Опровергнуто: длина индексов `slug` укладывается в лимит |
| 2 | **Частично опровергнута** | slug существующей статьи при `save()` не меняется (стабилен). Подтверждены: кириллица → `article`/`article-N`, длина > 200, коллизии без лимита |
| 3 | Подтверждена | P-01 |
| 4 | Подтверждена | P-06 |
| 5 | **Подтверждена частично** | Команда `publish_articles` есть и работает (границы, идемпотентность), но нигде не запускается (P-09) |
| 6 | **Частично опровергнута** | `locale/` есть и покрывает строки шаблонов. Подтверждены: невалидный `ua`, `KeyError` у `get_language_info`, `Content-Language: ua`, непереведённые/захардкоженные строки, пробел в msgid (P-37) |
| 7 | Подтверждена и шире | P-33, P-34 |
| 8 | Подтверждена | P-24 |
| 9 | Подтверждена | P-25 |
| 10 | Подтверждена | P-11 |
| 11 | **Частично опровергнута** | Отсутствие файла в хранилище не ломает страницы (`.url` не проверяет файл). Подтверждены: пустое `image` → 500, сбой `url()`/upload не обработан (P-41). Состояние Cloudinary не проверялось |
| 12 | Подтверждена | P-43 (8/60) |
| 13 | **Подтверждена частично** | 0007 необратима, плодит `""`/`-N` slug (P-42). Опровергнуто: `makemigrations --check` чист, цепочка с нуля проходит на SQLite и MySQL, 0007 идемпотентна на ASCII |
| 14 | Подтверждена | P-45 |
| 15 | **Частично опровергнута** | Все `{% url %}` и `reverse()` указывают на существующие имена с верным числом аргументов. Находки: `article_by_id` недостижим (P-31), `Author.get_absolute_url` даёт 404 (P-30), `author` в `article.html` (P-32) |
| 16 | **Подтверждена (локально)** | P-44; поведение на Heroku не проверено |
| 17 | Подтверждена (частично исправлена параллельным аудитом) | P-45 |

## 11. Проверено и безопасно

- Число SQL-запросов публичных страниц не растёт с N (статьи, категории, комментарии, авторы): N+1 исправлены и закреплены 14 регрессионными тестами; меню строится одним запросом, на тёплом кэше 0.
- Счётчик просмотров — атомарный `F()`-апдейт одной колонки, параллельные просмотры не теряются (MySQL, 16 потоков).
- Параллельные комментарии (12 потоков) сохраняются все.
- `make_aware` на переходе на летнее время (пропущенное и неоднозначное время в `Europe/Kyiv`) не падает.
- `%`, `_`, `\` в поиске экранируются; открытый редирект в `set_language` закрыт; HTML комментариев экранируется.
- Sitemap и RSS не выдают черновики и будущие статьи; RSS валиден.
- Меню и футер кэшируются по языку без перекрёстного загрязнения; сброс по сигналам работает в процессе-источнике.
- Недоступность reCAPTCHA обрабатывается библиотекой (комментарий не создаётся, 500 нет).
- `STRICT_TRANS_TABLES`, InnoDB/utf8mb4, ключи `slug`, миграция свежей БД с нуля (SQLite и MySQL), `makemigrations --check`.
- Статика: collectstatic с манифестом без ошибок; нет смешанного контента; ответы идентичны на 1 и 4 воркерах.
- Контракты URL: все имена обратимы, число аргументов верно, краулер от главной на синтетических данных не находит 404/500 (на ASCII-данных).
- Накопления SQL-запросов в памяти при `DEBUG=True` нет (Django 4.2).

## 12. Не проверено и почему

| Что | Почему / чего не хватает |
|---|---|
| Сборка и запуск на реальном Heroku (python-3.13.7, Aptfile, psycopg2/mysqlclient) | запрет на обращения к Heroku |
| Cloudinary: загрузка, отсутствие `card-example.png`, сбои | запрет на внешние сервисы; хранилище мокалось |
| Реальная reCAPTCHA | мок |
| Heroku Scheduler (настроен ли вне репозитория) | вне репозитория |
| Боевая БД: charset соединения, collation, объём, индексы | нет доступа; MySQL 8.0 в Docker. MariaDB/MySQL 5.7 не проверялись |
| Реальные задержки CDN; Lighthouse с настоящими CDN | сеть заблокирована намеренно |
| Нагрузка на Linux/Heroku, реальные лимиты dyno и БД-аддона, сетевая задержка до БД | локальный macOS; оценка в разделе 5 помечена как допущение |
| Утечка памяти > 10 мин | прогон 10 мин |
| Sitemap > 50 000 URL | 10 000 статей |
| Сравнение производительности на SQLite | не мерилось |
| Safari/реальные тач-устройства | Playwright WebKit и эмуляция |
| `mutmut` 3 / `cosmic-ray` | не совместимы с набором без pytest-обвязки; использован собственный AST-прогон (раздел 6) |
| Бэкапы, восстановление, zero-downtime, откат релиза | в репозитории нет артефактов; проверить на хостинге |
| Текущий HEAD (после параллельных исправлений) | цифры закреплены на `a240822`; HEAD не мерился |
| Безопасность (CSRF, XSS, права, секреты) | отдельный аудит; здесь только при влиянии на надёжность |

## 13. Чек-лист запуска (go-live)

1. [ ] Закрыты 7 блокирующих находок; зелёные `test_findings` + `prod_tests` (кроме согласованных остатков).
2. [ ] `DEBUG` из окружения (`False` в проде); `SECRET_KEY`, ключи Cloudinary/reCAPTCHA — из окружения (секреты в репозитории скомпрометированы: ротировать).
3. [ ] `DATABASES`: единая конфигурация (убрать дублирование `DATABASE_URL`/`DATABASE_*`), `charset: utf8mb4`, `STRICT_TRANS_TABLES`; проверить, что `django_heroku` не затирает `OPTIONS`.
4. [ ] Требования: убрать неиспользуемые тяжёлые пакеты, `psycopg2`/`mysqlclient`; обновить Django и пакеты с уязвимостями; чистая установка на `python-3.13.7` проходит.
5. [ ] Procfile: `release: python manage.py migrate --noinput`, `web: gunicorn anarchia.wsgi --workers N --timeout 30 --access-logfile -`; Heroku Scheduler на `python manage.py publish_articles`.
6. [ ] `LOGGING` в stdout + Sentry (или ADMINS), `/healthz`, `404.html`/`500.html`, `robots.txt`.
7. [ ] Пагинация на `/all`, категориях, поиске, авторе, авторах; `LIMIT` и кэш sitemap; составные индексы (по одному, с проверкой EXPLAIN).
8. [ ] Кэш меню: общий (Redis/Memcached) или TTL ≤ 60 с.
9. [ ] Данные: исправить существующие пустые slug (`SELECT ... WHERE slug = '' OR slug LIKE '-%'`), создать строку `AboutUsText(pk=1)`.
10. [ ] Smoke-тест на стейдже: главная, статья, категория, поиск, комментарий (капча), публикация, отложенная публикация, переключение языка, кабинет.
11. [ ] Резервная копия БД перед миграциями; проверка восстановления.
12. [ ] Нагрузочный прогон: p95 страниц с пагинацией, память одного воркера < 256 МБ.
13. [ ] Мониторинг: алерты на 5xx, R14/R15, время ответа, число запросов к БД.

## 14. План отката

- **Код:** `heroku rollback` на предыдущий релиз (или `git revert` + деплой). Одна находка — один коммит, откат точечный.
- **Миграции:** миграция 0007 необратима; новые миграции писать с `reverse_code`. Перед релизом с миграцией — снимок БД (`mysqldump` / бэкап аддона). Откат схемы — восстановление из снимка, а не `migrate <prev>`.
- **Кэш:** после отката сбросить кэш меню (`cache.clear()` или рестарт dyno).
- **Данные slug:** исправление пустых slug делать скриптом, сохранив старые значения в отдельной таблице/CSV, чтобы можно было вернуть прежние URL.
- **Критерий отката:** рост 5xx > 2 % за 5 минут или p95 > 3 с на главной/статье.

## 15. Решения, нужные от вас

1. Принять вердикт и порядок исправлений (Фаза 4 начинается только после явного «приступай»).
2. Какой Django целевой: 4.2 LTS (EOL) → 5.2 LTS? Параллельный аудит безопасности уже перевёл окружение на 5.2.18, и это меняет часть находок (например, `utf8mb3` в P-27); после апгрейда надо переснять замеры.
3. Нужна ли пагинация «страницами» (SEO: `?page=`) или «загрузить ещё» (JS)?
4. Heroku Scheduler уже настроен вне репозитория? Если да, P-09 снимается.
5. Транслитерация slug: `unidecode`-подобная схема или ручной ввод slug редактором.

## Приложение: артефакты

- Тесты: `prod_tests/` (`helpers.py` — общие фабрики, мок капчи, изоляция запросов в savepoint, лимит запросов вместо сигнального таймаута); расширение `anarchia/settings_test.py` (`NYZ_DB=mysql`, `NYZ_DB_FILE`, `NYZ_DB_NAME`).
- Скрипты: `docs/prod-readiness/scripts/` (`findings.py` — каталог находок и статусы по логам, `mutate*.py`, `run_prod_tests.sh`, генератор данных, locust, EXPLAIN, Playwright).
- Доказательства: `docs/prod-readiness/evidence/` (`D_performance.md`, `FG_frontend.md`, `I_deploy.md`, скриншоты), инвентаризация: `INVENTORY.md`.
- Инфраструктура тестов: тест-хелпер `table_queries` в `test_findings.py` ищет `"app_category"` в двойных кавычках и на MySQL даёт ложно-зелёное «0 запросов» (P-50).

## 16. Фаза 4: исправления

Работа шла поверх коммитов параллельного аудита безопасности (`f49d722`…`508ddfd`), который уже закрыл часть находок: транслитерацию slug, удаление только по POST, скрытие черновиков, валидацию ввода, санитайзинг HTML, ограничение глубины, Django 5.2, секреты в окружении. Эти коммиты ниже указаны как «безопасность».

Набор тестов теперь лежит в `prod_tests/` (вне `app/`, потому что сканеры безопасности считают любой `app/*.py` боевым кодом). Запуск: `manage.py test prod_tests app.test_findings app.security_tests`, для MySQL `NYZ_DB=mysql`.

**Итог прогона на текущем HEAD:** SQLite — 1200 тестов, 0 красных; MySQL 8.0 — 1200 тестов, 0 красных (до правок: 224 и 238 красных методов из 582).
**Браузеры:** 99 загрузок страниц в Chromium, Firefox и WebKit × 375/768/1440 дали 0 ошибок JS (раньше 3 на каждой странице); форма ответа открывается и переносит единственную капчу, дублей `id` нет.

| Находка | Исправление (коммит) |
|---|---|
| P-01, P-02, P-03 slug кириллицы | безопасность `f49d722`; длина и гонки — `fd53df3`; общий хелпер — `6e6ae6b` |
| P-04, P-05 длина slug, гонка | `fd53df3` (усечение под `max_length`, повтор при `IntegrityError`, случайный суффикс) |
| P-06 свежая установка | безопасность (`first()`/`get_or_create`); тесты зелёные |
| P-07, P-08 черновики, `publish_at` | безопасность `c8bc5e0` (`Article.objects.public()`) |
| P-09 отложенные статьи | `4b60bfc` (видимость по времени, миграция 0010, внешний планировщик не нужен) |
| P-10, P-19 удаление и каскады | безопасность `4581242` (POST); `a3cabba` (`SET_NULL`, миграция 0011) |
| P-11, P-12 боты, методы | `efb9d39` |
| P-13, P-49 вход | безопасность (`LOGIN_URL`); `24c9ea7` (`?next`) |
| P-14, P-28 ввод редактора | безопасность `c8bc5e0`; `4890b16` |
| P-15, P-16, P-20 комментарии, циклы | `423ccda` |
| P-17 транзакции, сбой хранилища | безопасность + `f3845b5` (503 с сообщением) |
| P-18, P-51 перезапись при правке | `4890b16` (`update_fields`) |
| P-21 глубокие ветки | безопасность (ограничение глубины) |
| P-22, P-23 порядок | `cb5584b` |
| P-24 пагинация | `cb5584b` (списки по 24), `92264f0` (комментарии по 20 веток) |
| P-25 поиск | `cb5584b`, `73c7b57` (поле `search_text`, миграция 0015) |
| P-26 N+1 в кабинете | `cbea687` |
| P-27 `utf8mb3` | `496f71b` (+ Django 5.2) |
| P-29 индексы | `87a7055` (три составных, миграция 0012) |
| P-30, P-32, P-41 картинки | `2b473c9` (`image_url` с запасным вариантом) |
| P-31 старые URL | `0e2759c` (301 по id и по прежним slug, миграция 0013) |
| P-33 JS | `972bef4` |
| P-34 «Відповісти» | `428a79f` |
| P-35, P-55 a11y, капча | `aa76f2c` |
| P-36 SEO | `22b119d` (мета-теги, микроразметка, sitemap, RSS, `Site` в миграции 0014) |
| P-37 язык | `e36124d`, `2902bb0` |
| P-38 BOM | `1db537c`, `6e6ae6b` |
| P-39, P-46 внешние ресурсы | `29ee50d` |
| P-40 эксплуатация | `a6ff7c8` (404/500), `3d1c86f` (`/healthz`, `robots.txt`), `9498223` (503, устойчивость кэша), `b60bcb5` (логи); `DEBUG` из окружения — безопасность |
| P-42 миграция 0007 | `6e6ae6b` |
| P-43 кэш меню | `5f76c93` (TTL 60 с; смягчение, не общий кэш) |
| P-44 развёртывание | `59b3e66` (`release:`, gunicorn); зависимости и Python 3.12 — безопасность `3041e75` |
| P-45 мусор в репозитории | `1bfffe5` (`fill_slugs.py`); артефакты — безопасность `bda609b` |
| P-47 двойная отправка | `c83fd68` |
| P-48 часовой пояс | `24c9ea7` (`EDITOR_TIME_ZONE`) |
| P-50 тестовый хелпер | `44b76a8` |
| P-52 подмена типа файла | безопасность `e8a8f7b` |
| P-53, P-54 варианты URL | `92264f0` |

**Решения, которые я принял сам (вы не ответили на вопросы раздела 15):**
- Целевой Django — 5.2 (так уже сделал аудит безопасности).
- Отложенная публикация: `is_published=True` + будущая `publish_at`; `False` теперь значит «скрыта».
- Пагинация страницами `?page=`; слеш-варианты `/about-us/`, `/authors/`, `/all/` редиректят на канонический адрес.
- Код языка `ua` остаётся внутренним (он в БД и в cookie посетителей); наружу (`<html lang>`, `Content-Language`, RSS) идёт `uk`.
- Структурированные данные — микроразметка Schema.org, а не JSON-LD: набор безопасности запрещает пользовательский текст внутри `<script>`.
- Уточнено при исправлении: гипотеза о несовместимости загрузчика CKEditor 5 и CKEditor 4 не подтвердилась, тест удалён; индекс комментариев `(article, created_at)` не добавлен (выигрыш 36→30 мс).

**Не сделано или сделано частично:**
- Общий кэш между воркерами (Redis): для этого нужна инфраструктура и зависимость; сейчас только TTL 60 с (P-43).
- Sentry: нет DSN; логи идут в stdout.
- Чистая установка `requirements.txt` и сборка на Heroku не перепроверялись (после обновлений аудита безопасности).
- Не пересняты числа нагрузки (раздел 5), Lighthouse и axe: проверено только отсутствие ошибок JS и дублей `id` в браузерах. Их надо повторить теми же скриптами перед запуском.
- Исправление уже существующих данных не выполнялось: пустые/числовые slug (запрос в разделе 13), статьи с `is_published=False` и `publish_at` в прошлом остаются скрытыми, их нужно просмотреть вручную.
- Регистронезависимый поиск кириллицы на SQLite невозможен (ограничение `LIKE`); тест помечен как MySQL-only.
- Миграции 0010–0015 нужно прогнать на копии боевой БД перед релизом: на пустых и тестовых базах они проходят.
