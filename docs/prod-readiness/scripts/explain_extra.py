"""D3 supplement (nyz_load only): restore comment FK index after explain_mysql.py, then test pagination (LIMIT 20) and FULLTEXT as search alternative."""
import time, statistics
import django
django.setup()
from django.db import connection
assert connection.settings_dict['NAME'] == 'nyz_load'
cur = connection.cursor()
cur.execute("SELECT index_name FROM information_schema.statistics WHERE table_schema='nyz_load' AND table_name='app_comment'")
names = {r[0] for r in cur.fetchall()}
if 'ix_comment_art_created' in names:   # restore baseline: FK index on article_id only (name of the Django-generated one)
    cur.execute('ALTER TABLE app_comment ADD INDEX tmp_art (article_id), DROP INDEX ix_comment_art_created')
    names.add('tmp_art')
if 'tmp_art' in names:
    cur.execute('ALTER TABLE app_comment RENAME INDEX tmp_art TO app_comment_article_id_c87ecbda_fk_app_article_id')
cur.execute("SELECT index_name FROM information_schema.statistics WHERE table_schema='nyz_load' AND table_name IN ('app_comment','app_article')")
print('indexes now:', sorted({r[0] for r in cur.fetchall()}))
def med(sql, n=7):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); cur.execute(sql); r = cur.fetchall(); ts.append((time.perf_counter() - t) * 1000)
    return len(r), round(statistics.median(ts), 1)
SEL = 'SELECT id,name,text,slug,image,language,views,publish_at FROM app_article'
base = {
 'all ua pub, no limit': f"{SEL} WHERE language='ua' AND is_published=1",
 'all ua pub ORDER BY publish_at DESC LIMIT 20 (no idx)': f"{SEL} WHERE language='ua' AND is_published=1 ORDER BY publish_at DESC LIMIT 20",
 'search common ILIKE %стаття%': f"{SEL} WHERE is_published=1 AND (name LIKE '%стаття%' OR text LIKE '%стаття%')",
 'search common LIKE ... ORDER BY publish_at DESC LIMIT 20 (no idx)': f"{SEL} WHERE is_published=1 AND (name LIKE '%стаття%' OR text LIKE '%стаття%') ORDER BY publish_at DESC LIMIT 20",
 'search rare LIKE': f"{SEL} WHERE is_published=1 AND (name LIKE '%квазіпульсар%' OR text LIKE '%квазіпульсар%')",
}
print('--- without indexes'); [print(' ', k, med(q)) for k, q in base.items()]
cur.execute('CREATE INDEX ix_lang_pub_publish ON app_article (language, is_published, publish_at)')
print('--- with ix_lang_pub_publish'); print(' ', 'all ua pub ORDER BY publish_at DESC LIMIT 20', med(base['all ua pub ORDER BY publish_at DESC LIMIT 20 (no idx)'.replace('(no idx)', '(no idx)')]))
cur.execute('DROP INDEX ix_lang_pub_publish ON app_article')
cur.execute('CREATE FULLTEXT INDEX ft_name_text ON app_article (name, text)')
print('--- FULLTEXT (word match, not substring! different semantics)')
for w in ('квазіпульсар', 'стаття'):
    print(' ', w, med(f"{SEL} WHERE is_published=1 AND MATCH(name,text) AGAINST ('{w}' IN BOOLEAN MODE)"))
cur.execute("SELECT ROUND(index_length/1048576,1) FROM information_schema.tables WHERE table_schema='nyz_load' AND table_name='app_article'"); print('  index size MB with FT:', cur.fetchone())
cur.execute('DROP INDEX ft_name_text ON app_article')
