from datetime import timedelta

from django.utils.timezone import now

from app.models import AboutUsText, Article, Category

from .helpers import (Base, html_of, mk_article, mk_author, mk_category, mk_comment, seed_site)

CEILING = {'/': 8, '/all': 6, '/category/root/': 6, '/authors': 6, '/authors/author-1': 6, '/article/seed-0/': 12,
           '/search/?q=Title': 6, '/about-us': 6, '/feed/': 5, '/sitemap.xml': 10, '/login/': 4}


def grow(n):
    root = mk_category('root', order=1)
    child = mk_category('child', parent=root)
    other = mk_category('other', order=2)
    author = mk_author()
    AboutUsText.objects.get_or_create(pk=1, defaults={'text_ua': 'a', 'text_en': 'b'})
    for i in range(n):
        art = mk_article(f'seed-{i}', cats=[root, child, other], author=author, views=i,
                         publish_at=now() - timedelta(minutes=i))
        if i < 5:
            parent = mk_comment(art)
            mk_comment(art, parent=parent)
    return root


class QueryBudgetTests(Base):
    def count(self, url):
        self.client.get(url)
        _, queries = self.queries(url)
        return queries

    def test_budget_is_respected_on_small_data(self):
        grow(3)
        for url, ceiling in CEILING.items():
            with self.subTest(url=url):
                self.assertLessEqual(self.count(url), ceiling)

    def test_budget_is_respected_on_large_data(self):
        grow(60)
        for url, ceiling in CEILING.items():
            with self.subTest(url=url):
                self.assertLessEqual(self.count(url), ceiling)

    def test_query_count_does_not_grow_with_article_count(self):
        grow(3)
        small = {url: self.count(url) for url in CEILING}
        for i in range(3, 80):
            mk_article(f'extra-{i}', cats=list(Category.objects.all()[:3]), author=None)
        for url, before in small.items():
            with self.subTest(url=url):
                self.assertEqual(self.count(url), before)

    def test_query_count_does_not_grow_with_category_count(self):
        grow(3)
        small = {url: self.count(url) for url in ['/', '/all', '/article/seed-0/', '/authors']}
        root = Category.objects.get(slug='root')
        for i in range(60):
            mk_category(f'more-{i}', parent=root if i % 2 else None)
        from django.core.cache import cache
        cache.clear()
        for url, before in small.items():
            with self.subTest(url=url):
                self.assertLessEqual(self.count(url), before + 1)

    def test_query_count_does_not_grow_with_comment_count(self):
        grow(3)
        art = Article.objects.get(slug='seed-0')
        before = self.count('/article/seed-0/')
        parent = None
        for i in range(60):
            parent = mk_comment(art, parent=parent if i % 3 else None)
        self.assertEqual(self.count('/article/seed-0/'), before)

    def test_query_count_does_not_grow_with_author_count(self):
        grow(3)
        before = self.count('/authors')
        for i in range(40):
            mk_author(f'bulk-{i}')
        self.assertEqual(self.count('/authors'), before)

    def test_editor_pages_do_not_grow_with_data(self):
        self.login()
        grow(3)
        urls = ['/editor-cabinet', '/editor-cabinet/comments-moderation/', '/editor-cabinet/categories/order/',
                '/article/seed-0/edit/', '/authors/author-1/edit', '/publish']
        small = {u: self.count(u) for u in urls}
        grow_more = Category.objects.get(slug='root')
        for i in range(40):
            art = mk_article(f'e-{i}', cats=[grow_more], author=None)
            mk_comment(art)
            mk_category(f'ec-{i}', parent=grow_more)
        for url, before in small.items():
            with self.subTest(url=url):
                self.assertEqual(self.count(url), before)

    def test_editor_pages_have_a_ceiling(self):
        self.login()
        grow(30)
        for url in ['/editor-cabinet', '/editor-cabinet/comments-moderation/', '/editor-cabinet/categories/order/',
                    '/article/seed-0/edit/', '/publish']:
            with self.subTest(url=url):
                self.assertLessEqual(self.count(url), 15)

    def test_article_view_write_queries_are_minimal(self):
        grow(2)
        _, total = self.queries('/article/seed-0/')
        self.assertLessEqual(total, 12)

    def test_cached_menu_hit_has_no_category_queries(self):
        grow(3)
        self.client.get('/')
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertEqual([q['sql'] for q in ctx.captured_queries if 'app_category' in q['sql'] and 'app_article_categories' not in q['sql']], [])


class PayloadSizeTests(Base):
    def test_listing_html_size_is_bounded_with_many_articles(self):
        grow(5)
        for i in range(400):
            mk_article(f'bulk-{i}', text='<p>' + 'lorem ipsum ' * 300 + '</p>')
        for url in ['/all', '/category/root/', '/search/?q=bulk', '/authors/author-1', '/']:
            with self.subTest(url=url):
                self.assertLess(len(self.client.get(url).content), 300_000)

    def test_article_html_does_not_scale_with_unrelated_articles(self):
        grow(3)
        before = len(self.client.get('/article/seed-0/').content)
        for i in range(200):
            mk_article(f'unrel-{i}', text='<p>' + 'x' * 3000 + '</p>')
        after = len(self.client.get('/article/seed-0/').content)
        self.assertLess(after, before * 2)

    def test_comments_page_html_is_bounded_with_many_comments(self):
        grow(2)
        art = Article.objects.get(slug='seed-0')
        for i in range(500):
            mk_comment(art, text='c' * 200)
        self.assertLess(len(self.client.get('/article/seed-0/').content), 400_000)

    def test_listing_pages_have_pagination_controls(self):
        grow(5)
        for i in range(60):
            mk_article(f'pg-{i}', cats=[Category.objects.get(slug='root')])
        for url in ['/all', '/category/root/']:
            with self.subTest(url=url):
                self.assertRegex(html_of(self.client.get(url)).lower(), r'page=|pagination|next')

    def test_listing_pages_render_a_bounded_number_of_cards(self):
        grow(5)
        for i in range(120):
            mk_article(f'cards-{i}', cats=[Category.objects.get(slug='root')])
        for url in ['/all', '/category/root/']:
            with self.subTest(url=url):
                self.assertLessEqual(html_of(self.client.get(url)).count('class="article-card"'), 60)

    def test_search_uses_a_limit(self):
        grow(5)
        for i in range(150):
            mk_article(f'lim-{i}', name='shared token')
        self.assertLessEqual(html_of(self.client.get('/search/?q=shared')).count('class="article-card"'), 60)

    def test_authors_page_is_bounded(self):
        for i in range(150):
            mk_author(f'a-{i}')
        self.assertLess(len(self.client.get('/authors').content), 120_000)
