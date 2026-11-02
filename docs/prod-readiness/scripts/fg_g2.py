"""G2: SEO checks over HTTP on localhost only (requests + lxml + feedparser)."""
import json, re, requests, feedparser
from lxml import html, etree
from fg_common import *
PAGES = [p for p in PUBLIC] + [('article_draft', '/article/draft-ua/'), ('article_future', '/article/future-ua/')]
for name, path in PAGES:
    r = requests.get(BASE + path, timeout=10)
    t = html.fromstring(r.content) if r.content else None
    if t is None: continue
    q = lambda x: t.xpath(x)
    rec = {'status': r.status_code, 'title': ''.join(q('//title/text()')), 'desc': q('//meta[@name="description"]/@content'), 'canonical': q('//link[@rel="canonical"]/@href'),
           'og': q('//meta[starts-with(@property,"og:")]/@property'), 'twitter': q('//meta[starts-with(@name,"twitter:")]/@name'), 'hreflang': q('//link[@hreflang]/@hreflang'),
           'alternate_links': q('//link[@rel="alternate"]/@href'), 'h1': [h.text_content().strip()[:50] for h in q('//h1')], 'jsonld': len(q('//script[@type="application/ld+json"]')),
           'microdata': len(q('//*[@itemtype]')), 'html_lang': q('/html/@lang'), 'robots_meta': q('//meta[@name="robots"]/@content'),
           'imgs': len(q('//img')), 'imgs_no_alt_attr': len([i for i in q('//img') if i.get('alt') is None]), 'imgs_empty_alt': len([i for i in q('//img') if i.get('alt') == '']),
           'bg_image_cards_div': len(q('//div[contains(@style,"background: url")]')), 'viewport': q('//meta[@name="viewport"]/@content'), 'h2': len(q('//h2')), 'h3': len(q('//h3'))}
    print(name, path, json.dumps(rec, ensure_ascii=False))
print('--- robots.txt', requests.get(BASE + '/robots.txt').status_code)
print('--- favicon.ico', requests.get(BASE + '/favicon.ico').status_code)
r = requests.get(BASE + '/sitemap.xml'); print('sitemap', r.status_code, r.headers.get('content-type'), len(r.content))
root = etree.fromstring(r.content); ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
urls = root.xpath('//s:url', namespaces=ns); print('urls', len(urls))
for u in urls: print('  ', u.findtext('s:loc', namespaces=ns), u.findtext('s:lastmod', namespaces=ns), u.findtext('s:changefreq', namespaces=ns), u.findtext('s:priority', namespaces=ns))
bad = []
for u in urls:
    loc = u.findtext('s:loc', namespaces=ns); path = re.sub(r'^https?://[^/]+', '', loc)
    rr = requests.get(BASE + path); 
    if rr.status_code != 200: bad.append((loc, rr.status_code))
print('sitemap urls not 200 on localhost:', bad)
for lang in ('ua', 'en'):
    r = requests.get(BASE + '/feed/', cookies={'django_language': lang}); print('--- feed', lang, r.status_code, r.headers.get('content-type'))
    f = feedparser.parse(r.content)
    print(' bozo', f.bozo, 'title', f.feed.get('title'), 'link', f.feed.get('link'), 'lang', f.feed.get('language'), 'updated', f.feed.get('updated'), 'entries', len(f.entries))
    for e in f.entries: print('   ', e.get('title'), '|', e.get('link'), '|', e.get('published'), '| guid', e.get('id'), '| desc_len', len(e.get('summary', '')), '| author', e.get('author'))
print('--- 404 body head', requests.get(BASE + '/nope/').text[:120].replace('\n', ' '))
