# Группы F и G: фронтенд, браузер, a11y, SEO (только измерения)

Стенд: Django 4.2.4, `anarchia.settings_test` + `docs/prod-readiness/scripts/fg_settings.py` (мок reCAPTCHA siteverify, MEDIA_ROOT в scratchpad), SQLite-файл в scratchpad, `runserver 127.0.0.1:8124 --noreload`, синтетика из `scripts/fg_seed.py` (5 категорий 3 уровня, 2 автора, 12 статей ua/en + draft + будущая, 4 комментария с цепочкой ответов, AboutUsText pk=1, superuser). Playwright 1.64.1: Chromium 1248, Firefox 1555, WebKit 2370. Все внешние хосты в браузере перехватывались `route` (abort, либо заглушка для api.js капчи в F2.5). Ни одного запроса вне 127.0.0.1. Lighthouse запущен с `--host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"`.

Скрипты: `docs/prod-readiness/scripts/fg_common.py, fg_f1.py, fg_f2.py, fg_f3.py, fg_f4.py, fg_g1.py, fg_g2.py, fg_seed.py, fg_settings.py` (запуск: `PYTHONPATH=docs/prod-readiness/scripts`). Сырые JSON (f1/f2/f3/g1, lighthouse) лежат в scratchpad. Скриншоты: `docs/prod-readiness/evidence/screens/*.png` (12 файлов, 1.2 МБ, палитра 48 цветов).

## 0. Блокирующие внешние зависимости base.html (зафиксировано)

| Ресурс | Файл:строка | Тип |
|---|---|---|
| `https://fonts.cdnfonts.com/css/sf-pro-display` | templates/base.html:13 | render-blocking CSS |
| `https://cdn.ckeditor.com/ckeditor5/39.0.1/classic/ckeditor.js` | templates/base.html:14 | синхронный `<script>` в `<head>`, без defer/async: блокирует парсинг |
| `https://www.google.com/recaptcha/api.js` | виджет `{{ captcha_form.captcha }}`, templates/article.html:163 | синхронный скрипт в середине body статьи |
| `https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js` | templates/category_order.html:70 | только кабинет |

Проверено: в шаблонах и style.css нет `http://` ресурсов (только xmlns в svg): смешанного контента нет, запросов `http://` на не-localhost за все прогоны 0. Это не гарантия под https (стенд http), но подгружаемых по http ресурсов в коде нет.

## F1. Ошибки JS, сбои запросов (3 браузера × 375/768/1440, 51 загрузка на браузер = 153)

Ожидание «0 ошибок JS» НЕ выполнено: ошибки на 100% страниц, во всех 3 браузерах и 3 вьюпортах.

Подтверждено (Chromium 1440, идентично в 375/768 и Firefox/WebKit, тексты разные):
- `Cannot read properties of null (reading 'addEventListener')` ← templates/base.html:116 (`themeToggle.addEventListener`, `themeToggle` = null на всех страницах, кроме /article/<slug>/). Firefox: `can't access property "addEventListener", themeToggle is null`; WebKit: `null is not an object (evaluating 'themeToggle.addEventListener')`.
- `Cannot read properties of null (reading 'addEventListener')` ← base.html:139 (`document.getElementById("ticker")`). Элемента `#ticker` нет: probe `ticker_id=false, ticker_cls=false` на всех страницах.
- `Cannot read properties of null (reading 'style')` ← base.html:204 (`ticker.style.marginTop`) внутри `updateHeaderMargin`, вызывается на `load` и на каждый `resize` (base.html:210-211), то есть бросается повторно при каждом ресайзе.
- Итого: 3 pageerror на каждой странице; на /article/<slug>/ 2 (themeToggle там есть). `/login/` и все страницы кабинета тоже 3 (+ см. ниже).
- Только кабинет, как следствие блокировки CDN (в проде при живом CDN не будет): `ClassicEditor is not defined` (editor_cabinet, edit_article; templates/editor-cabinet.html:105, edit_article.html:94), `Sortable is not defined` ×2 (category_order). edit_author и comments_moderation: только 3 базовые ошибки.
- Не-JS: 404 на `/does-not-exist/` — единственный локальный HTTP>=400 (ожидаемо). Локальных failed requests 0. Консольные ошибки кроме pageerror: только `net::ERR_FAILED` для 4 внешних хостов выше (наша блокировка; Firefox пишет их как warning «Loading failed for the <script>»).

