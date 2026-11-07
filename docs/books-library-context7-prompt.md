# Промпт: сверка изменений раздела «Бібліотека» и редакторского интерфейса с документацией через Context7 MCP

Скопируйте блок после линии в новую сессию Claude Code, где подключён Context7 MCP (коннектор нужно авторизовать в настройках claude.ai или через `/mcp`). Агент только читает: файлы не меняет и ничего не коммитит.

---

## РОЛЬ
Ты — старший Django/Python-инженер и ревьюер. Проверь, соответствуют ли **незакоммиченные изменения** в репозитории `nyz` (Django-сайт «Низовина») актуальной документации используемых библиотек и веб-стандартов. Источник истины — Context7 MCP, а не твоя память: твои знания о версиях могут быть устаревшими.

## ОГРАНИЧЕНИЯ
1. Только чтение. Никаких `git commit/push/reset/checkout/stash`, правок файлов, установки пакетов, запросов к боевым сервисам и к аккаунту Cloudinary. Разрешены `git status/diff/log`, чтение файлов и локальный запуск тестов.
2. Каждый вывод «не соответствует документации» подкрепляй: библиотека и версия из Context7, цитата или точный пересказ фрагмента, `файл:строка` в нашем коде. Нет подтверждения — пиши «не подтверждено документацией», а не угадывай.
3. Если Context7 не знает библиотеку, версию или раздел, напиши это и пометь пункт «не проверено». Не выдавай память за цитату.
4. Проверяй конкретные вызовы API, настройки и параметры, а не пересказывай изменения. Не оценивай качество кода вообще, только соответствие документации и вытекающие риски.

## ОБЛАСТЬ
Рабочее дерево относительно `HEAD`:
```
git status --short
git diff HEAD --stat
git diff HEAD -- <файл>      # для изменённых файлов
```
Новые (untracked) файлы читай напрямую. Игнорируй `docs/.DS_Store`, `docs/prod-readiness/` и `docs/prod-readiness/CONTEXT7_REVIEW_PROMPT.md` (не относятся к задаче).

Затронутые файлы:
- Модели и миграция: `app/models.py` (`Book`, `BookFile`, `book_storage`, `book_file_path`), `app/migrations/0016_book_and_bookfile.py`.
- Код: `app/book_views.py` (новый), `app/uploads.py` (`validate_pdf`), `app/views.py` (`repeat_key`/`forget_repeat`, сортировка в `editor_cabinet`), `app/sitemaps.py`, `anarchia/settings.py` (`STORAGES['books']`, `BOOK_MAX_FILE_BYTES`), `anarchia/settings_test.py`, `anarchia/urls.py`.
- Шаблоны: `templates/book.html`, `books.html`, `books_cabinet.html`, `book_edit.html`, `book_form_fields.html`, `article_form_fields.html`, `editor-cabinet.html`, `edit_article.html`, `cabinet_article_row.html`, `recursive_list.html`, `base.html`.
- Статика и переводы: `static/style.css` (блоки в конце файла), `locale/{en,ua}/LC_MESSAGES/django.{po,mo}`.
- Тесты: `prod_tests/test_m_books.py`, `prod_tests/test_n_cabinet.py`.
- Описание решения: `docs/books-library.md`.

Версии (из `requirements.txt`, `runtime.txt` и шаблонов): Django 5.2.18, django-cloudinary-storage 0.3.0, cloudinary 1.44.1, Pillow 13.0.0, django-ckeditor 6.7.1, whitenoise 6.12.0, Python 3.12.11, клиентский CKEditor 5 classic build 39.0.1 (CDN). Запрашивай документацию именно для этих версий.

Работай так: составь карту «файл → используемые API», затем для каждой библиотеки вызови `resolve-library-id` и `query-docs` по вопросам ниже. Группируй запросы по библиотеке.

## ЧТО СВЕРЯТЬ

