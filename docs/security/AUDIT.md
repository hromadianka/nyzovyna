# Аудит безопасности «Низовина» (nyzovyna)

Дата: 2026-11-02. Область: локальный код репозитория, SQLite in-memory, `anarchia/settings_test.py`. К боевому сайту, Heroku, Cloudinary, MySQL и GitHub запросов не делалось. Исключение: `pip-audit` обращается к публичным базам уязвимостей (PyPI/OSV) за списком advisories по пакетам, обращений к проекту при этом нет.

Карта приложения и матрица «эндпоинт × угроза» — в [RECON.md](RECON.md).

## 1. Резюме

- **606 новых тестов** в `app/security_tests/` (9 модулей, группы A–I). Каждый тест описывает желаемое безопасное поведение, красный тест означает подтверждённую уязвимость.
- **271 тест красный** (335 красных записей с учётом `subTest`), **335 зелёных**. Существующие 24 теста `app/test_findings.py` остаются зелёными.
- Найдено **23 находки**: 7 High, 11 Medium, 3 Low, 2 Info (раздел 2). Часть гипотез не подтвердилась (раздел 4).
- Самое срочное, не требующее кода: **ротация секретов** (SECRET_KEY, reCAPTCHA private, Cloudinary API key/secret) и решение по закоммиченной `db.sqlite3` с двумя суперпользователями. Удаление из репозитория не отзывает уже скомпрометированное, секреты остаются в истории (NYZ-001, NYZ-002).
- Самые опасные дефекты приложения: хранимый XSS в `article.text` без серверной санитизации (NYZ-003), отсутствие проверки роли `Editor` (NYZ-004), анонимная порча страницы цепочкой ответов без капчи (NYZ-010), `DEBUG = True` в проде (NYZ-008).
- Хорошее: CSRF защищает все 11 POST-эндпоинтов, SQL-инъекций нет (ORM везде), `striptags`-карточки устойчивы к 12 нагрузкам, user enumeration и open redirect не воспроизводятся, черновики не попадают в поиск, RSS и sitemap.

### Результаты по группам

| Группа | Тем | Тестов | Красных | Зелёных | Красных записей с `subTest` |
|--------|-----|--------|---------|---------|-----------------------------|
| A. CSRF | `test_a_csrf.py` | 71 | 7 | 64 | 7 |
| B. Аутентификация и доступ | `test_b_authz.py` | 96 | 36 | 60 | 36 |
| C. XSS | `test_c_xss.py` | 47 | 12 | 35 | 66 |
| D. Инъекции и валидация | `test_d_input.py` | 112 | 50 | 62 | 52 |
| E. Загрузка файлов | `test_e_uploads.py` | 93 | 58 | 35 | 61 |
| F. Конфигурация и секреты | `test_f_config.py` | 55 | 31 | 24 | 36 |
| G. Раскрытие и бизнес-логика | `test_g_logic.py` | 53 | 24 | 29 | 24 |
| H. DoS и ресурсы | `test_h_dos.py` | 36 | 12 | 24 | 12 |
| I. Зависимости | `test_i_dependencies.py` | 43 | 41 | 2 | 41 |
| **Итого** | | **606** | **271** | **335** | **335** |

Запуск:

```
DJANGO_SETTINGS_MODULE=anarchia.settings_test PYTHONDONTWRITEBYTECODE=1 \
  /opt/homebrew/Caskroom/miniconda/base/envs/nyz/bin/python manage.py test app.security_tests app.test_findings -v 2
```

Полный прогон: `Ran 630 tests, FAILED (failures=335)`, все 335 относятся к `security_tests`. Один прогон занимает около 43 с.

`anarchia/settings_test.py` расширен: временный `MEDIA_ROOT` (загрузки не пишут в отслеживаемый `media/`) и MD5-хешер (перебор паролей в тестах быстрый). `anarchia/settings.py` не менялся.

## 2. Таблица находок

| ID | Название | Серьёзность (CVSS-подобная) | Тесты (красные) |
|----|----------|------------------------------|-----------------|
| NYZ-001 | Секреты в репозитории и истории git | High 7.5 | 12 |
| NYZ-002 | Закоммичены `db.sqlite3` (суперпользователи, хеши, сессии), `.pyc`, `.vs/`, `.idea/` | High 7.4 | 11 |
| NYZ-003 | Хранимый XSS: `article.text`, about-us, RSS, oembed | High 7.3 | 12 методов / 66 записей |
| NYZ-004 | Нет проверки роли Editor: любой залогиненный управляет контентом | High 7.1 (латентно) | 23 |
| NYZ-005 | Удаление статей и категорий по GET | Medium 6.5 | 4 |
| NYZ-006 | Комментарии: капча не требуется для ответов, нет лимитов и валидации длины | Medium 5.3 | 7 |
| NYZ-007 | Черновики и отложенные публикации доступны публично | Medium 5.3 | 10 |
| NYZ-008 | `DEBUG = True` в продакшене | High 7.5 | 4 |
| NYZ-009 | `ALLOWED_HOSTS` фактически `['*']` | Medium 5.3 | 4 |
| NYZ-010 | DoS: рекурсия комментариев и категорий, циклы категорий | High 7.5 | 7 |
| NYZ-011 | Нет защиты от перебора паролей (`/login/`, `/admin/login/`) | Medium 5.9 | 3 |
| NYZ-012 | Кириллическое название категории даёт пустой slug и 500 на всех страницах | Medium 6.5 | 3 метода / 4 записи |
| NYZ-013 | Необработанные исключения и приём некорректного ввода: 35 сценариев дают 500, 9 принимаются и сохраняются | Medium 5.3 | 47 |
| NYZ-014 | Загрузка изображений проверяет только `Content-Type` клиента | Medium 6.0 | 54 |
| NYZ-015 | CKEditor-загрузчик: `csrf_exempt`, любые типы файлов, без лимита, bomb → 500 | Low 3.7 | 5 |
| NYZ-016 | Нет rate limiting и лимитов: поиск, счётчик просмотров, пакетное обновление порядка | Low 4.3 | 9 |
| NYZ-017 | Анонимный редирект двух вью ведёт на несуществующий `/accounts/login/` | Info 2.0 | 2 |
| NYZ-018 | Нет CSP и Permissions-Policy | Medium 5.0 | 6 |
| NYZ-019 | Сессии: подписанные cookie без серверного отзыва, нет Secure-флагов, нет маршрута выхода | Medium 5.4 | 7 |
| NYZ-020 | Уязвимые версии зависимостей: 262 advisories в 16 пакетах | High 7.5 | 16 |
| NYZ-021 | Лишние и незакреплённые пакеты, Python 3.13 для Django 4.2 | Low 4.0 | 21 |
| NYZ-022 | Сторонние скрипты без SRI, jQuery 2.1.1, CKEditor 4.22.1 | Medium 5.4 | 4 |
| NYZ-023 | Усиление защиты: CSRF не привязан к сессии, нет Cache-Control, мёртвый маршрут | Info | 3 |

