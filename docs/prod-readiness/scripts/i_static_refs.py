"""Scan templates for {% static %} refs and static/style.css url() refs; resolve via prod manifest storage.
Run: DJANGO_SETTINGS_MODULE=<wrapper with Manifest storage + scratch STATIC_ROOT> python i_static_refs.py (after collectstatic)."""
import re, glob, os, django
django.setup()
from django.contrib.staticfiles.storage import staticfiles_storage as st
from django.contrib.staticfiles import finders
from django.conf import settings
B = settings.BASE_DIR
pat = re.compile(r"""\{%\s*static\s+(['"])(.+?)\1""")
bad = 0; n = 0
for f in sorted(glob.glob(str(B / 'templates' / '*.html'))):
    for i, line in enumerate(open(f, encoding='utf-8'), 1):
        for m in pat.finditer(line):
            n += 1; p = m.group(2)
            found = finders.find(p)
            try: url = st.stored_name(p)
            except Exception as e: url = 'ERR %s' % type(e).__name__
            ok = bool(found) and not url.startswith('ERR')
            if not ok: bad += 1
            print('%s:%d static %r -> source=%s manifest=%s %s' % (os.path.relpath(f, B), i, p, bool(found), url, '' if ok else '<<< MISSING'))
cssp = B / 'static' / 'style.css'
for i, line in enumerate(open(cssp, encoding='utf-8'), 1):
    for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", line):
        u = m.group(1); n += 1
        if u.startswith(('http', 'data:')): print('static/style.css:%d external %s' % (i, u[:60])); continue
        target = (cssp.parent / u).resolve()
        ok = target.exists()
        if not ok: bad += 1
        print('static/style.css:%d url(%s) exists=%s %s' % (i, u, ok, '' if ok else '<<< MISSING'))
print('refs checked: %d, missing: %d' % (n, bad))