### A. Django 5.2: модели, файлы, хранилища
- `FileField(storage=book_storage)` с **callable**: поддерживается ли вызываемый объект, как он сериализуется в миграции (`deconstruct`, ссылка `app.models.book_storage`), вызывается ли он при импорте или лениво. То же для `upload_to=book_file_path(instance, filename)`: сигнатура, момент вызова (до `save()` модели, `instance.book.slug` доступен?).
- `django.core.files.storage.storages['books']`: нестандартный алиас в `STORAGES`; обязательны ли ключи `default` и `staticfiles`; как `settings_test.py` с полной подменой `STORAGES` должен выглядеть.
- `BookFile.save()`: чтение `self.file.size` у ещё не сохранённого `FieldFile` до `super().save()`; `editable=False` у `size`/`downloads`.
- `ImageField(blank=True)` без `default`: что возвращает `.url` для пустого поля (`ValueError`), как документирован `bool(field_file)`.
- `auto_now=True` у `Book.updated_at`: срабатывает только при `Model.save()`, не при `QuerySet.update()` и не при `update_fields` без этого поля.
- `Meta.ordering = ['order', 'pk']` и `['-created_at']`; `Paginator` над QuerySet с `ordering`.
- Удаление: `on_delete=CASCADE` для `BookFile`; **не удаляет ли Django файлы из хранилища при удалении записи** (ожидаем «не удаляет», подтверди цитатой).
- `transaction.atomic()` вокруг `save()` и загрузки файлов: что происходит с уже сохранёнными в хранилище файлами при откате.
- `UploadedFile`: `.size`, `.name`, `seek/read`; когда загруженный файл попадает в `request.FILES` как `TemporaryUploadedFile` (порог `FILE_UPLOAD_MAX_MEMORY_SIZE`); входит ли размер файлов в `DATA_UPLOAD_MAX_MEMORY_SIZE`; **пустое поле `<input type=file>` не попадает в `request.FILES`**, а соседние текстовые поля попадают в `request.POST` (ожидаем так, подтверди).
- Итерация `for key in request.FILES` (`MultiValueDict`) и `request.FILES[key]`; `request.POST.get`.
- `get_object_or_404(QuerySet, pk=..., book__slug=...)`, `QuerySet.update(downloads=F('downloads') + 1)`, `redirect(url)` с абсолютным внешним URL, `require_safe` и `HEAD` (поведение `HttpResponseRedirect` на `HEAD`).
- Конвертеры маршрутов: `<uuid:file_id>` вместе с `<slug:slug>`; `reverse()` с UUID.
- `Sitemap.lastmod`, `items()`; `cache.add/delete` для защиты от двойной отправки.
- Шаблоны: `{% include 'x.html' with a=b %}` и переопределение контекстной переменной (случай `book` не передан: поведение `{{ book.title|default:'' }}`), `|filesizeformat` (неразрывный пробел в выводе), `|default`, `{% trans %}`, `{% with files=book.files.all %}` и кэширование запроса, `prefetch_related('files')` вместе с `{% with %}`.

### B. Cloudinary (`django-cloudinary-storage` 0.3.0, `cloudinary` 1.44.1)
- `RawMediaCloudinaryStorage`: тип ресурса `raw`; сохраняется ли расширение `.pdf` в `public_id`/URL; как формируется `.url`; возвращает ли `.size`/`FieldFile.size` корректное значение; что делает `.delete()`.
- Совместимость 0.3.0 с `STORAGES` и Django 5.2 (сигнатуры `_save`, `get_available_name`, `exists`, `max_length`); читает ли пакет `STORAGES` или только `DEFAULT_FILE_STORAGE`.
- Исключения при сбое загрузки: наследуется ли `cloudinary.exceptions.Error` от `OSError`, какие ещё классы возможны (мы ловим `(OSError, CloudinaryError)`).
- Ограничения платформы, **если Context7 их индексирует**: максимальный размер raw-файла на бесплатном тарифе; настройка Security «Allow delivery of PDF and ZIP files» (по умолчанию выкл.) и её влияние на выдачу `raw`/PDF. Если документации нет, пометь «не проверено, требует ручной проверки в аккаунте».

### C. Валидация загрузок
- `validate_pdf`: расширение + первые 5 байт `%PDF-`. Что говорит спецификация/документация о расположении заголовка (допустим ли сдвиг в пределах первых 1024 байт) — если Context7 такой источник не индексирует, пометь «не проверено».
- Pillow 13: `Image.open`, `verify()`, `Image.DecompressionBombError`, `Image.MAX_IMAGE_PIXELS` (код вызывает `validate_image` для обложек книг так же, как для статей).

### D. Клиентская часть: CKEditor 5 39.0.1, HTML, CSS
- `ClassicEditor.create(...)` для нескольких `textarea` на странице; имена пунктов панели (`heading`, `link`, `bulletedList`, `numberedList`, `blockQuote`, `imageUpload`, `mediaEmbed`) существуют в classic build 39.0.1; опция `ckfinder.uploadUrl`; обновляется ли исходный `textarea` при отправке формы. Не вызывает ли атрибут `required`/`maxlength` на скрытом `textarea` проблем (в нашей разметке он у `summary`, но не у редакторов).
- Динамическое добавление строк формы (`cloneNode`, смена `name` на `book_file_N`/`file_label_N`): нет ли особенностей с `input[type=file]` при клонировании.
- HTML: атрибут `hidden` и CSS `display` (автор-стили перебивают `hidden`; мы добавили `[hidden] { display: none !important }`), `disabled` поле не отправляется (`datetime-local`), `<fieldset>` с `display:flex` (поддержка), `<details>/<summary>` с `list-style: none` и `::before`, атрибут `onerror` у `img`, `scroll-margin-top`, `aspect-ratio`, `object-fit`, `<nav aria-label>`, связка `<label>` с вложенным `input`.
- Доступность (WCAG/MDN, если индексируется): `alt=""` у декоративных миниатюр, `legend` у `fieldset`, ссылки со скриптовым обработчиком `href="#"`.

