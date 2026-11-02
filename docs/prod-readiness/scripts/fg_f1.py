"""F1: console/pageerror/failed requests per page x browser x viewport. Output JSON to scratchpad."""
import json, sys
from playwright.sync_api import sync_playwright
from fg_common import *

PROBE = """() => {
  const h = document.querySelector('header'), m = document.querySelector('main');
  const first = m.querySelector('h1, h2, .article-wrapper, .form, form, table, p, div');
  const hb = h.getBoundingClientRect().bottom;
  const fr = first ? first.getBoundingClientRect() : null;
  return {ticker_id: !!document.getElementById('ticker'), ticker_cls: !!document.querySelector('.ticker'),
    themeToggle: !!document.getElementById('themeToggle'), main_inline_mt: m.style.marginTop || null,
    main_computed_mt: getComputedStyle(m).marginTop, header_h: h.offsetHeight, header_bottom: hb,
    first_content_top: fr ? Math.round(fr.top) : null, overlap_px: fr ? Math.round(hb - fr.top) : null,
    h1_count: document.querySelectorAll('h1').length, hscroll: document.documentElement.scrollWidth > innerWidth,
    scrollW: document.documentElement.scrollWidth, imgs_no_alt: [...document.images].filter(i => !i.hasAttribute('alt')).length}
}"""

def run():
    out = []
    with sync_playwright() as p:
        for bname in ('chromium', 'firefox', 'webkit'):
            br = getattr(p, bname).launch()
            for vp, (w, h) in VIEWPORTS.items():
                for authed in (False, True):
                    ctx = br.new_context(viewport={'width': w, 'height': h})
                    ext = []
                    install_routes(ctx, ext)
                    page = ctx.new_page()
                    if authed:
                        login(page)
                    for name, path in (AUTH if authed else PUBLIC):
                        rec = {'browser': bname, 'vp': vp, 'page': name, 'path': path, 'console': [], 'pageerror': [], 'failed': [], 'http_err': [], 'http_reqs': []}
                        page.on('console', lambda m, r=rec: r['console'].append((m.type, m.text[:200], m.location.get('url', '')[:100])) if m.type in ('error', 'warning') else None)
                        page.on('pageerror', lambda e, r=rec: r['pageerror'].append(str(e)[:250]))
                        page.on('requestfailed', lambda q, r=rec: r['failed'].append((q.url[:120], (q.failure or '')[:60])))
                        page.on('response', lambda s, r=rec: r['http_err'].append((s.status, s.url[:120])) if s.status >= 400 else None)
                        page.on('request', lambda q, r=rec: r['http_reqs'].append(q.url) if q.url.startswith('http://') and 'localhost' not in q.url and '127.0.0.1' not in q.url else None)
                        try:
                            resp = page.goto(BASE + path, wait_until='load', timeout=30000)
                            page.wait_for_timeout(700)
                            rec['status'] = resp.status
                            rec['probe'] = page.evaluate(PROBE)
                        except Exception as e:
                            rec['nav_error'] = str(e)[:200]
                        out.append(rec)
                        page.close(); page = ctx.new_page()
                    ctx.close()
            br.close()
    json.dump(out, open(SP + '/f1.json', 'w'), ensure_ascii=False, indent=1)
    print('done', len(out))
run()