Последствия для вёрстки (измерено, Chromium):
- Inline `main.style.marginTop` не выставляется никогда (`main_inline_mt=null`). Спасает CSS-фоллбэк `main{margin-top:74px}` и `@media(max-width:1000px){main{margin-top:52px}}` (static/style.css:975-981) — гипотеза «контент уезжает под шапку везде» опровергнута.
- Но фоллбэк жёсткий и не равен высоте шапки (header `position:fixed`, style.css:76-80). Высота шапки: 75 px (375), 130 px (768), 88 px (1440). Верх первого контента под шапкой: 768, home — 28 px, /all, /category, /authors, /search, /login и др. — 38 px, статья — 48 px (перекрытие `header.bottom - first.top`). Визуально подтверждено: `screens/home_768.png`, заголовок «Останні публікації» обрезан шапкой. На 375 и 1440 перекрытия заголовка нет (-16...-27 px; у article-wrapper 1440 край на 14 px под шапкой, контент ниже за счёт theme-switcher margin).
- Бегущая строка `.ticker` (style.css:249-290) и клик «ticker → /about-us» (base.html:139-141) — мёртвый код.
- Горизонтального скролла нет (scrollWidth == viewport на всех).
- Меню: см. F2.

Дополнительно: `toggleReplyForm` нигде не определена (templates/article.html:127, templates/comment.html:12), см. F2.5.

## F2. Сценарии

2.1 Hover десктоп (1440, 3 браузера): подменю открывается (display none -> flex, 130×46), вложенный `.sub-menu.iteration` тоже, закрывается через ~400 мс после ухода курсора. Работает. Языковой dropdown открывается по hover.

2.2 Тап 375 (has_touch, 3 браузера): бургер открывает `.menu` на весь экран и вешает `overflow-hidden` на body. Тап по родительской категории с детьми открывает подменю, но URL НЕ меняется ни после 1-го, ни после 2-го тапа, и подменю не закрывается (base.html:155-170: `event.preventDefault()` на всём `li.parent-category`, ссылка на саму категорию с подкатегориями недостижима с телефона). Тап по «Кіно» (категория с детьми) тоже не переходит. Лист (`/category/documentary/`) открывается. Режим «тап» выбирается по `window.innerWidth <= 768` на момент загрузки (base.html:153), а бургер включён CSS при <=1000 (style.css:130): на 900 px с тачем (iPad-класс) бургер виден, а по тапу родительской категории происходит переход на `/category/culture/` напрямую, подменю дочерних недостижимо. Ширина не пересчитывается при ресайзе/повороте.

2.3 Язык: кнопки в dropdown (hover или клик). `next=request.path` (base.html:45): на статье остаётся на той же статье, но в EN-режиме h1/текст остаются украинскими (статья не переключается на en-версию), меню и кнопка меняются на `Culture`/`ENG`. Query теряется: `/search/?q=article` -> `/search/` (проверено 3 браузера). Cookie `django_language=en`. Главная после этого: «Latest articles», карточки только en. `<html lang>` пуст всегда.

2.4 Тема: на статье `label[for=themeToggle]` ставит `main.light` и `body.light`, фон rgb(40,40,40) -> rgb(253,251,238). Не сохраняется: после reload класс `article-main` без `light` (нет localStorage/cookie). У `label` нет текста и aria-label, `input[hidden]` — недоступен с клавиатуры и скринридера. На главной `#themeToggle` нет (подтверждено), переключателя темы вне статей нет.

2.5 Комментарии (мок-капча): форма отправляется. Без токена `g-recaptcha-response` комментарий НЕ создаётся и пользователю ничего не сообщается (redirect на ту же статью, нет сообщения: `silent_failure_message_shown=false`). С токеном (мок siteverify) комментарий создаётся (счётчик +1) во всех 3 браузерах. Ответ на комментарий: клик по «Відповісти» -> pageerror `toggleReplyForm is not defined` (WebKit: `Can't find variable: toggleReplyForm`), форма остаётся `display:none`, UI ответа недоступен вообще. Серверный путь ответа (при принудительном показе формы) работает, +1 комментарий. Ссылка «Відповісти» — `<a>` без href (lighthouse `crawlable-anchors`: `div.article > div#comments > div.comment > a`).

