"""F2 interaction scenarios. Output printed + JSON in scratchpad."""
import json, sys, traceback
from playwright.sync_api import sync_playwright
from fg_common import *

R = {}
def rec(b, name, val):
    R.setdefault(b, {})[name] = val
    print(b, name, json.dumps(val, ensure_ascii=False)[:600])

def mk(br, w, h, touch=False, stub=False):
    ctx = br.new_context(viewport={'width': w, 'height': h}, has_touch=touch, is_mobile=touch and w < 600)
    ext = []; install_routes(ctx, ext, recaptcha_stub=stub)
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)[:150]))
    return ctx, pg, errs

DISP = "(sel) => { const e = document.querySelector(sel); if(!e) return null; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return {display: cs.display, vis: cs.visibility, w: Math.round(r.width), h: Math.round(r.height)} }"

def scenarios(bname, br):
    # 1 desktop hover
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/'); pg.wait_for_timeout(500)
    sub = '.parent-category:first-child > .sub-menu'
    before = pg.evaluate(DISP, sub)
    pg.hover('.parent-category:first-child > a'); pg.wait_for_timeout(200)
    open1 = pg.evaluate(DISP, sub)
    pg.hover('.sub-menu .parent-category > a'); pg.wait_for_timeout(200)
    nested = pg.evaluate(DISP, '.sub-menu.iteration')
    pg.mouse.move(700, 600); pg.wait_for_timeout(900)
    after = pg.evaluate(DISP, sub)
    rec(bname, 'F2.1 desktop hover submenu', {'before': before, 'on_hover': open1, 'nested_hover': nested, 'after_leave_900ms': after})
    # language dropdown hover
    pg.hover('.dropbtn'); pg.wait_for_timeout(200)
    rec(bname, 'F2.1b lang dropdown hover', pg.evaluate(DISP, '.dropdown-content'))
    ctx.close()

    # 2 mobile tap
    ctx, pg, errs = mk(br, 375, 812, touch=True)
    pg.goto(BASE + '/'); pg.wait_for_timeout(500)
    res = {'menu_hidden_initially': pg.evaluate(DISP, '.menu')}
    pg.tap('.burger-icon'); pg.wait_for_timeout(300)
    res['menu_after_burger'] = pg.evaluate(DISP, '.menu')
    res['body_overflow_class'] = pg.evaluate("document.body.classList.contains('overflow-hidden')")
    res['burger_top_element_at_icon'] = pg.evaluate("(() => { const r = document.querySelector('.burger-icon').getBoundingClientRect(); const e = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2); return e.className || e.tagName })()")
    res['sub_before_tap'] = pg.evaluate(DISP, '.parent-category:first-child > .sub-menu')
    url0 = pg.url
    pg.tap('.parent-category:first-child > a'); pg.wait_for_timeout(500)
    res['sub_after_tap_parent'] = pg.evaluate(DISP, '.parent-category:first-child > .sub-menu')
    res['url_changed_after_parent_tap'] = pg.url != url0
    pg.tap('.parent-category:first-child > a'); pg.wait_for_timeout(500)
    res['url_changed_after_second_tap'] = pg.url != url0
    res['sub_after_second_tap'] = pg.evaluate(DISP, '.parent-category:first-child > .sub-menu')
    pg.tap('.sub-menu .parent-category > a'); pg.wait_for_timeout(500)
    res['nested_sub_after_tap'] = pg.evaluate(DISP, '.sub-menu.iteration')
    res['url_after_tap_child_with_children'] = pg.url
    # leaf
    try:
        pg.tap('.sub-menu.iteration a'); pg.wait_for_timeout(800)
        res['url_after_tap_leaf'] = pg.url
    except Exception as e: res['leaf_err'] = str(e)[:100]
    # can the menu be closed / is burger usable after navigation
    rec(bname, 'F2.2 mobile menu tap', res)
    ctx.close()
    # 2b 900px touch tablet
    ctx, pg, errs = mk(br, 900, 1000, touch=True)
    pg.goto(BASE + '/'); pg.wait_for_timeout(500)
    res = {'burger_visible': pg.evaluate(DISP, '.burger-icon'), 'menu_display': pg.evaluate(DISP, '.menu')}
    pg.tap('.burger-icon'); pg.wait_for_timeout(300)
    res['menu_after_burger'] = pg.evaluate(DISP, '.menu')
    pg.tap('.parent-category:first-child > a'); pg.wait_for_timeout(800)
    res['url_after_tap_parent_at_900'] = pg.url
    res['sub_display_before_nav'] = None
    rec(bname, 'F2.2b 900px touch (burger shown by CSS<=1000, JS tap mode only <=768)', res)
    ctx.close()

    # 3 language switch on article
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/article/test-article-0/'); pg.wait_for_timeout(400)
    res = {'start_menu_first': pg.inner_text('.menu .menu-link'), 'start_btn': pg.inner_text('.dropbtn').strip(), 'start_h1': pg.inner_text('h1')}
    pg.hover('.dropbtn'); pg.click('button[name=language][value=en]'); pg.wait_for_load_state('load')
    res['after_en_url'] = pg.url; res['after_en_menu_first'] = pg.inner_text('.menu .menu-link'); res['after_en_btn'] = pg.inner_text('.dropbtn').strip()
    res['after_en_h1'] = pg.inner_text('h1'); res['html_lang'] = pg.evaluate('document.documentElement.lang')
    res['cookies'] = [c['name'] + '=' + c['value'] for c in ctx.cookies()]
    pg.goto(BASE + '/'); res['home_after_en_first_h1'] = pg.inner_text('h1'); res['home_first_card'] = pg.inner_text('.article-card h3').strip()
    # keyboard-only: tab to dropbtn, Enter
    pg.keyboard.press('Tab')
    rec(bname, 'F2.3 language switch', res)
    ctx.close()
    # persistence of query string / page
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/search/?q=article'); pg.hover('.dropbtn'); pg.click('button[name=language][value=en]'); pg.wait_for_load_state('load')
    rec(bname, 'F2.3b lang switch from /search/?q=article', {'url_after': pg.url})
    ctx.close()

    # 4 theme toggle
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/article/test-article-0/'); pg.wait_for_timeout(400)
    res = {'main_class_before': pg.evaluate("document.querySelector('main').className"), 'bg_before': pg.evaluate("getComputedStyle(document.querySelector('main')).backgroundColor")}
    pg.click('label[for=themeToggle]'); pg.wait_for_timeout(200)
    res['main_class_after'] = pg.evaluate("document.querySelector('main').className"); res['body_class_after'] = pg.evaluate("document.body.className")
    res['bg_after'] = pg.evaluate("getComputedStyle(document.querySelector('main')).backgroundColor")
    res['label_has_text_or_aria'] = pg.evaluate("(() => {const l=document.querySelector('label[for=themeToggle]'); return {text: l.textContent.trim(), aria: l.getAttribute('aria-label')}})()")
    res['input_hidden_attr'] = pg.evaluate("document.getElementById('themeToggle').hidden")
    pg.reload(); pg.wait_for_timeout(300)
    res['main_class_after_reload'] = pg.evaluate("document.querySelector('main').className")
    pg.keyboard.press('Tab')
    rec(bname, 'F2.4 theme toggle on article', res)
    pg.goto(BASE + '/'); pg.wait_for_timeout(300)
    rec(bname, 'F2.4b themeToggle on home', {'exists': pg.evaluate("!!document.getElementById('themeToggle')")})
    ctx.close()

    # 5 comments
    ctx, pg, errs = mk(br, 1440, 900, stub=True)
    pg.goto(BASE + '/article/test-article-2/'); pg.wait_for_timeout(500)
    res = {'recaptcha_widget_div': pg.evaluate("!!document.querySelector('.g-recaptcha')"), 'recaptcha_div_sitekey': pg.evaluate("(document.querySelector('.g-recaptcha')||{}).dataset ? document.querySelector('.g-recaptcha').dataset.sitekey : null")}
    n0 = pg.evaluate("document.querySelectorAll('.comment').length")
    pg.fill('form.comment-form:not(.reply-form form) input[name=author], .comments > form input[name=author]', 'Tester')
    pg.fill('.comments > form textarea[name=text]', 'Hello from playwright')
    # submit without captcha token
    pg.click('.comments > form .comment-btn'); pg.wait_for_load_state('load')
    res['after_submit_without_token_url'] = pg.url; res['comments_after_no_token'] = pg.evaluate("document.querySelectorAll('.comment').length")
    res['silent_failure_message_shown'] = pg.evaluate("/captcha|помилк|error/i.test(document.querySelector('.comments').innerText)")
    pg.fill('.comments > form input[name=author]', 'Tester'); pg.fill('.comments > form textarea[name=text]', 'Hello from playwright')
    pg.evaluate("(() => {const i=document.createElement('input'); i.type='hidden'; i.name='g-recaptcha-response'; i.value='mock'; document.querySelector('.comments > form').appendChild(i)})()")
    pg.click('.comments > form .comment-btn'); pg.wait_for_load_state('load'); pg.wait_for_timeout(300)
    res['comments_after_token'] = pg.evaluate("document.querySelectorAll('.comment').length"); res['n0'] = n0
    res['final_url'] = pg.url
    rec(bname, 'F2.5 root comment (mock captcha token)', res)
    # reply (article-0 has comments)
    pg.goto(BASE + '/article/test-article-0/'); pg.wait_for_timeout(400)
    res = {}
    res['toggleReplyForm_defined'] = pg.evaluate("typeof toggleReplyForm")
    res['reply_form_display_before'] = pg.evaluate("getComputedStyle(document.querySelector('.reply-form')).display")
    e0 = len(errs)
    pg.click('a[onclick^=toggleReplyForm] >> nth=0'); pg.wait_for_timeout(300)
    res['reply_form_display_after_click'] = pg.evaluate("getComputedStyle(document.querySelector('.reply-form')).display")
    res['pageerrors_on_click'] = errs[e0:]
    res['reply_link_is_focusable_anchor_without_href'] = pg.evaluate("(() => { const a=document.querySelector('a[onclick^=toggleReplyForm]'); return {href: a.getAttribute('href'), tabindex: a.tabIndex} })()")
    # force-visible to test the reply POST server path
    pg.evaluate("document.querySelector('.reply-form').style.display='block'")
    cnt = pg.evaluate("document.querySelectorAll('.comment').length")
    pg.fill('.reply-form input[name=author]', 'Replier'); pg.fill('.reply-form textarea[name=text]', 'Reply text'); pg.click('.reply-form .comment-btn'); pg.wait_for_load_state('load')
    res['comments_count_before_after'] = [cnt, pg.evaluate("document.querySelectorAll('.comment').length")]
    res['reply_prefill_textarea_example'] = None
    rec(bname, 'F2.5b reply', res)
    ctx.close()

    # 6 search
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/'); pg.fill('.search-form input[name=q]', 'article 3'); pg.press('.search-form input[name=q]', 'Enter'); pg.wait_for_load_state('load')
    res = {'url': pg.url, 'cards': pg.evaluate("document.querySelectorAll('.article-card').length"), 'input_prefilled': pg.input_value('.search-form input[name=q]')}
    pg.goto(BASE + '/search/?q=zzzznothing'); res['empty_results_text'] = pg.inner_text('main').strip()[:80]
    pg.goto(BASE + '/search/?q='); res['empty_q_cards'] = pg.evaluate("document.querySelectorAll('.article-card').length")
    res['search_input_label'] = pg.evaluate("(() => {const i=document.querySelector('.search-form input'); return {id:i.id, aria:i.getAttribute('aria-label'), labels:i.labels.length, placeholder:i.placeholder, btn_aria: document.querySelector('.search-button').getAttribute('aria-label')}})()")
    res['search_form_position_top_of_page'] = pg.evaluate("document.querySelector('.search-form').getBoundingClientRect().top + scrollY")
    rec(bname, 'F2.6 search', res)
    ctx.close()

    # 7 keyboard
    for vpn, (w, h) in (('1440', (1440, 900)), ('375', (375, 812))):
        ctx, pg, errs = mk(br, w, h)
        pg.goto(BASE + '/'); pg.wait_for_timeout(400)
        seq = []
        for i in range(16):
            pg.keyboard.press('Tab')
            seq.append(pg.evaluate("(() => {const e=document.activeElement; return (e.tagName + ':' + (e.className||'') + ':' + (e.textContent||'').trim().slice(0,18) + (e.closest('.sub-menu') ? ' [IN-SUBMENU]' : '') + (e.closest('.burger-menu') ? ' [IN-HEADER]' : ''))})()"))
        sub_vis = pg.evaluate(DISP, '.parent-category:first-child > .sub-menu')
        res = {'tab_sequence': seq, 'first_submenu_after_tabbing': sub_vis,
               'submenu_link_focused_ever': any('IN-SUBMENU' in s for s in seq), 'burger_focused_ever': any('burger' in s for s in seq)}
        rec(bname, f'F2.7 keyboard Tab @ {vpn}', res)
        # focus-visible styling on links: outline
        res2 = pg.evaluate("(() => { const a=document.querySelector('.menu-link'); a.focus(); const cs=getComputedStyle(a); return {outline: cs.outlineStyle + ' ' + cs.outlineWidth, focus_visible: a.matches(':focus-visible')} })()")
        rec(bname, f'F2.7b focus style on first menu link @ {vpn}', res2)
        ctx.close()
    # dropbtn via keyboard
    ctx, pg, errs = mk(br, 1440, 900)
    pg.goto(BASE + '/'); pg.focus('.dropbtn'); pg.keyboard.press('Enter'); pg.wait_for_timeout(200)
    st = pg.evaluate(DISP, '.dropdown-content')
    pg.keyboard.press('Tab'); f = pg.evaluate("document.activeElement.textContent.trim()")
    rec(bname, 'F2.7c lang dropdown keyboard Enter on button', {'dropdown_after_enter': st, 'next_tab_focus': f, 'aria_expanded': pg.evaluate("document.querySelector('.dropbtn').getAttribute('aria-expanded')")})
    ctx.close()

with sync_playwright() as p:
    for bname in (sys.argv[1:] or ['chromium', 'firefox', 'webkit']):
        br = getattr(p, bname).launch()
        try: scenarios(bname, br)
        except Exception: traceback.print_exc()
        br.close()
json.dump(R, open(SP + '/f2.json', 'w'), ensure_ascii=False, indent=1)
