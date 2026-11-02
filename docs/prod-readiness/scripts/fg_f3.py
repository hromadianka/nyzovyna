"""F3: effect of render-blocking external resources. Chromium only. Simulated delays via route (no real network)."""
import json, statistics, time
from playwright.sync_api import sync_playwright
from fg_common import *

def run(br, mode, delay_ms, page_path, runs=3):
    res = []
    for _ in range(runs):
        ctx = br.new_context(viewport={'width': 1440, 'height': 900})
        def handler(route):
            u = route.request.url
            if is_local(u): return route.continue_()
            if 'ckeditor.com' in u:
                if mode in ('ck_delay', 'both_delay'):
                    time.sleep(delay_ms / 1000) if False else None
                    ctx_wait(route, delay_ms, 'application/javascript')
                    return
                if mode == 'ck_hang':
                    return  # never answered: simulates blackholed/slow CDN
            if 'cdnfonts.com' in u:
                if mode in ('font_delay', 'both_delay'):
                    ctx_wait(route, delay_ms, 'text/css'); return
            if 'recaptcha' in u: return route.abort('failed')
            return route.abort('failed')
        def ctx_wait(route, ms, ctype):
            # sync API: use a timer via page.wait_for_timeout is not available inside handler -> use time.sleep (blocks dispatcher, acceptable for sim)
            time.sleep(ms / 1000); route.fulfill(status=200, content_type=ctype, body='')
        ctx.route('**/*', handler)
        pg = ctx.new_page()
        t0 = time.time()
        try:
            pg.goto(BASE + page_path, wait_until='commit', timeout=60000)
            pg.wait_for_function("performance.getEntriesByName('first-contentful-paint').length > 0", timeout=20000 if mode != 'ck_hang' else 12000)
            fcp = pg.evaluate("performance.getEntriesByName('first-contentful-paint')[0].startTime")
        except Exception as e:
            fcp = None
        dcl = pg.evaluate("(() => { const n = performance.getEntriesByType('navigation')[0]; return n.domContentLoadedEventEnd })()") if fcp else None
        res.append({'fcp': fcp, 'dcl': dcl, 'wall_s': round(time.time() - t0, 1)})
        ctx.close()
    return res

with sync_playwright() as p:
    br = p.chromium.launch()
    out = {}
    for page_path in ('/', '/article/test-article-0/'):
        for mode, delay in (('baseline_abort', 0), ('ck_delay', 2000), ('font_delay', 2000), ('both_delay', 2000), ('ck_hang', 0)):
            r = run(br, mode, delay, page_path, runs=2 if mode == 'ck_hang' else 3)
            out[f'{page_path} {mode} {delay}ms'] = r
            f = [x['fcp'] for x in r if x['fcp']]
            print(page_path, mode, delay, 'FCP median ms', round(statistics.median(f)) if f else None, 'n_ok', len(f), '/', len(r))
    json.dump(out, open(SP + '/f3.json', 'w'), indent=1)
