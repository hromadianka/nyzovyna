"""F4: screenshots (chromium, CDN blocked => fallback fonts) of key pages in 3 viewports, palette-quantized to keep files small."""
import io
from playwright.sync_api import sync_playwright
from PIL import Image
from fg_common import *
OUT = '/Users/d/Development/Projects/nyz/docs/prod-readiness/evidence/screens'
PAGES = [('home', '/'), ('article', '/article/test-article-0/'), ('category', '/category/culture/'), ('search', '/search/?q=article')]
with sync_playwright() as p:
    br = p.chromium.launch()
    for vp, (w, h) in VIEWPORTS.items():
        ctx = br.new_context(viewport={'width': w, 'height': h}); install_routes(ctx, [])
        for name, path in PAGES:
            pg = ctx.new_page(); pg.goto(BASE + path, wait_until='load'); pg.wait_for_timeout(500)
            im = Image.open(io.BytesIO(pg.screenshot())).convert('RGB')
            im = im.quantize(colors=48, method=Image.Quantize.MEDIANCUT)
            im.save(f'{OUT}/{name}_{vp}.png', optimize=True); pg.close()
        ctx.close()
    br.close()