2.6 Поиск: форма только в футере (позиция y≈1534 на главной, найти поиск на длинной странице нужно скроллить до конца). `q=article 3` -> 1 карточка. `q=zzzz` -> страница с одним заголовком «Результати пошуку» без сообщения «ничего не найдено». Пустой `q` -> все 12 статей. У input нет label/aria-label (только placeholder), у кнопки `.search-button` нет имени (axe critical).

2.7 Клавиатура (Chromium и Firefox идентичны): Tab на 1440 проходит логотип, 5 верхних пунктов меню, кнопку языка, затем карточки. Ссылки подменю (`.sub-menu`, display:none пока нет hover) НИ РАЗУ не получают фокус (`submenu_link_focused_ever=false`), подкатегории доступны только мышью. Подменю по фокусу не раскрывается. На 375 меню скрыто, `.burger-icon` — `div` без tabindex/role, фокус на него не попадает (`burger_focused_ever=false`): с клавиатуры меню на мобильной ширине недоступно. Кнопка языка: Enter открывает dropdown, следующий Tab -> «English» (работает, но нет `aria-expanded`). Focus-ring на 1440 штатный (`outline auto`), на 375 у ссылок меню `outline none` (меню скрыто, не проверено визуально). WebKit: Tab-навигация в Playwright WebKit ведёт себя иначе (фокус зациклился на input футера), результаты по клавиатуре для WebKit считать недостоверными (см. «не удалось»).

Побочная находка (видна в UI): на главной и в категориях показана статья «Future ua» с `publish_at` через 5 дней (`index`/`category` фильтруют только `is_published`; screens/home_768.png). Draft не показывается в списках, но открывается по URL (`/article/draft-ua/` 200, h1 «Draft ua»).

## F3. CKEditor 5 (CDN) vs CKEditor 4 (бэкенд)

- `ClassicEditor` (CKEditor 5) используется только в: templates/editor-cabinet.html:105,113,121; templates/edit_article.html:94. `CKEDITOR`/`ClassicEditor` на публичных шаблонах (index, article, category, search, authors, author_detail, about-us, login): 0 вхождений. Скрипт base.html:14 на публичных страницах не нужен. Все 13 шаблонов наследуют base.html, значит CDN подтягивают и публичные страницы.
- CKEditor 4 на бэкенде: пакет `ckeditor` (settings.py:53, `CKEDITOR_*` settings.py:193-197), `RichTextField` в app/models.py:5 (Article.text), используется в админке и `ckeditor_uploader` (`/ckeditor/upload/` как uploadUrl для CKEditor 5, templates/edit_article.html:100). Два разных редактора разных мажорных версий: админка (v4 из static) и кабинет (v5 с CDN). Совместимость ответа аплоада v4<->v5 не проверялась (нужен staff-логин и реальный файл).
- Эффект блокировки (Chromium, 1440, 3 прогона медиана FCP, CDN симулирован задержкой через route; localhost-сервер):

| Сценарий | / | /article/test-article-0/ |
|---|---|---|
| оба внешних ресурса сразу abort (эквивалент «без CDN») | 76 мс | 68 мс |
| ckeditor.js отвечает через 2 с | 2068 мс | 2068 мс |
| fonts CSS отвечает через 2 с | 2072 мс | 2064 мс |
| ckeditor.js «висит» (нет ответа) | FCP нет за 12 с (2/2) | FCP нет за 12 с (2/2) |

  Каждая секунда задержки каждого CDN прибавляется к FCP один к одному: страница белая, пока CDN не ответит. Строка «оба с задержкой 4080 мс» — артефакт серийной обработки route в симуляторе, не использовать. Реальный размер ckeditor.js не измерен (запрещён внешний запрос).

## F4. Скриншоты

`docs/prod-readiness/evidence/screens/{home,article,category,search}_{375,768,1440}.png` (12 шт, 1.2 МБ). Фон: шрифт CDN недоступен (fallback), картинки статей — заглушка card-example.png.

## F5. Lighthouse (lighthouse из npm, Chrome for Testing 1248 headless, localhost; CDN не резолвится, быстрый отказ, поэтому performance оптимистичнее реальности, где CDN могут тормозить; сервер — Django runserver)

