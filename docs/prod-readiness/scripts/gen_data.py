"""Synthetic data generator. random.seed(42). Usage: gen_data.py <large|small>
large: 10000 articles/500 cats/50000 comments/200 authors; small: 100/20/500/10.
Special slugs: article-c5 (5 comments), article-cbig (5000 large / 300 small), author-heavy (500 / 50 articles)."""
import os, sys, random, time, uuid, datetime
import django
django.setup()
from django.db import connection
from django.utils import timezone
from app.models import Author, Category, Article, Comment, AboutUsText

random.seed(42)
SIZE = sys.argv[1] if len(sys.argv) > 1 else 'large'
P = dict(large=dict(A=10000, C=500, M=50000, AU=200, BIGC=5000, HEAVY=500, roots=10, mids=40),
         small=dict(A=100, C=20, M=500, AU=10, BIGC=300, HEAVY=50, roots=3, mids=5))[SIZE]
for m in (Article, Comment):
    m._meta.get_field('created_at').auto_now_add = False  # let us spread dates

UA = "стаття низовина культура місто дорога вода історія людина час життя слово думка місце сила земля пам'ять голос шлях світ річка книга театр музика кіно політика економіка наука технології війна мир свобода право суспільство освіта здоров'я спорт подорож природа ліс гора море вітер".split()
EN = "article lowland culture city road water history person time life word thought place power land memory voice path world river book theatre music cinema politics economy science technology war peace freedom law society education health sport travel nature forest mountain sea wind".split()
RARE = ['квазіпульсар', 'zymurgy']   # rare terms, each injected in ~10 articles
now = timezone.now()

def words(lang, n):
    w = UA if lang == 'ua' else EN
    return ' '.join(random.choice(w) for _ in range(n))

def html(lang):
    parts = []
    size = random.randint(3000, 6000)
    cur = 0
    while cur < size:
        r = random.random()
        if r < .12:
            s = f'<h2>{words(lang, 4).capitalize()}</h2>'
        elif r < .2:
            s = '<ul>' + ''.join(f'<li>{words(lang, 8)}</li>' for _ in range(3)) + '</ul>'
        elif r < .27:
            s = f'<blockquote><p><em>{words(lang, 14)}.</em></p></blockquote>'
        else:
            s = (f'<p>{words(lang, 25).capitalize()}, <strong>{words(lang, 3)}</strong> {words(lang, 20)}. '
                 f'<a href="https://example.com/{random.randint(1,999)}">{words(lang, 2)}</a> {words(lang, 25)}.</p>')
        parts.append(s); cur += len(s.encode())
    return '\n'.join(parts)

t0 = time.time()
tt = {}
def lap(name):
    tt[name] = round(time.time() - t0 - sum(tt.values()), 2)

# ---- authors
authors = []
for i in range(P['AU']):
    slug = 'author-heavy' if i == 0 else f'author-{i:03d}'
    authors.append(Author(slug=slug, name_en=f'Author {i}', name_ua=f'Автор {i}',
                          description_en=words('en', 30), description_ua=words('ua', 30)))
Author.objects.bulk_create(authors); lap('authors')

# ---- categories (3 levels)
cats = []; level = {0: [], 1: [], 2: []}
nr, nm = P['roots'], P['mids']
for i in range(nr):
    cats.append(Category(slug=f'cat-r-{i:02d}', name_ua=f'Розділ {i}', name_en=f'Section {i}', order=i)); level[0].append(cats[-1])
for i in range(nm):
    par = level[0][i % nr]
    cats.append(Category(slug=f'cat-m-{i:02d}', name_ua=f'Підрозділ {i}', name_en=f'Subsection {i}', parent=par, order=i)); level[1].append(cats[-1])
for i in range(P['C'] - nr - nm):
    par = level[1][i % nm]
    cats.append(Category(slug=f'cat-l-{i:03d}', name_ua=f'Тема {i}', name_en=f'Topic {i}', parent=par, order=i)); level[2].append(cats[-1])
