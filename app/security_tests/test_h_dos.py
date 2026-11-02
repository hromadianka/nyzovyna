"""H. Resource exhaustion: recursion, query counts, bulk JSON, search cost, cache keys."""
import json
import signal
import time

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from app.models import Article, Author, Category, Comment

from .base import SecBase, add_cases


class Deadline:
    """Turns an infinite loop in a view into a failing request instead of a hung test run."""

    def __init__(self, seconds):
        self.seconds = seconds

    def _raise(self, *_):
        raise TimeoutError(f'no response after {self.seconds}s')

    def __enter__(self):
        self.old = signal.signal(signal.SIGALRM, self._raise)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        self.started = time.monotonic()
        return self

    def __exit__(self, *exc):
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self.old)
        self.elapsed = time.monotonic() - self.started
        return False


class DeepStructures(SecBase):
    def chain_of_categories(self, depth):
        parent = None
        for i in range(depth):
            parent = Category.objects.create(name_ua=f'd{i}', name_en=f'd{i}', slug=f'deep-{i}', parent=parent)
        return parent

    def chain_of_comments(self, depth):
        parent = None
        for i in range(depth):
            parent = Comment.objects.create(article=self.article, author='a', text=f'c{i}', parent_comment=parent)


@add_cases(DeepStructures, 'category_tree_depth_does_not_break_pages', {f'depth_{d}': d for d in (10, 40, 100, 300)})
def _category_depth(self, depth):
    self.chain_of_categories(depth)
    for url in ('/', '/article/public/'):
        response = self.make_client().get(url)
        self.assertEqual(response.status_code, 200, f'{url} -> {response.status_code} with a {depth}-level category chain (recursive template include in the site-wide menu)')


@add_cases(DeepStructures, 'comment_thread_depth_does_not_break_article', {f'depth_{d}': d for d in (10, 40, 100, 300)})
def _comment_depth(self, depth):
    self.chain_of_comments(depth)
    response = self.make_client().get('/article/public/')
    self.assertEqual(response.status_code, 200, f'article page -> {response.status_code} with a {depth}-deep reply thread (recursive comment.html include)')


class AnonymousCanBreakArticlePage(SecBase):
    def test_reply_chain_posted_by_anonymous_visitor_does_not_take_the_page_down(self):
        client = self.make_client()
        parent = self.comment.id
        for i in range(160):
            client.post(self.url('comment_reply'), {'article_id': str(self.article.id), 'author': 'bot', 'text': f'r{i}', 'parent_comment_id': str(parent)})
            parent = Comment.objects.latest('created_at').id
        response = client.get('/article/public/')
        self.assertEqual(response.status_code, 200, f'160 anonymous, captcha-free replies make the article page return {response.status_code}')


class Cycles(SecBase):
    def make_cycle(self):
        loop = Category.objects.create(name_ua='loop', name_en='loop', slug='loop')
        Category.objects.filter(pk=loop.pk).update(parent=loop)
        article = self.make_article('looped', 'Looped', 'body')
        article.categories.set([loop])
        return Category.objects.get(pk=loop.pk), article

    def test_model_rejects_category_as_its_own_ancestor(self):
        from django.core.exceptions import ValidationError
        loop = Category.objects.create(name_ua='loop', name_en='loop', slug='loop')
        loop.parent = loop
        with self.assertRaises(ValidationError, msg='Category(parent=self).full_clean() passes: admin can create a cycle'):
            loop.full_clean()

    def test_article_page_survives_category_cycle(self):
        _, article = self.make_cycle()
        with Deadline(3) as deadline:
            response = self.make_client().get(f'/article/{article.slug}/')
        self.assertEqual(response.status_code, 200, f'article_detail loops forever on a category cycle (stopped after {deadline.elapsed:.1f}s, HTTP {response.status_code})')

    def test_publish_survives_category_cycle(self):
        loop, _ = self.make_cycle()
        data = {**self.data('publish'), 'categories': [str(loop.id)]}
        with Deadline(3) as deadline:
            response = self.make_client(self.editor_user).post(self.url('publish'), data)
        self.assertEqual(response.status_code, 302, f'publish loops forever on a category cycle (stopped after {deadline.elapsed:.1f}s)')


PAGES = {
    'index': ('/', 14), 'all_articles': ('/all', 10), 'category': ('/category/root/', 10), 'author': ('/authors/author', 10),
    'authors': ('/authors', 10), 'search': ('/search/?q=Article', 10), 'article': ('/article/public/', 14),
    'feed': ('/feed/', 8), 'sitemap': ('/sitemap.xml', 8),
}
EDITOR_PAGES = {
    'editor_cabinet': ('/editor-cabinet', 16), 'comments_moderation': ('/editor-cabinet/comments-moderation/', 10),
    'category_order': ('/editor-cabinet/categories/order/', 10),
}


class QueryBudget(SecBase):
    def setUp(self):
        super().setUp()
        for i in range(40):
            article = self.make_article(f'bulk-{i}', f'Article {i}', f'Article text {i}', views=i)
            Comment.objects.create(article=article, author='a', text='c')
        for i in range(40):
            Comment.objects.create(article=self.article, author='a', text=f'c{i}', parent_comment=self.comment)
        for i in range(20):
            Author.objects.create(name_ua=f'a{i}', name_en=f'a{i}', description_ua='d', description_en='d', slug=f'a{i}')

    def count_queries(self, client, url):
        cache.clear()
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(url)
        return response, len(ctx)


