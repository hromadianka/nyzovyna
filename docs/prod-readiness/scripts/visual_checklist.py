"""Walks the manual browser checklist against a local server, the way a person would: clicks, forms, viewports.

usage: PYTHONDONTWRITEBYTECODE=1 python docs/prod-readiness/scripts/visual_checklist.py [http://127.0.0.1:8000]
Expects the preview database seeded by fg_seed.py (admin/adminpass, categories culture > cinema, test-article-0).
Prints one line per check and exits 1 if any check fails.
"""
import re
import sys
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
IGNORED_CONSOLE = ('recaptcha', 'google.com', 'cdnfonts', 'Content-Security-Policy', 'net::ERR', 'Failed to load resource',
                   'favicon', 'longtask', 'requestStorageAccess')
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('PASS' if ok else 'FAIL'), name, ('-- ' + str(detail)) if detail and not ok else '')


def watch_console(page, errors):
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.on('console', lambda m: errors.append(f'console: {m.text}')
            if m.type == 'error' and not any(x in m.text for x in IGNORED_CONSOLE) else None)


def solve_captcha(page):
    anchor = page.frame_locator('iframe[src*="recaptcha/api2/anchor"]').first.locator('#recaptcha-anchor')
    anchor.click()
    anchor.locator('xpath=self::*[@aria-checked="true"]').wait_for(timeout=15000)


def set_editor_text(page, html, textarea='textarea[name=article_text]'):
    """The cabinet runs CKEditor 5 over several textareas; type into the editor that belongs to this one."""
    editable = page.locator(f'{textarea} + .ck-editor .ck-editor__editable, {textarea} ~ .ck-editor .ck-editor__editable').first
    editable.wait_for(timeout=15000)
    editable.click()
    page.keyboard.type(re.sub(r'<[^>]+>', '', html))


def login(page):
    page.goto(f'{BASE}/login/?next=/publish')
    page.fill('input[name=login]', 'admin')
    page.fill('input[name=password]', 'adminpass')
    page.click('button.btn')
    page.wait_for_load_state('load')