| Страница | Пресет | Perf | A11y | BP | SEO | FCP | LCP | TBT | CLS |
|---|---|---|---|---|---|---|---|---|---|
| / | mobile | 75 | 59 | 96 | 82 | 1.5 s | 7.5 s | 0 | 0 |
| / | desktop | 96 | 65 | 96 | 82 | 0.4 s | 1.4 s | 0 | 0 |
| /article/test-article-0/ | mobile | 95 | 55 | 96 | 73 | 1.5 s | 2.9 s | 0 | 0 |
| /article/test-article-0/ | desktop | 100 | 61 | 96 | 73 | 0.4 s | 0.4 s | 0 | 0.015 |
| /category/culture/ | mobile | 76 | 59 | 96 | 82 | 1.4 s | 7.4 s | 0 | 0 |
| /category/culture/ | desktop | 97 | 65 | 96 | 82 | 0.4 s | 1.3 s | 0 | 0 |

Пороги (предложение для прод-готовности): perf >= 90 mobile, a11y >= 90, BP >= 90, SEO >= 90. Не проходят: a11y (55-65) и SEO (73-82) на всех страницах; perf mobile на главной/категории (75-76, LCP 7.5 s при пороге 2.5 s). Причины по данным lighthouse: `static/img/bg.png` весит 970188 байт и грузится на главной/категориях (total 1212 KiB, из них bg.png + card-example.png 227 KB; в проде картинки статей придут с Cloudinary, их вес здесь синтетический); LCP-картинка без `fetchpriority` (lcp-discovery-insight); `errors-in-console`; `html-has-lang`, `image-alt`, `link-name`, `button-name`, `meta-description`, `color-contrast` (статья), `heading-order`, `crawlable-anchors` (статья). BP 96: снижает только консоль (ошибки сети/JS).

## G1. axe-core 4.x (Chromium, 1440 и 375, 11 публичных страниц + статья в светлой теме; результаты на 375 и 1440 совпадают)

