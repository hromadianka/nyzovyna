"""Hypothesis 12: LocMemCache menu invalidation with N gunicorn workers.
Warm / on all workers, create a category through the real view (POST /create-category/), count how many follow-up GET / contain it.
Usage: python i_menu_cache_workers.py http://127.0.0.1:8123 <user> <password>"""
import sys, re, requests
base, user, pw = sys.argv[1:4]
s = requests.Session()
def tok(html):
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    return m.group(1) if m else s.cookies.get('csrftoken')
r = s.get(base + '/login/'); s.post(base + '/login/', data={'login': user, 'password': pw, 'csrfmiddlewaretoken': tok(r.text)}, headers={'Referer': base + '/login/'})
anon = lambda: requests.get(base + '/').text
for _ in range(60): anon()
name = 'Zzmenuprobe1'
r = s.get(base + '/editor-cabinet'); t = tok(r.text)
r = s.post(base + '/create-category/', data={'name_ua': name, 'name_en': name + 'En', 'csrfmiddlewaretoken': t}, headers={'Referer': base + '/editor-cabinet'}, allow_redirects=False)
print('create_category status', r.status_code)
hits = [name in anon() for _ in range(60)]
print('GET / after creation (anon, new connection each): %d/60 show new category' % sum(hits))
print('sequence:', ''.join('Y' if h else '.' for h in hits))