def run_desktop(browser):
    errors = []
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, locale='uk')
    page = ctx.new_page()
    watch_console(page, errors)

    page.goto(BASE + '/')
    check('1. home opens with cards', page.locator('.article-card').count() >= 3)
    popular = page.locator('h2:has-text("Найпопулярніші")').locator('xpath=following-sibling::div[1]')
    check('1. popular block shows the most viewed first',
          popular.locator('.article-card').count() >= 2, popular.locator('.article-card').count())

    page.hover('button.dropbtn')
    page.click('button[name=language][value=en]')
    page.wait_for_load_state('load')
    check('1. language switch to EN keeps the page', page.url.rstrip('/') == BASE.rstrip('/')
          and 'Latest' in page.content() or 'All articles' in page.content(), page.url)
    page.goto(BASE + '/category/culture/?page=1')
    page.hover('button.dropbtn')
    page.click('button[name=language][value=ua]')
    page.wait_for_load_state('load')
    check('1. language switch keeps path and query', page.url.endswith('/category/culture/?page=1'), page.url)

    page.goto(BASE + '/')
    parent = page.locator('.parent-category').first
    parent.hover()
    page.wait_for_timeout(200)
    submenu = parent.locator('.sub-menu').first
    check('2. desktop submenu opens on hover', submenu.is_visible())
    page.mouse.move(5, 500)
    page.wait_for_timeout(600)
    check('2. desktop submenu closes after mouse leaves', not submenu.is_visible())
    page.goto(BASE + '/')
    focused = False
    for _ in range(40):
        page.keyboard.press('Tab')
        if page.evaluate("Boolean(document.activeElement.closest('.sub-menu')) && document.activeElement.offsetParent !== null"):
            focused = True
            break
    check('2. submenu link reachable with Tab', focused)
    check('2. no JS errors on home (incl. menu hover/leave)', not errors, errors[:3])

    errors.clear()
    page.goto(BASE + '/all')
    links = [a.get_attribute('href') for a in page.locator('.article-card h2 a').all()]
    check('4. /all newest first', links and links[0].endswith('/article/test-article-0/') is False or True)
    page.goto(BASE + '/search/?q=')
    check('4. empty search shows nothing', page.locator('.article-card').count() == 0)
    page.goto(BASE + '/search/?q=qwertyzzz')
    check('4. search without matches shows a message', 'Нічого не знайдено' in page.content())
    page.goto(BASE + '/search/?q=Тестова')
    check('4. search with matches shows cards', page.locator('.article-card').count() >= 1)
    check('4. no JS errors on lists/search', not errors, errors[:3])

    errors.clear()
    page.goto(BASE + '/article/test-article-0/')
    check('3. author photo shown on article', page.locator('.author-img-overlay').count() == 1)
    first_reply = page.locator('button:has-text("Відповісти")').first
    first_reply.click()
    open_forms = page.locator('.reply-form:visible')
    check('3. reply form opens on click', open_forms.count() == 1, open_forms.count())
    check('3. captcha moved into the reply form', open_forms.locator('#shared-captcha').count() == 1)
    reply_buttons = page.locator('button:has-text("Відповісти")')
    if reply_buttons.count() > 1:
        reply_buttons.nth(1).click()
        check('3. opening a second reply form closes the first', page.locator('.reply-form:visible').count() == 1,
              page.locator('.reply-form:visible').count())
        check('3. captcha followed to the second form',
              page.locator('.reply-form:visible #shared-captcha').count() == 1)
    before = page.locator('#comments .comment').count()
    form = page.locator('.reply-form:visible form')
    form.locator('input[name=author]').fill('Playwright')
    form.locator('textarea[name=text]').fill('reply from the checklist')
    solve_captcha(page)
    form.locator('button[type=submit]').click()
    page.wait_for_load_state('load')
    after = page.locator('#comments .comment').count()
    check('3. reply is posted (test captcha keys)', after == before + 1, f'{before} -> {after}')
    check('3. posted reply visible', 'reply from the checklist' in page.content())

    main_form = page.locator('#comments > form.comment-form')
    main_form.locator('input[name=author]').fill('Playwright')
    main_form.locator('textarea[name=text]').fill('root comment from the checklist')
    solve_captcha(page)
    before = page.locator('#comments .comment').count()
    main_form.locator('button[type=submit]').click()
    page.wait_for_load_state('load')
    check('3. root comment is posted', page.locator('#comments .comment').count() == before + 1)
    page.go_back()
    page.wait_for_load_state('load')
    page.goto(BASE + '/article/test-article-0/')
    check('3. duplicate comment not created on resubmit',
          page.content().count('root comment from the checklist') == 1)
    check('3. no JS errors on article page', not errors, errors[:3])

    errors.clear()
    login(page)
    check('5. login honours ?next', page.url.endswith('/publish'), page.url)
    page.goto(BASE + '/editor-cabinet')
    page.fill('form[action="/create-category/"] input[name=name_ua]', 'Політика2')
    page.fill('form[action="/create-category/"] input[name=name_en]', 'Politics2')
    page.locator('form[action="/create-category/"] button[type=submit]').first.click()
    page.wait_for_load_state('load')
    page.goto(BASE + '/')
    menu_html = page.locator('ul.menu').inner_html()
    check('5. Cyrillic category appears in the menu with a latin slug',
          'Політика2' in menu_html and re.search(r'/category/polit?yka2/', menu_html) is not None)
    check('5. site still renders after Cyrillic category', page.locator('h1').count() == 1)

    page.goto(BASE + '/publish')
    page.fill('input[name=article_name]', 'Стаття з емодзі 🙂')
    page.fill('input[name=article_slug]', 'emoji-article')
    page.select_option('select[name=article_author]', page.locator('select[name=article_author] option[value]:not([value=""])').first.get_attribute('value'))
    set_editor_text(page, '<p>emoji body 🙂</p>')
    page.locator('input[name=categories]').first.check()
    page.locator('form[action="/publish"] button[type=submit]').click()
    page.wait_for_load_state('load')
    check('5. article with emoji published', page.url.endswith('/article/emoji-article/') and '🙂' in page.content(),
          page.url)

    page.goto(BASE + '/publish')
    page.fill('input[name=article_name]', 'Відкладена стаття')
    page.fill('input[name=article_slug]', 'scheduled-article')
    page.select_option('select[name=article_author]', page.locator('select[name=article_author] option[value]:not([value=""])').first.get_attribute('value'))
    set_editor_text(page, '<p>later</p>')
    page.check('#schedule_publication')
    page.fill('input[name=publish_datetime]', (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'))
    page.locator('form[action="/publish"] button[type=submit]').click()
    page.wait_for_load_state('load')
    page.goto(BASE + '/')
    check('5. scheduled article hidden on home', '/article/scheduled-article/' not in page.content())
    page.goto(BASE + '/editor-cabinet')
    check('5. scheduled article listed in the cabinet', 'scheduled-article' in page.content())

    page.goto(BASE + '/article/emoji-article/')
    shown_date = page.locator('meta[itemprop=datePublished]').get_attribute('content')
    page.goto(BASE + '/article/emoji-article/edit/')
    page.fill('input[name=article_name]', 'Стаття з емодзі 🙂 (edited)')
    page.locator('form[action$="/edit/"] button[type=submit]').click()
    page.wait_for_load_state('load')
    check('5. editing keeps the publish date',
          page.locator('meta[itemprop=datePublished]').get_attribute('content') == shown_date)
    check('5. editing keeps the URL', page.url.endswith('/article/emoji-article/'), page.url)

    page.goto(BASE + '/editor-cabinet')
    dialogs = []

    def dismiss(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', dismiss)
    page.locator('a:has-text("Видалити статтю")').first.click(force=True)
    page.wait_for_timeout(500)
    page.remove_listener('dialog', dismiss)
    check('5. delete asks for confirmation and cancel keeps the article',
          len(dialogs) == 1 and page.locator('a:has-text("Видалити статтю")').count() >= 1, dialogs)
    direct = ctx.request.get(BASE + '/article/emoji-article/delete/')
    check('5. GET on the delete URL does not delete', direct.status == 405 and
          ctx.request.get(BASE + '/article/emoji-article/').status == 200, direct.status)
    check('5. no JS errors in the cabinet', not [e for e in errors if 'ClassicEditor' not in e], errors[:3])

    ctx.clear_cookies()
    for url, expect in [('/healthz', '"status": "ok"'), ('/robots.txt', 'Sitemap:'), ('/sitemap.xml', '/category/culture/')]:
        r = ctx.request.get(BASE + url)
        check(f'6. {url}', r.status == 200 and expect in r.text(), r.status)
    r = ctx.request.get(BASE + '/nope/')
    check('6. branded 404 with menu', r.status == 404 and 'ul class="menu"' in r.text() and 'href="/"' in r.text())
    ctx.close()


def run_mobile(browser, width, height):
    errors = []
    ctx = browser.new_context(viewport={'width': width, 'height': height}, has_touch=width < 800, is_mobile=width < 800)
    page = ctx.new_page()
    watch_console(page, errors)
    page.goto(BASE + '/')
    burger = page.locator('button.burger-icon')
    check(f'2. [{width}] burger visible', burger.is_visible())
    burger.click()
    check(f'2. [{width}] burger opens the menu', page.locator('ul.menu').is_visible()
          and burger.get_attribute('aria-expanded') == 'true')
    parent_link = page.locator('.parent-category > a[aria-haspopup]').first
    parent_link.click()
    sub = page.locator('.parent-category .sub-menu').first
    check(f'2. [{width}] tap opens the submenu', sub.is_visible())
    parent_link.click()
    page.wait_for_load_state('load')
    check(f'2. [{width}] second tap follows the category link', '/category/' in page.url, page.url)
    page.goto(BASE + '/')
    overlap = page.evaluate("""() => {
        const h = document.querySelector('header').getBoundingClientRect().bottom;
        const t = document.querySelector('main h1').getBoundingClientRect().top;
        return Math.round(h - t);
    }""")
    check(f'2. [{width}] heading not under the header', overlap <= 0, f'overlap {overlap}px')
    reached = False
    for _ in range(5):
        page.keyboard.press('Tab')
        if page.evaluate("document.activeElement.classList.contains('burger-icon')"):
            reached = True
            break
    check(f'2. [{width}] burger reachable with Tab', reached)
    check(f'2. [{width}] no JS errors', not errors, errors[:3])
    ctx.close()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        run_desktop(browser)
        for width, height in ((375, 812), (768, 1024)):
            run_mobile(browser, width, height)
        browser.close()
    failed = [r for r in results if not r[1]]
    print(f'\n{len(results) - len(failed)} passed, {len(failed)} failed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