Оценки CVSS приблизительные: векторы условны, не вычислялись калькулятором, предположения (публичность репозитория, переиспользование ключей в проде) указаны в тексте и **не проверялись**.

## 3. Подробности

Формат: файлы и строки, воспроизведение, тесты, рекомендация. Значения секретов замаскированы (первые 4 символа).

### NYZ-001. Секреты в репозитории и истории git (High)

- `anarchia/settings.py:32` `SECRET_KEY = 'djan***'` (с коммита `32d2acb`, 2024-04-14, префикс `django-insecure-`).
- `anarchia/settings.py:215` `RECAPTCHA_PRIVATE_KEY = '6LfA***'` (с `f18f0f3`, 2026-01-19).
- `anarchia/settings.py:186` Cloudinary `API_KEY = '3672***'` (с `88f945f`, 2026-08-29).
- Cloudinary `API_SECRET` был литералом в `settings.py` в коммитах с `0ca581b` (2024-04-14) до удаления в `0f039b0` (2024-08-22), значение `CJ_I***` осталось в истории.
- Воспроизведение: `git log --all -p -- anarchia/settings.py` или тесты ниже.
- Тесты: `test_f_config.SecretsInRepository.test_not_in_tracked_files__{django_insecure_secret_key,recaptcha_private_key,cloudinary_api_key}`, `test_not_in_git_history__{django_insecure_secret_key,recaptcha_private_key,cloudinary_api_key,cloudinary_api_secret}`; `ProductionSettings.test_secret_key_is_not_hardcoded`, `test_secret_key_is_strong`, `test_recaptcha_private_key_is_not_hardcoded`, `test_cloudinary_credentials_are_not_hardcoded`; `CommittedArtefacts.test_pyc_files_do_not_embed_secrets`.
- Эффект: знание `SECRET_KEY` позволяет подделывать сессии (см. NYZ-019). `django_heroku.settings()` подставляет `SECRET_KEY` из переменной окружения, если она задана: **не проверено**, переопределён ли ключ на Heroku.
- **Не проверено:** публичность репозитория `hromadianka/nyzovyna` (обращение к GitHub запрещено ограничением 1).
- Рекомендация: считать все четыре значения скомпрометированными и ротировать; читать из `os.environ`; решение по очистке истории (`git filter-repo` и force-push) принимает владелец. Очистка не заменяет ротацию.

### NYZ-002. Закоммичены база, байткод и IDE-файлы (High)

- `db.sqlite3` в HEAD (первый коммит 2024-04-14): 2 учётные записи, **обе суперпользователи**, PBKDF2-хеши паролей (`pbkdf2_sha256$600000…`), e-mail, похожий на реальный (в отчёте не приводится), 9 строк `django_session`. Таблицы комментариев и `app_editor` пусты.
- 61 файл `.pyc` отслеживается, включая `anarchia/__pycache__/settings.cpython-311.pyc`, куда скомпилированы секреты. Файл перечислен в `.gitignore`, но закоммичен.
- `anarchia/settings.py` перечислен в `.gitignore`, но отслеживается (ложное чувство защиты).
- Отслеживаются `.vs/` (в т.ч. `slnx.sqlite`, `.suo`), `.idea/`, `staticfiles/` (вывод `collectstatic`), `media/` (7 файлов, EXIF с GPS нет).
- `.gitignore` из трёх строк не содержит `__pycache__`, `*.pyc`, `.env`, `*.sqlite3`, `.idea`, `.vs`.
- Тесты: `test_f_config.CommittedArtefacts.test_committed_database_has_no_{user_accounts,password_hashes,personal_data,privileged_accounts,sessions}`, `test_no_bytecode_is_tracked`, `test_no_database_file_is_tracked`, `test_no_ide_state_is_tracked`, `test_gitignored_settings_file_is_not_tracked`, `test_ignored_bytecode_of_settings_is_not_tracked`, `test_gitignore_covers_secrets_and_artefacts`.
- Рекомендация: `git rm --cached`, расширить `.gitignore`, сменить пароли обеих учётных записей, считать e-mail раскрытыми персональными данными; хеши в истории остаются доступными для офлайн-подбора.

### NYZ-003. Хранимый XSS (High)

- `templates/article.html:64` `{% autoescape off %}{{ article.text|safe }}`; `templates/about-us.html:10,12` `autoescape off`; `app/feeds.py:20` отдаёт `item.text` как описание RSS; `article.html:182-194` JS превращает `<oembed url>` в `iframe.src` без проверки схемы (`javascript:` исполняется).
- На сервере санитизации нет (`views.py:210`, `:331`, `:413` сохраняют вход как есть).
- Воспроизведение: сохранить `<img src=x onerror=…>` в тексте статьи через `/publish`, открыть `/article/<slug>/` (все 12 нагрузок из набора срабатывают).
- Тесты: `test_c_xss.StoredXssInRawFields.test_article_body_on_article_page`, `test_about_us_text`, `test_rss_description_is_inert_html`, `test_oembed_url_scheme_is_restricted`, `test_article_text_is_sanitised_before_storage_via_publish`, `test_about_us_is_sanitised_before_storage`; `StoredXssInEscapedFields`-тест `test_templates_do_not_disable_escaping_for_unsanitised_fields`.
- Усиливается NYZ-004 (писать может любой залогиненный) и NYZ-018 (нет CSP).
- Рекомендация: allowlist-санитайзер при сохранении и/или выводе (bleach, nh3), список тегов CKEditor без `script`, обработчиков `on*`, `javascript:`/`data:` в `href/src/url`; для oembed разрешать только `https://` и известные хосты.

