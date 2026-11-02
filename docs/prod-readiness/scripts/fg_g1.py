"""G1: axe-core (node_modules/axe-core from scratchpad npm) on public pages. Chromium. External hosts blocked."""
import json, sys
from playwright.sync_api import sync_playwright
from fg_common import *
AXE = SP + '/node/node_modules/axe-core/axe.min.js'
pages = [p for p in PUBLIC if p[0] != '404'] + [('article_light_theme', '/article/test-article-0/')]
out = {}
with sync_playwright() as p:
    br = p.chromium.launch()
    for vp in ('1440', '375'):
        w, h = VIEWPORTS[vp]
        for name, path in pages:
            ctx = br.new_context(viewport={'width': w, 'height': h}); install_routes(ctx, []); pg = ctx.new_page()
            pg.goto(BASE + path, wait_until='load'); pg.wait_for_timeout(400)
            if name == 'article_light_theme':
                pg.click('label[for=themeToggle]'); pg.wait_for_timeout(200)
            pg.add_script_tag(path=AXE)
            r = pg.evaluate("axe.run(document, {resultTypes: ['violations']})")
            out[f'{name}@{vp}'] = [{'id': v['id'], 'impact': v['impact'], 'nodes': len(v['nodes']), 'sel': v['nodes'][0]['target'][0] if v['nodes'] else '', 'help': v['help']} for v in r['violations']]
            ctx.close()
    br.close()
json.dump(out, open(SP + '/g1.json', 'w'), ensure_ascii=False, indent=1)
# summary
agg = {}
for k, vs in out.items():
    for v in vs:
        a = agg.setdefault(v['id'], {'impact': v['impact'], 'help': v['help'], 'pages': {}, 'sel': v['sel']})
        a['pages'][k] = v['nodes']
for i, a in sorted(agg.items(), key=lambda x: ['critical', 'serious', 'moderate', 'minor'].index(x[1]['impact'])):
    print(i, a['impact'], '|', a['help'], '| ex:', a['sel'][:70]); print('    ', a['pages'])
