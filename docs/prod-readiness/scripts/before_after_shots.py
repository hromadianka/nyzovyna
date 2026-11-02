"""Side-by-side screenshots of the original code and the current code for the visible changes.

usage: before_after_shots.py <before_base> <after_base> <out_dir>
Both servers must run the seed from fg_seed.py (admin/adminpass). Writes NN_<name>_{before,after}.png and README.md.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BEFORE, AFTER, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
notes = []


def login(page, base):
    page.goto(base + '/login/')
    page.fill('input[name=login]', 'admin')
    page.fill('input[name=password]', 'adminpass')
    page.click('button.btn')
    page.wait_for_load_state('load')


def shot(ctx, name, path, label, prepare=None, viewport=(1440, 900), full=False, note='', element=None):
    page = ctx.new_page()
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    page.on('dialog', lambda d: d.dismiss())
    base = BEFORE if label == 'before' else AFTER
    if prepare:
        prepare(page, base)
    else:
        page.goto(base + path)
    page.wait_for_timeout(700)
    file = OUT / f'{name}_{label}.png'
    if element:
        page.add_style_tag(content='header { visibility: hidden !important; }')
        page.locator(element).screenshot(path=str(file))
    else:
        page.screenshot(path=str(file), full_page=full)
    page.close()
    return file.name


def cabinet(page, base):
    login(page, base)
    page.goto(base + '/editor-cabinet')
    page.wait_for_timeout(500)
    page.evaluate("""() => { const card = [...document.querySelectorAll('.article-card')]
        .find(c => c.textContent.includes('Future ua') || c.textContent.includes('Draft ua'));
        if (card) card.scrollIntoView({block: 'center'}); }""")


def article_title_tab(page, base):
    page.goto(base + '/article/test-article-0/')
    title = page.title()
    page.evaluate("(t) => { const b = document.createElement('div'); b.textContent = 'Заголовок вкладки: ' + t;"
                  " b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#ffeb3b;color:#000;"
                  "font:bold 22px sans-serif;padding:12px'; document.body.appendChild(b); }", title)


def article_comments(page, base):
    page.goto(base + '/article/test-article-0/')
    page.evaluate("document.querySelector('#comments')?.scrollIntoView()")


def article_reply_open(page, base):
    page.goto(base + '/article/test-article-0/')
    page.evaluate("document.querySelector('#comments')?.scrollIntoView()")
    target = page.locator('button:has-text("Відповісти"), a:has-text("Відповісти")').first
    target.click()
    page.wait_for_timeout(800)


def article_author(page, base):
    page.goto(base + '/article/test-article-0/')
    page.evaluate("document.querySelector('.article-author')?.scrollIntoView({block: 'center'})")


def mobile_menu_tap(page, base):
    page.goto(base + '/')
    page.click('.burger-icon')
    page.wait_for_timeout(300)
    page.locator('.parent-category > a').first.click()
    page.wait_for_timeout(500)


def mobile_menu_second_tap(page, base):
    mobile_menu_tap(page, base)
    page.locator('.parent-category > a').first.click()
    page.wait_for_load_state('load')
    page.wait_for_timeout(500)


def keyboard_submenu(page, base):
    page.goto(base + '/')
    for _ in range(4):
        page.keyboard.press('Tab')
    page.wait_for_timeout(300)


def all_top(page, base):
    page.goto(base + '/all')


def all_bottom(page, base):
    page.goto(base + '/all')
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")


def home_popular(page, base):
    page.goto(base + '/')
    page.evaluate("""() => { const h = [...document.querySelectorAll('h1, h2')].find(x => x.textContent.trim().startsWith('Найпопулярніші'));
        const block = h && h.nextElementSibling; if (block) block.id = 'popular-block'; }""")


CASES = [
    ('01_home_768_header', '/', dict(viewport=(768, 1024)),
     'Главная на планшете: заголовок «Останні публікації» срезан шапкой — на месте'),
    ('02_cabinet_cards', None, dict(prepare=cabinet),
     'Кабинет редактора, раздел «Відкладені статті»: заголовок, текст и кнопки карточки наложены друг на друга — разложены по порядку'),
    ('03_not_found', '/nope/', dict(viewport=(1440, 700)),
     'Страница 404: отладочная страница Django со списком маршрутов — страница в стиле сайта'),
    ('04_search_empty', '/search/?q=zzzqqq', dict(viewport=(1440, 500)),
     'Поиск без результатов: пустая страница — сообщение «Нічого не знайдено»'),
    ('05_article_tab_title', None, dict(prepare=article_title_tab, viewport=(1440, 500)),
     'Статья, заголовок вкладки браузера (жёлтая полоса добавлена скриптом): всегда «Низовина» — название статьи и сайта'),
    ('06_article_reply_open', None, dict(prepare=article_reply_open, viewport=(1440, 1100)),
     'Статья, клик по «Відповісти»: ничего не происходит (ошибка JS) — открывается форма ответа с капчей'),
    ('07_mobile_menu_tap', None, dict(prepare=mobile_menu_tap, viewport=(375, 812)),
     'Телефон, первый тап по «Культура»: раскрывается подменю. Здесь разницы нет, снимок нужен как исходная точка для 08'),
    ('08_mobile_menu_second_tap', None, dict(prepare=mobile_menu_second_tap, viewport=(375, 812)),
     'Телефон, второй тап по «Культура»: остаёмся в меню — переходим в категорию'),
    ('09_keyboard_submenu', None, dict(prepare=keyboard_submenu),
     'Клавиатура, 4 нажатия Tab: подменю закрыто и фокус невидим — подменю раскрыто, фокус на «Кіно»'),
    ('10_all_order', None, dict(prepare=all_top, viewport=(1440, 900)),
     'Все статьи, верх списка: порядок зависел от порядка вставки в базу (`reversed` без сортировки; на SQLite совпал с датой, на MySQL был бы произвольным) — сортировка по дате публикации, новые первыми'),
    ('10b_all_pagination', None, dict(prepare=all_bottom, viewport=(1440, 900)),
     'Все статьи, низ списка: все 44 на одной странице без навигации — 24 на странице и ссылка «Далі»'),
    ('11_home_popular', None, dict(prepare=home_popular, element='#popular-block'),
     'Блок «Найпопулярніші»: порядок перевёрнут, самая популярная статья последней — самая популярная первой'),
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, path, opts, note in CASES:
            opts = dict(opts)
            for label in ('before', 'after'):
                ctx = browser.new_context(viewport={'width': opts.get('viewport', (1440, 900))[0],
                                                    'height': opts.get('viewport', (1440, 900))[1]},
                                          has_touch=opts.get('viewport', (1440,))[0] < 800)
                try:
                    shot(ctx, name, path, label, **{k: v for k, v in opts.items() if k != 'viewport'},
                         viewport=opts.get('viewport', (1440, 900)))
                    print('ok', name, label)
                except Exception as exc:
                    print('FAILED', name, label, str(exc).splitlines()[0][:120])
                ctx.close()
            notes.append((name, note))
        browser.close()
    lines = ['# Скриншоты «до / после»', '',
             'Слева `*_before.png` — исходный код (`a240822`), справа `*_after.png` — текущий HEAD. Одни и те же '
             'синтетические данные (`fg_seed.py`), один и тот же браузер (Chromium, Playwright).', '']
    for name, note in notes:
        lines += [f'## {name}', '', note, '', f'| до | после |', '|---|---|',
                  f'| ![]({name}_before.png) | ![]({name}_after.png) |', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