### NYZ-004. Нет проверки роли Editor (High, латентно)

- `app/views.py`: все редакторские вью под `@login_required` (строки 188, 203, 294, 301, 316, 323, 410, 422, 442, 462, 468, 476, 484), модель `Editor` во вью не используется.
- Воспроизведение: залогиниться обычным пользователем без записи `Editor` (создаётся в админке) и вызвать любой из 19 привилегированных методов: удаление статей, комментариев, правка контента, `about-us`.
- Тесты: `test_b_authz.PrivilegedAccess.test_regular_user_without_editor_role_is_forbidden__*` (19), `RoleEscalation.test_regular_user_cannot_delete_article`, `test_regular_user_cannot_rewrite_article`, `test_regular_user_cannot_delete_comments`, `test_regular_user_can_not_read_unpublished_list`; тест целостности ответов `test_comment_reply_cannot_attach_to_a_comment_of_another_article` учтён в NYZ-006.
- Серьёзность зависит от наличия не-редакторских аккаунтов: регистрации в приложении нет, в закоммиченной базе `app_editor` пуст.
- Рекомендация: декоратор/миксин `editor_required` (проверка `Editor` или группы/permission), 403 вместо редиректа для залогиненных без роли.

### NYZ-005. Удаление по GET (Medium)

- `views.py:295-299` (`delete_article`), `:317-321` (`delete_category`): `if request.method == 'GET': …delete()`; UI делает `fetch(url)` (`editor-cabinet.html:326,347`).
- Каскад: удаление категории удаляет подкатегории (`on_delete=CASCADE`).
- Нюанс: cookie сессии `SameSite=Lax` (дефолт Django) защищает от `<img>`/`fetch` с чужого сайта, но не от top-level навигации (ссылка, `location=`). Гипотеза про «картинку» верна лишь частично.
- Тесты: `test_a_csrf.GetNeverChangesState.test_editor_get_is_read_only__{delete_article,delete_category}`, `test_cross_site_get_cannot_delete__{delete_article,delete_category}`.
- Побочно (NYZ-013): POST/другие методы на эти вью возвращают `None` → 500.
- Рекомендация: `@require_POST` (или DELETE) + CSRF-токен в `fetch`; на других методах 405. Подтверждение удаления должно быть на сервере.

### NYZ-006. Комментарии (Medium)

- `views.py:118-122` капча проверяется только при пустом `parent_comment_id`; ответы создают комментарий без капчи (`:127-134`).
- Нет лимита частоты: 40 ответов подряд приняты (`test_reply_flood_is_rate_limited`), корневые тоже при валидной капче (`test_root_comment_flood_is_rate_limited`).
- Нет валидации: `author` до `max_length=100` (SQLite не проверяет, MySQL strict даст 500), текст до 2,5 МБ, пустые/пробельные значения.
- `parent_comment` не проверяется на принадлежность той же статье, на комментарий к черновику (NYZ-007).
- Тесты: `test_g_logic.CommentAbuse.test_reply_requires_captcha`, `test_reply_flood_is_rate_limited`, `test_root_comment_flood_is_rate_limited`, `test_author_length_is_validated`, `test_text_length_is_limited`, `test_blank_comments_are_refused`; `test_b_authz.RoleEscalation.test_comment_reply_cannot_attach_to_a_comment_of_another_article`; `test_d_input.MalformedInput` (`comment_reply_*`).
- Зелёное: корневой комментарий без капчи не создаётся; HTML в имени и тексте экранируется; рассылки писем в коде нет (`send_mail` не найден).
- Рекомендация: капча на всех комментариях, `Form` с `max_length`/`strip`, проверка `parent.article_id == article.id`, лимит частоты по IP/сессии.

### NYZ-007. Черновики и отложенные публикации (Medium)

- `views.py:64` `article_detail` берёт статью по slug без фильтра: черновик (`is_published=False`) и отложенный пост (`publish_at` в будущем) открываются любому. Шаблон даже содержит класс `unpublished` (`article.html:51`), то есть предпросмотр задуман, но не ограничен редакторами.
- Статьи с `is_published=True` и будущей `publish_at` попадают на `/`, `/all`, `/category/…`, `/authors/<slug>` (`views.py:26-33, 48-52, 57-60, 148-151`) и в боковой список статьи; поиск, RSS и sitemap фильтруют по `publish_at__lte=now()`.
- Комментарии к черновикам принимаются, что подтверждает существование UUID.
- Тесты: `test_g_logic.UnpublishedContent.test_direct_url_is_not_public__{draft,scheduled}`, `test_anonymous_cannot_see__{index,all_articles,category_page,subcategory_page,author_page,other_article_sidebar}__scheduled`, `test_comment_on_unpublished_is_refused__{draft,scheduled}`.
- Зелёное: поиск, RSS и sitemap не раскрывают ни черновики, ни отложенные; редактор по-прежнему может смотреть предпросмотр.
- Рекомендация: общий `Article.objects.public()` (`is_published=True` и `publish_at__lte=now()`), в `article_detail` — 404 для всех, кроме Editor.

### NYZ-008. `DEBUG = True` в продакшене (High)

- `anarchia/settings.py:35`. `manage.py check --deploy` с боевым модулем: `security.W018`.
- Эффект: на 404 показывается список всех маршрутов (admin, ckeditor, editor-cabinet…), на 500 — трейсбек с путями, исходным кодом и локальными переменными; `anarchia/urls.py` при `DEBUG` отдаёт `STATIC_ROOT` и `MEDIA_ROOT` через приложение.
- Тесты: `test_f_config.ProductionSettings.test_debug_is_disabled`; `test_g_logic.ErrorPages.test_404_does_not_reveal_url_map_with_production_debug`, `test_500_does_not_reveal_paths_with_production_debug`, `test_debug_static_serving_is_off_in_production`. Зелёные проверки: при `DEBUG=False` 404/500 типовые, без стека и путей.
- Рекомендация: `DEBUG = os.environ.get('DEBUG') == '1'`, по умолчанию False; проверить логирование без утечек.

### NYZ-009. `ALLOWED_HOSTS` фактически `['*']` (Medium)