Category.objects.bulk_create(cats); lap('categories')
leaves = level[2]
# skewed weights so some categories are huge, some tiny
weights = [1 / (k + 1) ** 0.9 for k in range(len(leaves))]

# ---- articles
arts = []; through = []
Through = Article.categories.through
n_pub = 0
for i in range(P['A']):
    lang = 'ua' if random.random() < .7 else 'en'
    if i < P['HEAVY']: au = authors[0]
    else: au = authors[1 + (i % (P['AU'] - 1))]
    pub = random.random() < .95
    pa = now - datetime.timedelta(days=random.randint(0, 730), seconds=random.randint(0, 86399))
    if not pub and random.random() < .5:
        pa = now + datetime.timedelta(days=random.randint(1, 30))
    slug = {1000: 'article-c5', 1001: 'article-cbig'}.get(i) if P['A'] >= 2000 else {10: 'article-c5', 11: 'article-cbig'}.get(i)
    slug = slug or f'article-{i:05d}'
    if slug in ('article-c5', 'article-cbig'):
        pub, lang = True, 'ua'; pa = now - datetime.timedelta(days=3)
    text = html(lang)
    if i % 1000 == 7: text = text.replace('<p>', f'<p>{RARE[0]} ', 1)
    if i % 1000 == 8: text = text.replace('<p>', f'<p>{RARE[1]} ', 1)
    name = words(lang, random.randint(4, 10)).capitalize()
    a = Article(slug=slug, name=name, text=text, language=lang, author=au, views=int(random.expovariate(1 / 300)),
                reactions=random.randint(0, 50), publish_at=pa, created_at=pa - datetime.timedelta(hours=1), is_published=pub)
    arts.append(a)
    chosen = set()
    for lf in random.choices(leaves, weights, k=random.randint(1, 3)):
        c = lf
        while c is not None:         # like the editor's publish(): add all ancestors
            chosen.add(c.id); c = c.parent
    for cid in chosen:
        through.append((a, cid))
Article.objects.bulk_create(arts, batch_size=500); lap('articles')
Through.objects.bulk_create([Through(article_id=a.id, category_id=cid) for a, cid in through], batch_size=2000); lap('article_categories')

# ---- comments
cz = []
def build(article, n):
    made = []   # (comment, depth)
    for j in range(n):
        if not made or random.random() < .45:
            parent, depth = None, 0
        else:
            cand = [m for m in made[-40:] if m[1] < 6]
            parent, depth = random.choice(cand) if cand else (None, 0)
            depth = depth + 1 if parent else 0
        c = Comment(article=article, author=f'user{random.randint(1,500)}', text=words('ua', random.randint(8, 40)).capitalize() + '.',
                    parent_comment=parent, created_at=now - datetime.timedelta(minutes=(n - j) * 7))
        made.append((c, depth)); cz.append(c)
by_slug = {a.slug: a for a in arts}
build(by_slug['article-c5'], 5); build(by_slug['article-cbig'], P['BIGC'])
rest = P['M'] - 5 - P['BIGC']
others = [a for a in arts if a.slug not in ('article-c5', 'article-cbig')]
cnt = {}
for a in random.choices(others, [1 / (k + 1) ** 0.6 for k in range(len(others))], k=rest):
    cnt[a.slug] = cnt.get(a.slug, 0) + 1
for s, n in cnt.items(): build(by_slug[s], n)
Comment.objects.bulk_create(cz, batch_size=1000); lap('comments')
AboutUsText.objects.update_or_create(pk=1, defaults=dict(text_ua=words('ua', 120), text_en=words('en', 120))); lap('about')
tt['TOTAL'] = round(time.time() - t0, 2)
print(SIZE, tt)
print({m.__name__: m.objects.count() for m in (Author, Category, Article, Comment)},
      'published', Article.objects.filter(is_published=True).count(), 'ua', Article.objects.filter(language='ua').count(),
      'max comments/article', max(cnt.values()), 'cats of cbig', by_slug['article-cbig'].categories.count())
