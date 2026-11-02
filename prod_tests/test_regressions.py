from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.models import Article, Category

from .helpers import Base, html_of, mk_article, mk_category, mk_comment, seed_site


def category_queries(ctx):
    return [q['sql'] for q in ctx.captured_queries if 'app_category' in q['sql'] and 'app_article_categories' not in q['sql']]


class KnownFixesStayFixed(Base):
    def test_menu_is_built_with_single_query_on_cache_miss(self):
        root = mk_category('r')
        for i in range(5):
            child = mk_category(f'c{i}', parent=root)
            mk_category(f'g{i}', parent=child)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertEqual(len(category_queries(ctx)), 1)

    def test_menu_costs_nothing_on_cache_hit(self):
        mk_category('r')
        self.client.get('/')
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertEqual(category_queries(ctx), [])

    def test_new_category_is_visible_immediately(self):
        self.client.get('/')
        mk_category('fresh')
        self.assertIn('/category/fresh/', html_of(self.get_ok('/')))

    def test_deleted_category_disappears_immediately(self):
        c = mk_category('gone')
        self.client.get('/')
        c.delete()
        self.assertNotIn('/category/gone/', html_of(self.get_ok('/')))

    def test_view_counter_updates_only_the_counter_column(self):
        a = mk_article('v')
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/article/v/')
        updates = [q['sql'] for q in ctx.captured_queries if q['sql'].lstrip().upper().startswith('UPDATE')]
        self.assertEqual(len(updates), 1)
        self.assertNotIn('"text"', updates[0].replace('`', '"'))

    def test_counter_survives_stale_in_memory_value(self):
        a = mk_article('stale', views=5)
        Article.objects.filter(pk=a.pk).update(views=50)
        self.client.get('/article/stale/')
        a.refresh_from_db()
        self.assertEqual(a.views, 51)

    def test_footer_links_resolve(self):
        seed_site(1)
        html = html_of(self.get_ok('/'))
        footer = html.split('<footer>')[1]
        for href in __import__('re').findall(r'href="(/[^"]*)"', footer):
            with self.subTest(href=href):
                self.assertEqual(self.client.get(href).status_code, 200)

    def test_feed_item_links_resolve(self):
        mk_article('feed-one')
        for link in __import__('re').findall(r'<link>https?://[^/]+(/article/[^<]+)</link>', html_of(self.get_ok('/feed/'))):
            self.assertEqual(self.client.get(link).status_code, 200)

    def test_sitemap_renders_and_locations_resolve(self):
        seed_site(2)
        body = html_of(self.get_ok('/sitemap.xml'))
        for path in __import__('re').findall(r'<loc>https?://[^/]+(/[^<]*)</loc>', body):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_delete_category_and_edit_author_do_not_crash(self):
        self.login()
        mk_category('del-me')
        self.assertEqual(self.client.post('/category/del-me/delete/').status_code, 200)
        from .helpers import mk_author
        mk_author('ea')
        response = self.client.post('/authors/ea/edit', {'name_ua': 'u', 'name_en': 'e', 'description_ua': 'd',
                                                          'description_en': 'd'})
        self.assertEqual(response.status_code, 302)

    def test_comment_tree_is_built_in_constant_queries(self):
        a = mk_article('ct')
        self.get_ok('/article/ct/')
        small = len(CaptureQueriesContext(connection).__enter__().captured_queries) if False else None
        parent = None
        for i in range(30):
            parent = mk_comment(a, parent=parent if i % 2 else None)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/article/ct/')
        comment_queries = [q for q in ctx.captured_queries if 'app_comment' in q['sql']]
        self.assertLessEqual(len(comment_queries), 2)

    def test_home_page_prefetches_categories(self):
        root = mk_category('hp')
        for i in range(8):
            mk_article(f'hp{i}', cats=[root])
        self.client.get('/')
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertLessEqual(len(ctx), 6)

    def test_recommended_articles_use_the_root_category(self):
        root = mk_category('rr')
        child = mk_category('rc', parent=root)
        mk_article('same-root', cats=[root], views=9)
        mk_article('current', cats=[child])
        self.assertIn('/article/same-root/', html_of(self.get_ok('/article/current/')))

    def test_category_order_change_reflected_in_menu(self):
        self.login()
        a, b = mk_category('a', order=1), mk_category('b', order=2)
        self.get_ok('/')
        import json
        self.client.post('/editor-cabinet/categories/order/update/',
                         data=json.dumps([{'id': str(a.id), 'order': 9}, {'id': str(b.id), 'order': 1}]),
                         content_type='application/json')
        self.in_order(html_of(self.get_ok('/')), '/category/b/', '/category/a/')