- `settings.py:37` задаёт список, но `settings.py:179` `django_heroku.settings(locals())` по умолчанию (`allowed_hosts=True`) заменяет его на `['*']`. Проверено импортом: эффективное значение `['*']`.
- Эффект: Host-header injection; цепочка с `set_language`: при `Host: evil.example` и `next=https://evil.example/x` Django считает хост «своим» и отдаёт редирект на него (`test_host_header_cannot_turn_set_language_into_open_redirect`). Для эксплуатации нужен контроль над заголовком Host (не браузерный сценарий).
- Тесты: `test_b_authz.HostHeader.test_unknown_host_is_rejected_with_production_allowed_hosts`, `test_host_header_cannot_turn_set_language_into_open_redirect`; `test_f_config.ProductionSettings.test_allowed_hosts_has_no_wildcard`, `test_explicit_allowed_hosts_survive_django_heroku`.
- Рекомендация: `django_heroku.settings(locals(), allowed_hosts=False)` (или убрать вызов и настроить нужное явно).

### NYZ-010. DoS: рекурсия и циклы (High)

- Комментарии: `templates/comment.html:28` рекурсивно включает сам себя; глубина ответов между 100 (ещё 200) и 160 (уже 500) ломает рендер страницы статьи; 300 тоже 500. Ответы не требуют капчи (NYZ-006), поэтому **аноним** одним скриптом выводит страницу статьи из строя навсегда. Тест через HTTP: `test_h_dos.AnonymousCanBreakArticlePage` (160 ответов).
- Категории: `recursive_menu.html` рекурсивен; цепочка 100 уровней даёт 500 на **каждой** странице (меню в `base.html`). Создать цепочку может редактор (`create_category` с `parent_id`).
- Циклы: модель `Category` не запрещает `parent=self`. Цикл вешает `article_detail` (`views.py:85`, `while parent_of.get(parent_category)`) и `publish` (`:243-246`), тест останавливает запрос через 3 с (`Deadline`). Бесконечный цикл блокирует воркер до таймаута gunicorn.
- Тесты: `test_h_dos.DeepStructures.test_category_tree_depth_does_not_break_pages__depth_{100,300}`, `test_comment_thread_depth_does_not_break_article__depth_300`, `AnonymousCanBreakArticlePage`, `Cycles.test_model_rejects_category_as_its_own_ancestor`, `test_article_page_survives_category_cycle`, `test_publish_survives_category_cycle`.
- Рекомендация: ограничить глубину ответов (например 3–5) на сервере и вынести рендер в итеративный; валидация `Category.clean()` (нет циклов, максимальная глубина); итеративный обход с защитой от повторов.

### NYZ-011. Нет защиты от перебора паролей (Medium)

- `views.py:176-186`, `/admin/login/`: 30 неверных паролей подряд, затем верный пароль входит.
- Зелёное: сообщения об ошибке одинаковы для существующего, несуществующего и отключённого пользователя; для несуществующего выполняется фиктивное хеширование (нет утечки по времени, проверено наличием вызова, не измерением).
- Тесты: `test_b_authz.LoginHardening.test_login_is_throttled_after_repeated_failures`, `test_correct_password_is_refused_while_locked_out`, `test_admin_login_is_throttled`.
- Рекомендация: django-axes или собственный счётчик по IP+логину в кэше/БД; `LocMemCache` у нескольких воркеров считает отдельно, нужен общий бэкенд.

### NYZ-012. Кириллическое название категории ломает весь сайт (Medium)

- `models.py:53-62` строит slug из `slugify(name_ua)`; для кириллицы результат пустой строкой `''` (уникален, поэтому сохраняется). `views.py:309-312` не задаёт slug. `base.html:31-33` вызывает `{% url 'category_articles' category.slug %}` → `NoReverseMatch` → 500 на `/`, на странице статьи, на `/authors` и остальных.
- Воспроизведение: создать категорию «Культура» через `/create-category/`. На SQLite воспроизведено. `Author.save` с пустым именем на латинице аналогично (slug автора пуст).
- Тесты: `test_d_input.NonAsciiNames.test_cyrillic_category_gets_a_routable_slug`, `test_site_survives_cyrillic_category_created_by_editor` (3 страницы), `test_cyrillic_author_gets_a_routable_slug`.
- Не проверено: как устроены уже существующие категории в проде (slug мог быть задан скриптом `fill_slugs.py` из `name_en`).
- Рекомендация: транслитерация (`slugify(..., allow_unicode=True)` с конвертером `<str:slug>` или transliterate), fallback `category-<n>`; защита меню от `NoReverseMatch`.

### NYZ-013. Необработанные исключения на мусорном вводе (Medium)

- 35 сценариев возвращают 500 вместо 4xx, ещё 9 принимают и сохраняют заведомо некорректный ввод (длины 101 символ, `language` вне choices, `order` > 2^31, пустые и мегабайтные комментарии); `MissingSingletons` добавляет ещё 3 сценария 500. Причины: `get_object_or_404`/`.get()` с не-UUID (ValidationError), `strptime` без обработки (`views.py:252, 368`), поля `None` в `NOT NULL` (`name`, `author`, названия), `json.loads` без проверок (`:487`), метод POST на «GET-only» вью (`delete_*`, `about_us_edit`), `AboutUsText.objects.get(pk=1)` при отсутствии строки (`:38, 192, 415`), `create_new_author` без файла (`image=None`, `:429-436`).
- Часть сценариев на SQLite принимается, на MySQL strict даст 500/DataError (длины 101 символ, `order` > 2^31, `language` длиннее 2): тест считает приём некорректного значения дефектом.
- Тесты: `test_d_input.MalformedInput.test_never_a_server_error__*` (44 красных: 35 + 9 принятых, список — в выводе прогона), `MissingSingletons.*`.
- Зелёное: slug 5000 символов, null-байт в пути, невалидный UTF-8, юникод в `q`, 3 МБ тело (400 из-за `DATA_UPLOAD_MAX_MEMORY_SIZE`), мусорный UUID в URL — 404.
- Рекомендация: `Form`/`ModelForm` + `full_clean()`, `try/except ValueError, ValidationError`, `@require_http_methods`.
- Не воспроизведено: `TooManyFieldsSent` (1500 GET-параметров) в тестовой среде падает при логировании `AdminEmailHandler`, что связано с `DEBUG=False` и в боевой (где `DEBUG=True`) не проявится; результат не засчитан.