@add_cases(QueryBudget, 'public_page_query_count_is_bounded', PAGES)
def _public_budget(self, spec):
    url, limit = spec
    response, queries = self.count_queries(self.make_client(), url)
    self.assertEqual(response.status_code, 200)
    self.assertLessEqual(queries, limit, f'{url}: {queries} queries (limit {limit}) with 40 articles/80 comments: N+1 amplifies every request')


@add_cases(QueryBudget, 'editor_page_query_count_is_bounded', EDITOR_PAGES)
def _editor_budget(self, spec):
    url, limit = spec
    response, queries = self.count_queries(self.make_client(self.editor_user), url)
    self.assertEqual(response.status_code, 200)
    self.assertLessEqual(queries, limit, f'{url}: {queries} queries (limit {limit})')


class BulkAndSearch(SecBase):
    def test_category_order_update_is_batched(self):
        for i in range(300):
            Category.objects.create(name_ua=f'c{i}', name_en=f'c{i}', slug=f'bulk-{i}')
        items = [{'id': str(c.id), 'order': n} for n, c in enumerate(Category.objects.all())]
        with CaptureQueriesContext(connection) as ctx:
            response = self.post_json(self.make_client(self.editor_user), self.url('update_category_order'), items)
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(ctx), 20, f'{len(ctx)} queries for one reorder request: one UPDATE per item, the list length is unbounded')

    def test_category_order_payload_item_count_is_capped(self):
        items = [{'id': '00000000-0000-0000-0000-000000000000', 'order': 1}] * 50_000
        response = self.post_json(self.make_client(self.editor_user), self.url('update_category_order'), items)
        self.assertGreaterEqual(response.status_code, 400, 'a 50 000-item array (about 2 MB) is processed as 50 000 queries')

    def test_deeply_nested_json_is_a_client_error(self):
        response = self.post_json(self.make_client(self.editor_user), self.url('update_category_order'), '[' * 200_000)
        self.assertLess(response.status_code, 500, 'json.loads recursion error is not handled')

    def test_oversized_json_body_is_refused(self):
        response = self.post_json(self.make_client(self.editor_user), self.url('update_category_order'), '[' + '1,' * 1_500_000 + '1]')
        self.assertEqual(response.status_code, 400)

    def test_search_query_length_is_capped(self):
        response = self.make_client().get('/search/', {'q': 'a' * 4000})
        self.assertLessEqual(len(response.context['query']), 200, 'a 4000-character q is used verbatim in an unindexed LIKE over the whole article text')

    def test_search_is_throttled(self):
        client = self.make_client()
        statuses = [client.get('/search/', {'q': f'term{i}'}).status_code for i in range(120)]
        self.assertTrue(any(s == 429 for s in statuses), 'unthrottled full-table LIKE scans: 120 searches in a row, all served')

    def test_like_wildcards_are_escaped(self):
        response = self.make_client().get('/search/', {'q': '%'})
        self.assertEqual(len(response.context['results']), 0, '% must be treated literally')

    def test_search_is_not_regex_based(self):
        response = self.make_client().get('/search/', {'q': '(a+)+$' + 'a' * 5000 + '!'})
        self.assertEqual(response.status_code, 200)


class CacheBehaviour(SecBase):
    def menu_keys(self):
        return [k for k in cache._cache if 'site_menu' in k]

    def test_cache_cardinality_is_bounded_by_language_count(self):
        client = self.make_client()
        for i in range(40):
            client.cookies['django_language'] = f'xx{i}'
            client.get(f'/?cachebust={i}', HTTP_ACCEPT_LANGUAGE=f'q{i}')
        self.assertLessEqual(len(self.menu_keys()), 2, f'{len(self.menu_keys())} cache entries created by request variations (cache poisoning / memory growth)')

    def test_languages_do_not_leak_into_each_other(self):
        Category.objects.filter(pk=self.root_cat.pk).update(name_ua='UAONLYNAME', name_en='ENONLYNAME')
        cache.clear()
        ua = self.make_client()
        ua.get('/')
        en = self.make_client()
        en.cookies['django_language'] = 'en'
        html = body_text_of(en.get('/'))
        self.assertIn('ENONLYNAME', html)
        self.assertNotIn('UAONLYNAME', html)

    def test_menu_is_refreshed_after_category_change(self):
        self.make_client().get('/')
        self.root_cat.name_ua = 'RENAMEDROOT'
        self.root_cat.save()
        self.assertIn('RENAMEDROOT', body_text_of(self.make_client().get('/')))

    def test_menu_is_refreshed_after_bulk_reorder(self):
        self.make_client().get('/')
        other = Category.objects.create(name_ua='Second', name_en='Second', slug='second', order=5)
        self.post_json(self.make_client(self.editor_user), self.url('update_category_order'),
                       [{'id': str(other.id), 'order': -1}, {'id': str(self.root_cat.id), 'order': 3}])
        html = body_text_of(self.make_client().get('/'))
        self.assertLess(html.index('Second'), html.index('Root'))


def body_text_of(response):
    return response.content.decode('utf-8', 'replace')
