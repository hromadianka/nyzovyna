"""D3: EXPLAIN + timing of the real ORM queries on nyz_load (MySQL 8). Usage: explain_mysql.py [--with-indexes]
With --with-indexes it creates trial indexes ONLY in nyz_load (refuses other DBs) and re-measures; indexes are dropped at the end."""
import sys, time, statistics, json
import django
django.setup()
from django.db import connection
from django.db.models import Q, F
from django.utils.timezone import now
from app.models import Article, Comment, Category
assert connection.settings_dict['NAME'] == 'nyz_load'
cur = connection.cursor()
cat = Category.objects.get(slug='cat-l-000'); root = Category.objects.get(slug='cat-r-00')
art = Article.objects.get(slug='article-cbig')
Q_ = {
 'home_latest ua pub order -publish_at LIMIT5': Article.objects.filter(language='ua', is_published=True).order_by('-publish_at')[:5],
 'home_popular ua pub order -views LIMIT10': Article.objects.filter(language='ua', is_published=True).order_by('-views')[:10],
 'all_articles ua pub (no order, no limit)': Article.objects.filter(language='ua', is_published=True),
 'article page: pub order -views LIMIT2 (no language)': Article.objects.filter(is_published=True).order_by('-views')[:2],
 'category (leaf) M2M ua pub': Article.objects.filter(language='ua', categories__in=[cat], is_published=True),
 'category (root) M2M ua pub': Article.objects.filter(language='ua', categories__in=[root], is_published=True),
 'recommended: categories=root pub order -views LIMIT2': Article.objects.filter(categories=root.id, is_published=True).order_by('-views')[:2],
 'search rare name|text icontains': Article.objects.filter(is_published=True, publish_at__lte=now()).filter(Q(name__icontains='квазіпульсар') | Q(text__icontains='квазіпульсар')),
 'search common name|text icontains': Article.objects.filter(is_published=True, publish_at__lte=now()).filter(Q(name__icontains='стаття') | Q(text__icontains='стаття')),
 'search name only icontains': Article.objects.filter(is_published=True).filter(name__icontains='квазіпульсар'),
 'comments by article order -created_at': Comment.objects.filter(article=art).order_by('-created_at'),
 'menu: all categories': Category.objects.all(),
 'category children by parent': Category.objects.filter(parent=root),
 'author articles': Article.objects.filter(author__slug='author-heavy', is_published=True),
 'feed: ua pub publish_at<=now order -created_at LIMIT5': Article.objects.filter(language='ua', is_published=True, publish_at__lte=now()).order_by('-created_at')[:5],
 'sitemap: pub publish_at<=now order pk': Article.objects.filter(is_published=True, publish_at__lte=now()).order_by('pk'),
}
def run(label):
    out = {}
    for name, qs in Q_.items():
        sql, params = qs.query.sql_with_params()
        cur.execute('EXPLAIN FORMAT=TREE ' + sql, params); tree = cur.fetchone()[0]
        ts = []
        for _ in range(5):
            t = time.perf_counter(); cur.execute(sql, params); rows = cur.fetchall(); ts.append((time.perf_counter() - t) * 1000)
        cur.execute('EXPLAIN ' + sql, params)
        cols = [d[0] for d in cur.description]; plan = [dict(zip(cols, r)) for r in cur.fetchall()]
        brief = '; '.join(f"{p['table']}:{p['type']}:key={p['key']}:rows={p['rows']}:extra={p['Extra']}" for p in plan)
        out[name] = dict(rows=len(rows), med_ms=round(statistics.median(ts), 1), plan=brief)
        print(f"[{label}] {name}\n   rows_returned={len(rows)} median={out[name]['med_ms']}ms\n   plan: {brief}")
    return out
cur.execute("SELECT table_name, index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) FROM information_schema.statistics WHERE table_schema='nyz_load' AND table_name IN ('app_article','app_comment','app_category','app_article_categories','app_author') GROUP BY table_name,index_name")
print('EXISTING INDEXES:'); [print('  ', r) for r in cur.fetchall()]
cur.execute('SELECT table_name, table_rows, ROUND(data_length/1048576,1), ROUND(index_length/1048576,1) FROM information_schema.tables WHERE table_schema="nyz_load" AND table_name LIKE "app_%"')
print('TABLE SIZES (rows~, data MB, index MB):'); [print('  ', r) for r in cur.fetchall()]
cur.execute('ANALYZE TABLE app_article, app_comment, app_category, app_article_categories')
before = run('before')
if '--with-indexes' in sys.argv:
    idx = [
     ('app_article', 'ix_lang_pub_publish', '(language, is_published, publish_at)'),
     ('app_article', 'ix_lang_pub_views', '(language, is_published, views)'),
     ('app_article', 'ix_pub_views', '(is_published, views)'),
     ('app_article', 'ix_pub_publish', '(is_published, publish_at)'),
     ('app_comment', 'ix_comment_art_created', '(article_id, created_at)'),
    ]
    for t, n, c in idx:
        cur.execute(f'CREATE INDEX {n} ON {t} {c}')
    cur.execute('ANALYZE TABLE app_article, app_comment')
    try:
        after = run('after')
    finally:
        for t, n, c in idx:
            cur.execute(f'DROP INDEX {n} ON {t}')
    print('\nSUMMARY before -> after (ms)')
    for k in before: print(f"  {k}: {before[k]['med_ms']} -> {after[k]['med_ms']}")