| Правило | Impact | Узлов на странице | Страницы | Селектор / ссылка |
|---|---|---|---|---|
| button-name | critical | 1 | все 11 | `.search-button` (base.html:105, иконка svg без текста/aria-label) |
| image-alt | critical | 2 | все | логотипы `header .logo > img`, `.footer-row1 > .logo > img` (base.html:19, 78: нет `alt`) |
| html-has-lang | serious | 1 | все | `<html>` base.html:6 |
| link-name | serious | 2 (все страницы) ... 14 (home), 9 (/all), 10 (author_detail), 5 (category) | все | `.logo` ссылки (base.html:19,78) и `.card-image-link`/`a > .card-image` — ссылки, содержащие только фон-div (index.html:23-31, category.html:25-32 и др.) |
| color-contrast | serious | 19-20 (article ua/светлая), 3 (article en) | /article/* | `.article-card.recommended > .card-text > p` 3.92:1 (#7f7e77 на #fdfbee), `.comment > a` 4.34:1, `.comment p` 3.69-4.46:1 (#828282); article.html:127,137 (inline `color: gray`) |
| heading-order | moderate | 1-2 | home(2), all, category x2, authors, author_detail, search | h1 -> h3 без h2 (карточки `h3`, `index.html:36,...`) |
| page-has-heading-one | moderate | 1 | /login/ | нет h1 (templates/login.html) |

Первые 4 правила присутствуют на каждой публичной странице из-за base.html. Правил про label у input поиска axe не выдал (placeholder засчитывается), хотя `labels=0, aria-label=null`. Страницы кабинета axe не гонялись (по заданию публичные).

## G2. SEO (HTTP-запросы на localhost, lxml + feedparser)

| Проверка | Результат |
|---|---|
| title | `Низовина` одинаковый на всех публичных страницах и на статьях (base.html:10; ни в одном шаблоне нет `{% block title %}`) |
| meta description | нет нигде (lighthouse `meta-description` fail) |
| canonical | нет нигде |
| og:*, twitter:* | нет нигде |
| hreflang / alternate | нет; при этом ua/en-контент выбирается cookie, один и тот же URL отдаёт разные языки |
| `<html lang>` | отсутствует (`html_lang=[]`), base.html:6. Только на дебаг-404 Django `en` |
| h1 | ровно 1: /all, category, article, authors, author_detail, about-us, search. 2 на `/` (index.html:16, 107: «Останні…», «Найпопулярніші…»). 0 на /login/ |
| structured data | JSON-LD 0, microdata 0 на статье (нет Article/BreadcrumbList) |
| alt у img | на всех страницах 2 `<img>` (логотипы шапки/футера) без атрибута `alt`. Картинки статей/карточек/авторов — CSS `background:url(...)` в div (index.html:23-31 и т.д.), то есть без `alt` и не как контент-изображения |
| robots meta | нет |
| robots.txt | 404 (маршрута нет) |
| /favicon.ico | 404 (иконка задана `<link rel=icon>` на logo.svg, base.html:11) |
| sitemap.xml | 200, `application/xml`, валидный XML. 15 URL: 12 опубликованных статей (draft и будущая статья исключены — опровергнуто «в sitemap утекают неопубликованные»), 2 автора, about-us. Нет главной, /all, категорий, /authors. Все 15 URL отвечают 200. `lastmod`: у статей `publish_at` (date), у about-us и авторов — «сегодня» (now) |
| host в sitemap/feed | `http://example.com/...` — берётся из `django.contrib.sites` (SITE_ID=1, settings.py:58). В тестовой БД Site=example.com; в проде зависит от строки Site (не проверялось, нужна боевая БД) |
| RSS /feed/ | 200 `application/rss+xml`, feedparser `bozo=False` (валидный). Язык канала `ua` и `en` (по cookie). `ua` — не валидный ISO 639-1 для украинского (`uk`), поэтому проверка валидаторов RSS даст предупреждение. 5 записей, ссылки абсолютные `http://example.com/article/<slug>/`, guid = link, `author` не задан. `pubDate` у всех 5 записей одинаковый `02 Nov 2026 12:13:15` (= created_at, т.к. сид создал статьи одновременно), при этом `publish_at` у них различается на дни: подтверждено, что pubDate берётся из `created_at`, а не `publish_at` (app/feeds.py:`item_pubdate`). Описание — полный HTML текста |
| 404 в проде | При DEBUG=True (settings.py:35 хардкод) отдаётся техническая страница Django (title «Page not found at ...», `NONE,NOARCHIVE`). Проверка с `override_settings(DEBUG=False)`: голый «Not Found», шаблона 404.html/500.html нет, шапка/меню/язык сайта не показываются |

## Опровергнутые или уточнённые предположения

- «themeToggle только в article.html» — подтверждено (и в base.html:114 на нём всё падает на остальных страницах).
- «main margin-top ломается» — опровергнуто для 375/1440 (CSS-фоллбэк); подтверждено частично для 768 (обрезан h1 на 28-48 px).
- «Подменю на десктопе недоступно» — опровергнуто для мыши; подтверждено для клавиатуры и для категорий с детьми на тач-устройствах.
- Sitemap/feed не содержат draft и будущие статьи (опровергнута утечка), XML валиден. Но главная/категории показывают будущую (scheduled) статью.
- Mixed content: не обнаружен (0 http-ресурсов, 0 запросов).
- Локальных failed requests/404 по static и media: 0.
- Горизонтального переполнения на 375/768/1440 нет.
- Нет JS-ошибок на странице 404 (там нет base.html, это дебаг-страница).
- Языковое переключение сохраняет путь, но теряет query; не сохраняет язык статьи (нет en-версии как отдельной страницы).

## Не удалось проверить и почему

- Реальные размеры и время CDN-ресурсов (ckeditor.js, шрифт, recaptcha): запрещён внешний трафик. Влияние только симуляцией задержки.
- Реальный reCAPTCHA (виджет, v2 checkbox, прохождение): мок токена и siteverify; поведение при недоступности Google (таймаут в `captcha.client.submit`) не измерялось.
- Cloudinary-изображения (размеры, форматы, lazy): заглушки card-example.png (227 KB) вместо реальных; LCP на главной/категориях в проде будет другим.
- WebKit Tab-навигация: поведение Playwright WebKit (фокус цикл на input) не соответствует Safari, результаты клавиатуры по WebKit недостоверны; клавиатура измерена только в Chromium и Firefox. Реальные Safari iOS/Android Chrome тачи не проверялись (эмуляция Playwright).
- Страницы кабинета в axe не гонялись (задание: публичные); XSS/безопасность контента не в зоне.
- Работа CKEditor 5 и аплоада изображений (v4-бэкенд `ckeditor_uploader`) не проверялась: редактор не загружается без CDN.
- Боевой Site-домен для sitemap/feed и боевой DEBUG: не проверялись (нужна боевая конфигурация); 404/500 проверены только в локальном DEBUG=False.
- При старте работы в репозитории `git status` показывает изменённые tracked `__pycache__/*.cpython-311.pyc` и `app/prod_tests/`: мои команды запускались с `PYTHONDONTWRITEBYTECODE=1`, вероятнее всего это параллельные процессы других групп; я их не откатывал.