### NYZ-014. Загрузка изображений (Medium)

- `views.py:277`, `:385` проверяют `article_image.content_type.startswith('image')`, значение приходит от клиента. `create_new_author` (`:429`) и `edit_author` (`:450-457`) не проверяют вообще.
- Принимаются: HTML и SVG под видом PNG, `image/svg+xml`, `shell.php` с типом `image/gif`, `.php.png`, `x.png.php`, `.html`/`.exe` с типом image, обрезанный PNG, 0 байт, 11 МБ, PNG с заявленным размером 100000×100000 (decompression bomb: Pillow отказывается его открыть, сервер файл не открывает). Расширение сохраняется как у клиента.
- Тесты: `test_e_uploads.ModelImageUploads.test_hostile_upload_is_rejected__{publish,edit_article,create_new_author,edit_author}__*` (4×12 = 48), `test_filename_cannot_escape_media_root__*__unicode_rtl_override` (4), `test_non_image_content_type_is_refused__{edit_author,create_new_author}`.
- Зелёное: `../`, `..\`, абсолютные пути, null-байт, 300-символьные имена не выходят за `MEDIA_ROOT` (Django санирует имя); валидный PNG принимается.
- В проде файлы уходят в Cloudinary (другой origin), что снижает риск stored XSS через `.html`/`.svg`, но **не проверялось** (запрещено ограничением 1).
- Рекомендация: валидация содержимого (Pillow `verify()`, лимит пикселей), allowlist расширений `jpg/jpeg/png/gif/webp`, лимит размера (например 5 МБ), проверка через `forms.ImageField`.

### NYZ-015. CKEditor-загрузчик (Low)

- `ckeditor_uploader.urls` оборачивает `upload` в `csrf_exempt`; `CKEDITOR_ALLOW_NONIMAGE_FILES` по умолчанию True: принимаются `.html`, `.svg`, `.php`; нет лимита размера; PNG-бомба даёт 500 (Pillow открывает файл).
- Ограничение: доступ только staff (аноним, обычный пользователь и редактор без `is_staff` получают 302); `SameSite=Lax` блокирует кросс-сайтовый POST.
- Тесты: `test_e_uploads.CkeditorEndpoints.test_upload_requires_csrf_token`, `test_non_image_files_are_refused` (4 типа), `test_decompression_bomb_is_handled`, `test_oversized_upload_is_refused`; `test_a_csrf.CsrfExemptions.test_no_installed_state_changing_route_is_csrf_exempt`.
- Рекомендация: `CKEDITOR_ALLOW_NONIMAGE_FILES = False`, обёртка с CSRF и лимитами, либо замена CKEditor 4 (NYZ-022).

### NYZ-016. Лимиты и усиление нагрузки (Low)

- Поиск (`views.py:155-172`): `icontains` по тексту статей без индекса; длина `q` не ограничена (4000 символов проходят), нет троттлинга (120 запросов подряд обработаны). ReDoS отсутствует (регулярок нет, `%` экранируется).
- Счётчик просмотров (`views.py:65`): растёт на каждый GET, включая HEAD и ботов; один клиент поднимает статью в «популярные». Обновление атомарно (F-выражение).
- `update_category_order` (`views.py:486-494`): один UPDATE на элемент (304 запроса на 300 категорий), число элементов не ограничено, вложенный JSON `[[[[…` даёт 500 (RecursionError).
- N+1 на `comments_moderation` (124 запроса на 81 комментарий).
- Тесты: `test_h_dos.BulkAndSearch.test_category_order_update_is_batched`, `test_deeply_nested_json_is_a_client_error`, `test_search_query_length_is_capped`, `test_search_is_throttled`; `QueryBudget.test_editor_page_query_count_is_bounded__comments_moderation`; `test_g_logic.ViewCounter.test_repeated_requests_from_one_client_count_once`, `test_head_requests_do_not_count`, `test_crawlers_do_not_inflate_views`, `test_popular_list_cannot_be_hijacked_by_one_client`.
- Зелёное: все 9 публичных страниц укладываются в лимиты запросов (после предыдущих исправлений `test_findings`); огромное тело JSON отсекается 400.
- Рекомендация: `bulk_update` или один `Case/When`, лимит длины `q` (например 100), троттлинг (кэш-бэкенд, общий для воркеров), `select_related('article')` в модерации, счёт просмотров по сессии/IP с TTL.

### NYZ-017. Редирект двух вью на несуществующий логин (Info)

- `views.py:476, 484` используют `@login_required` без `login_url`, `LOGIN_URL` не задан → `/accounts/login/` (404). Аноним ничего не получает, данные не раскрываются, но UX ломается.
- Тесты: `test_b_authz.PrivilegedAccess.test_anonymous_is_redirected_to_a_working_login__{get_category_order_editor,post_update_category_order}`.
- Зелёное: остальные 17 привилегированных методов ведут на рабочий логин (через `/login` → `/login/`), `next` не отражается и не используется (open redirect отсутствует).
- Рекомендация: `LOGIN_URL = 'login'` в settings и убрать `login_url` из декораторов.

### NYZ-018. Нет CSP и Permissions-Policy (Medium)

- Ответы не содержат `Content-Security-Policy` ни на одной из 4 проверенных страниц, а также `Permissions-Policy`. Усиливает NYZ-003 и NYZ-022 (inline JS в шаблонах нужно перевести в файлы или использовать nonce).
- Тесты: `test_c_xss.BrowserSideDefences.test_content_security_policy_header_present__{index,article,login,category}`, `HeaderValues.test_csp_blocks_inline_script_and_foreign_origins`; `test_f_config.ResponseHeaders.test_permissions_policy_present`.
- Зелёное: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, `Strict-Transport-Security` (`max-age=31536000; includeSubDomains`, preload) присутствуют на HTTPS-ответах.
- Рекомендация: `django-csp` или middleware, начать с `Content-Security-Policy-Report-Only`.

### NYZ-019. Сессии (Medium)

- `settings.py:218` `signed_cookies`: сессию нельзя отозвать на сервере. Разлогин через `/admin/logout/` не обесценивает украденную cookie. Тест: `test_session_is_revoked_server_side_on_logout`.
- Подделка: имея `SECRET_KEY` из репозитория (NYZ-001) и хеш пароля из закоммиченной БД (NYZ-002), можно собрать cookie редактора вручную: `test_session_cannot_be_minted_with_the_secret_key_from_the_repository`.
- `SESSION_COOKIE_SECURE` и `CSRF_COOKIE_SECURE` не заданы (`security.W012`, `W016`); HSTS и SSL-редирект смягчают, но не отменяют.
- В приложении нет маршрута выхода (`test_app_provides_a_logout_route`).
- Тесты: `test_b_authz.SessionLifecycle.*` (красных 5), `test_f_config.ProductionSettings.test_session_and_csrf_cookie_flags` (2 записи), `test_session_engine_allows_server_side_revocation`.
- Зелёное: `HttpOnly`, `SameSite=Lax`, подмена/порча cookie отвергается, смена пароля и деактивация обнуляют сессию, при входе выдаётся новая cookie, CSRF-токен ротируется при входе, срок жизни 2 недели.
- Рекомендация: `SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'` (или `db`), `SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True`, маршрут `logout` (POST).

### NYZ-020. Уязвимые зависимости (High)

`pip-audit -r requirements.txt --no-deps --disable-pip` (строка `mysqlclient>=2.0` исключена: не закреплена, не проверялась): **262 известных advisory в 16 пакетах**. Эксплуатируемость в этом проекте по каждому CVE не оценивалась.

| Пакет | Версия | Advisories | Минимальная версия без известных advisory |
|-------|--------|-----------|-------------------------------------------|
| Django | 4.2.4 | 91 | 4.2.30 (линия 4.2 LTS) |
| Pillow | 12.1.0 | 76 | 13.0.0 |
| urllib3 | 1.26.16 | 18 | 2.8.0 (в линии 1.26 – 1.26.19) |
| cryptography | 41.0.4 | 16 | 49.0.0 |
| pyasn1 | 0.5.0 | 12 | 0.6.5 |
| sqlparse | 0.4.4 | 12 | 0.6.0 |
| requests | 2.29.0 | 8 | 2.33.0 |
| jwcrypto | 1.5.0 | 6 | 1.5.7 |
| certifi | 2023.7.22 | 4 | 2026.10.18 |
| gunicorn | 21.2.0 | 4 | 22.0.0 |
| idna | 3.4 | 4 | 3.15 |
| protobuf | 4.24.4 | 4 | 6.33.5 |
| setuptools | 80.9.0 | 3 | 84.1.0 |
| httplib2 | 0.22.0 | 2 | 0.32.0 |
| pycryptodome | 3.19.0 | 1 | 3.19.1 |
| wheel | 0.45.1 | 1 | 0.46.2 |

- Для `Pyrebase4`, `gcloud`, `Radicale`, `python-jwt`, `rethinkdb`, `python-firebase`, `vobject`, `passlib` pip-audit advisories не нашёл; проблема этих пакетов в другом (NYZ-021).
- Окружение `nyz` отличается от `requirements.txt` (например, Pillow 13.0.0 вместо 12.1.0, requests 2.34.2), поэтому уязвимости закреплённых версий тестами выполнения не воспроизводятся: красные тесты сравнивают закреплённые версии с таблицей выше.
- Тесты: `test_i_dependencies.KnownVulnerableVersions.test_pinned_version_has_no_known_advisories__*` (16).
- Рекомендация: обновить как минимум Django (4.2.30), Pillow, gunicorn, requests, urllib3, cryptography; прогнать полный набор; включить `pip-audit` в CI.

### NYZ-021. Лишние и незакреплённые пакеты (Low)

- Не импортируются проектом (в окружении `nyz`, на котором приложение и все тесты работают, их тоже нет): Pyrebase4, gcloud, python-firebase, python-jwt, Radicale, rethinkdb, oauth2client, vobject, passlib, pybind11, django-storages, boto3, google-cloud-storage, Markdown, looseversion, jwcrypto, mysqlclient (17 тестов). Часть из них — транзитивные зависимости этой же группы (Pyrebase4 → gcloud, python-jwt, oauth2client, pycryptodome и др.), часть тянет django-heroku (psycopg2, dj-database-url) и в список «лишних» не вошла.
- `mysqlclient>=2.0` не закреплён и дублирует `PyMySQL` (код использует `pymysql.install_as_MySQLdb()`); хешей (`--hash`) в `requirements.txt` нет; `runtime.txt` требует Python 3.13.7, который Django 4.2 не поддерживает (поддерживает 3.8–3.12).
- Тесты: `test_i_dependencies.UnusedPackages.test_requirement_is_imported_by_the_project__*` (17), `RequirementHygiene.test_every_requirement_is_pinned_exactly`, `test_requirements_carry_hashes`, `test_only_one_mysql_driver`, `test_runtime_python_is_supported_by_pinned_django`.
- Рекомендация: сократить `requirements.txt` до реально используемого (проверить `pip-compile`/`pipdeptree`), закрепить и хешировать, согласовать версию Python и Django.

### NYZ-022. Сторонний фронтенд (Medium)

- `base.html:14` подключает `cdn.ckeditor.com/ckeditor5@39.0.1` на **каждой** публичной странице без `integrity=`; `category_order.html:70` — Sortable с jsdelivr; `base.html:13` — стили с `fonts.cdnfonts.com`. Компрометация CDN даёт исполнение кода на всех страницах.
- `settings.py:195` `CKEDITOR_JQUERY_URL = '//ajax.googleapis.com/…/2.1.1/…'`: протокол-относительный URL и jQuery 2.1.1 (< 3.5.0, известные XSS CVE-2020-11022/11023).
- `django-ckeditor 6.7.1` встраивает CKEditor 4.22.1 с неисправленными проблемами (`ckeditor.W001` из `check --deploy`).
- Тесты: `test_i_dependencies.FrontendSupplyChain.test_external_scripts_use_subresource_integrity`, `test_external_stylesheets_use_subresource_integrity`, `test_ckeditor_jquery_is_https_and_patched`; `RequirementHygiene.test_ckeditor4_is_not_in_use`.
- Не проверено: используется ли `ClassicEditor` из `base.html` где-либо (в шаблонах вызова не найдено, скрипт грузится зря).
- Рекомендация: убрать неиспользуемый CKEditor 5 из `base.html`, остальное локально (static) либо с `integrity`/`crossorigin`; сменить редактор.

### NYZ-023. Усиление защиты (Info)

Тесты красные, но реальная эксплуатация условная:

- CSRF-токен не привязан к сессии: подкинутая через соседний поддомен пара cookie/токен принимается для залогиненного редактора (`test_a_csrf.CsrfCookieAndSession.test_csrf_token_is_bound_to_the_session`); смягчается HSTS `includeSubDomains`. Рекомендация `CSRF_USE_SESSIONS = True`.
- Страницы кабинета без `Cache-Control: private/no-store` (`test_f_config.ResponseHeaders.test_cache_headers_on_editor_pages_forbid_shared_caching`): важно только при общем кэше/CDN, о наличии которого данных нет.
- Маршрут `article/<uuid:id>/` мёртв: перехвачен `article/<slug:slug>/` (UUID — допустимый slug), вью не принимает `id` (`test_g_logic.ErrorPages.test_article_by_id_route_is_dead_code`). Данные не раскрываются.

## 4. Ложные срабатывания и проверенное безопасное

Опровергнутые или ослабленные гипотезы:

| Гипотеза | Итог |
|----------|------|
| 1. CSRF на удалении | Подтверждена только для GET-удалений. Все 11 POST-эндпоинтов (включая `set_language`, JSON `update_category_order`, `login`, `comment`) возвращают 403 без токена и с неверным токеном (22 теста), Origin/Referer на HTTPS проверяются, `@csrf_exempt` в коде проекта нет (кроме сторонней `ckeditor_uploader`). `<img>` с чужого сайта не сработает из-за `SameSite=Lax`. |
| 2. Секреты | Подтверждена, и шире: Cloudinary API key/secret, секрет в истории и `db.sqlite3` (NYZ-001/002). |
| 3. Капча на ответах | Подтверждена (NYZ-006). |
| 4. Редакторские вью | Подтверждена, но латентно: регистрации нет (NYZ-004). |
| 5. `login_required` и open redirect | Открытого редиректа нет: `user_login` игнорирует `next` (4 варианта), редиректы на логин содержат только локальный `next`. Подтвердился только некорректный `LOGIN_URL` (NYZ-017). |
| 6. `set_language` open redirect | Не подтверждён для 9 вариантов `next` при корректном Host; достижим только через `ALLOWED_HOSTS=['*']` (NYZ-009). |
| 7. Загрузка | Подтверждена (NYZ-014), включая `image=None` → 500. |
| 8. XSS | Подтверждён только в `article.text`, about-us, RSS и oembed. Имена, комментарии, авторы, категории, поиск `q`, slug, `request.path`, контексты атрибутов и inline-JS безопасны. Карточки со `striptags` + `autoescape off` устойчивы к 12 нагрузкам, включая вложенные и незакрытые теги. |
| 9. ReDoS | Регулярок нет; `%` и `_` экранирует ORM. Остаётся отсутствие лимитов и троттлинга (NYZ-016). |
| 10. `update_category_order` | Падает на мусоре (NYZ-013) и делает N запросов (NYZ-016); «массовое изменение чужих записей» ограничено полем `order` и требует логина. |
| 11. Вход | Нет блокировки (NYZ-011); enumeration и тайминг не подтверждены. |
| 12. Сессии | Подтверждены Secure, отзыв и подделка (NYZ-019); `HttpOnly`, `SameSite=Lax`, срок 14 дней в норме; fixation не воспроизводится. |
| 13. Заголовки | `X-Frame-Options`, nosniff, Referrer-Policy, COOP, HSTS на месте; нет CSP (NYZ-018), `ALLOWED_HOSTS` обнулён (NYZ-009). |
| 14. `/admin/`, `/ckeditor/` | Аноним, обычный пользователь и не-staff редактор получают 302; проблемы только `csrf_exempt`, типы файлов и бомба (NYZ-015). |
| 15. Зависимости | Подтверждена (NYZ-020/021); для Pyrebase4/gcloud/Radicale/python-jwt/rethinkdb advisories нет, но пакеты не используются. |
| 16. Закоммиченные файлы | Подтверждена (NYZ-002). EXIF/GPS в `media/` нет; `.vs/` и `.idea/` содержат только раскладку рабочей области. |
| 17. `article/<uuid:id>/` | Опровергнута как уязвимость: маршрут недостижим, ошибка не возникает и ничего не раскрывает (NYZ-023). |
| 18. Раскрытие информации | Черновики не видны в поиске, RSS, sitemap; открыты по slug и на лентах (отложенные), NYZ-007; `DEBUG=True` подтверждён. |

Дополнительно проверено и безопасно: SQL-инъекции (7 нагрузок × `q`, поля комментария, логин, slug в URL, JSON id), отсутствие `raw`/`extra`/`eval`/`mark_safe`; SSTI в тексте; имена файлов с `../`, `..\`, null-байтом, 300 символами (остаются в `MEDIA_ROOT`); отсутствие `send_mail`; атомарность счётчика (`F`-выражение); кэш меню (число записей ограничено языками, языки не смешиваются, инвалидация работает); 3 МБ формы и JSON отсекаются 400; смена пароля и деактивация обнуляют сессии.

## 5. Что не проверено и почему

- Реальные значения на Heroku (переопределение `SECRET_KEY` через env; конфиг-переменные), правила роутера, лимиты gunicorn (`Procfile` без параметров): нет доступа к боевой среде.
- Публичность репозитория на GitHub и существование форков: запрещены внешние запросы.
- Реальная капча reCAPTCHA (в тестах `is_valid` подменяется), доставка файлов Cloudinary (origin, Content-Type), поведение MySQL strict mode (длины, переполнение `IntegerField`): SQLite не воспроизводит. Такие тесты проверяют, что некорректный ввод не принимается.
- Тайминг входа измерением (шумно на SQLite): проверен только факт фиктивного хеширования.
- `TooManyFieldsSent`: логирование падает в тестовой конфигурации, в боевой оно вне области.
- Эксплуатируемость каждого из 262 CVE для этого проекта; `mysqlclient` не аудитирован (не закреплён).
- Статика админки и `staticfiles/` (вендорные файлы), `locale/*.po`: на XSS не просматривались.

## 6. Выход `manage.py check --deploy`

С боевым модулем настроек (`DJANGO_SETTINGS_MODULE=anarchia.settings`, фиктивные переменные БД, подключения к БД нет):

```
?: (ckeditor.W001) django-ckeditor bundles CKEditor 4.22.1 which isn't supported anymore and which does have unfixed security issues ...
?: (security.W009) Your SECRET_KEY ... prefixed with 'django-insecure-' ...
?: (security.W012) SESSION_COOKIE_SECURE is not set to True.
?: (security.W016) ... you have not set CSRF_COOKIE_SECURE to True.
?: (security.W018) You should not have DEBUG set to True in deployment.
System check identified 5 issues (0 silenced).
```

`SECURE_SSL_REDIRECT`, HSTS (год, поддомены, preload) и `SECURE_PROXY_SSL_HEADER` в порядке. `ALLOWED_HOSTS=['*']` системная проверка не флагирует (NYZ-009).

## 7. Решения, нужные перед Фазой 4

1. **Секреты**: ротация SECRET_KEY, reCAPTCHA, Cloudinary выполняется владельцем вне кода. Переписывать историю git (и force-push)? Я ничего не пушу без отдельной просьбы.
2. **Зависимости**: ограничение запрещает добавлять пакеты в `requirements.txt`. Для NYZ-003 нужен санитайзер (bleach/nh3), для NYZ-011/016 — троттлинг (django-axes/django-ratelimit или самописный на кэше), для NYZ-018 — django-csp. Разрешить добавить, или писать самописные решения? Обновление Django/Pillow/и др. (NYZ-020) тоже меняет `requirements.txt`: разрешить?
3. **Модель ролей** (NYZ-004): считать редактором наличие записи `Editor`, группу или `is_staff`? Нужен ли доступ `is_staff` без `Editor`?
4. **Предпросмотр черновиков** (NYZ-007): только редакторам и 404 для остальных; так?
5. **Сессии** (NYZ-019): перейти на `cached_db`/`db` (все активные входы сбросятся, таблица `django_session` в миграциях есть)?
6. **Хранение лимитов**: `LocMemCache` у каждого воркера свой; для троттлинга нужен общий кэш (БД/Redis на Heroku). Что доступно?
7. **Python**: `runtime.txt` = 3.13.7 при Django 4.2: понизить до 3.12 или обновить Django (5.x потребует миграции кода)?
8. **Красные «Info»-тесты** (NYZ-023, часть NYZ-018): исправлять или перевести в `expectedFailure`/пометить как рекомендации?
9. Порядок исправлений по умолчанию: NYZ-008/009 (конфигурация) → NYZ-003/004/005 → NYZ-010/012/013 → NYZ-006/007/011/014 → NYZ-019/018/022 → NYZ-020/021 → NYZ-015/016/017/023. Один коммит на тему (Conventional Commits).

## 8. Статус исправлений (Фаза 4)

Прогон `app.test_findings` + `app.security_tests`: 638 тестов, **OK (expected failures=51)**. Открытые находки помечены `expectedFailure` (при исправлении превратятся в «unexpected success»).

| Находка | Статус | Коммит |
|---------|--------|--------|
| NYZ-001 | Секреты читаются из env. **Ротация и очистка истории за владельцем**, тесты истории остаются expectedFailure | `fix(settings)` |
| NYZ-002 | `.pyc`, `db.sqlite3`, `.vs/`, `.idea/` убраны из индекса, `.gitignore` расширен; в истории остаются | `chore(git)` |
| NYZ-003 | Исправлено: allowlist-санитайзер при сохранении и выводе, https-only oembed | `fix(xss)` |
| NYZ-004, 005, 017, 019 (кроме CSRF-привязки) | Исправлено: `editor_required`, POST-удаления, `LOGIN_URL`, сессии в БД, маршрут `logout`, Secure-cookie | `fix(auth)`, `fix(settings)` |
| NYZ-006, 007, 010, 011, 012, 013, 014, 015, 016 | Исправлено (лимиты хранятся в `LocMemCache` каждого воркера, для строгих лимитов нужен общий кэш) | `fix(models)`, `fix(uploads)`, `fix(views)` |
| NYZ-008, 009 | Исправлено: `DEBUG` из `DJANGO_DEBUG`, `allowed_hosts=False` | `fix(settings)` |
| NYZ-018 | Permissions-Policy добавлен. **CSP отложен**: нужны nonce для всех inline-скриптов и обработчиков и проверка редактора в браузере | – |
| NYZ-020, 021 | Исправлено: 22 закреплённых пакета вместо 66, Django 5.2 LTS, Python 3.12; `pip-audit`: «No known vulnerabilities found». Хеши (`--hash`) в `requirements.txt` не добавлены (нужен `pip-compile` и сеть) | `fix(deps)` |
| NYZ-022 | jQuery для CKEditor обновлён и на https. SRI для CDN-скриптов и замена CKEditor 4 отложены (нужны хеши из сети) | `fix(settings)` |
| NYZ-023 | Cache-Control `never_cache` для кабинета сделан; CSRF-токен в сессии (`CSRF_USE_SESSIONS`) и мёртвый маршрут оставлены | – |

Перед деплоем задать переменные окружения: `SECRET_KEY` (новый), `CLOUDINARY_API_KEY`, `RECAPTCHA_PUBLIC_KEY`, `RECAPTCHA_PRIVATE_KEY` (новые). Без них приложение не стартует. Активные входы редакторов сбросятся из-за смены движка сессий.

Обновление зависимостей: `Django 5.2.18` (4.2 в EOL, оставшиеся advisories исправлены только на новых линиях), `Pillow 13.0.0`, `urllib3 2.8.0`, `requests 2.34.2`, `whitenoise 6.12.0`, `gunicorn 26.2.0` и др.; удалены Pyrebase4, gcloud, python-firebase, python-jwt, Radicale, rethinkdb, oauth2client, vobject, passlib, pybind11, boto3, django-storages, google-*, Markdown, mysqlclient, cryptography и транзитивный хвост. Версии проверены в окружении `nyz`; боевую сборку на Heroku не запускал. `runtime.txt` = `python-3.12.11`: если такой патч-версии у Heroku нет, указать доступную 3.12.x.