### E. SEO и микроразметка (если Context7 индексирует; иначе «не проверено»)
- `schema.org/Book`: допустимо ли `itemprop="author"` с текстовым значением, `itemprop="image"` на `<img>`, `itemprop="description"`, `itemprop="name"` на `<h1>`.
- Open Graph: допустимо ли `og:type="book"` без `book:author`/`book:isbn`; формат `og:image`.
- `rel="nofollow"` у ссылок на скачивание, `robots` `noindex,follow` у предпросмотра черновика.

### F. i18n
- Новые msgid (`Бібліотека`, `Завантажити`, `Анотація`) добавлены вручную в `.po` и скомпилированы `msgfmt`: эквивалентно ли это `manage.py compilemessages`; требуется ли `msgfmt -c`; дубли msgid.
- `gettext_lazy` внутри f-строки в `page_meta` (форматирование ленивой строки).

### G. Безопасность по документации Django
- Загрузка файлов: санитизация имени (`get_valid_name`, `Storage.generate_filename`), раздел «Managing files» и «Serving user-uploaded files» (заголовок `Content-Type`, `X-Content-Type-Options`, `SECURE_CONTENT_TYPE_NOSNIFF`).
- CSRF для `fetch` с `X-CSRFToken` из `{{ csrf_token }}` в inline-скрипте против чтения из cookie; влияние `CSRF_COOKIE_HTTPONLY`.
- `redirect()` на значение из хранилища (не из ввода пользователя): остаётся ли риск открытого редиректа.
- `require_POST` на удаление и `never_cache` у `editor_required`.

### H. Тесты (Django 5.2)
- `SimpleUploadedFile`, `Client.head`, `override_settings(BOOK_MAX_FILE_BYTES=...)`, `self.settings(MEDIA_ROOT=...)` и алиас `books`: временный каталог в `FileSystemStorage` берёт `MEDIA_ROOT` в момент создания или при обращении (влияет ли это на изоляцию тестов).

## СВОИ ПОДОЗРЕНИЯ (подтверди или опровергни по документации)
1. Callable `storage=` корректно записывается в миграцию и не создаёт новую миграцию при смене бэкенда в `STORAGES`.
2. У `RawMediaCloudinaryStorage` расширение `.pdf` сохраняется в URL и `size` доступен без запроса к API.
3. Выдача PDF/`raw` может блокироваться настройкой аккаунта Cloudinary по умолчанию.
4. Пустой `input[type=file]` не попадает в `request.FILES`, поэтому нумерация строк `book_file_N`/`file_label_N` нужна для правильного сопоставления подписей.
5. Django не удаляет файл из хранилища при удалении записи, значит удаление PDF оставляет файл в Cloudinary.
6. `auto_now` не обновляется при `QuerySet.update()`.
7. Перебивание `hidden` стилем `display:flex` — известное поведение браузеров (MDN).
8. `og:type="book"` допустим без дополнительных свойств.

## ПОРЯДОК РАБОТЫ
1. Построй карту «файл → API» по `git diff HEAD` и новым файлам (кратко).
2. По областям A–H сделай запросы в Context7 и сопоставь с кодом. Открывай сам код (`файл:строка`).
3. Проверь список «Свои подозрения».
4. Для каждого расхождения оцени влияние (ломает продакшен / деградация / стиль) и предложи минимальное исправление без правки файлов.
5. По желанию подтверди выводы локальным запуском: `DJANGO_SETTINGS_MODULE=anarchia.settings_test python manage.py test prod_tests.test_m_books prod_tests.test_n_cabinet` (SQLite in-memory, ничего не пишет вовне).

## ФОРМАТ ОТВЕТА
1. Краткий итог (≤10 строк): сколько пунктов проверено, сколько ✓ / ⚠ / ✗ / «не проверено».
2. Таблица (строка на пункт):
   | № | Область | Файл:строка | Что делает код | Что говорит документация (библиотека, версия, цитата/источник Context7) | Вердикт ✓/⚠/✗/? | Серьёзность | Минимальное исправление |
3. Список «не удалось проверить через Context7» с причиной (нет библиотеки, версии или раздела).
4. Список «документация предупреждает, а код этого не учитывает», даже если тесты зелёные.
5. Ответы на 8 подозрений (подтверждено / опровергнуто / не проверено, с источником).
6. Топ-5 расхождений, которые стоит исправить до релиза, по убыванию серьёзности.
