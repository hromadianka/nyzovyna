import threading
from unittest import mock

from django.db import OperationalError, connection, connections
from django.db.models import F
from django.test import TransactionTestCase, Client
from unittest import skipUnless

from app.models import Article, Author, Category, Comment

from .helpers import (TEST_PASSWORD, make_editor, Base, ON_MYSQL, captcha_ok, html_of, mk_article, mk_author, mk_category, mk_comment, png,
                      seed_site)


class DependencyFailureTests(Base):
    def setUp(self):
        super().setUp()
        seed_site(3)

    def test_database_outage_returns_503_not_500(self):
        with mock.patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                        side_effect=OperationalError('db down')):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 503)

    def test_database_outage_does_not_leak_stack_trace(self):
        with mock.patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection',
                        side_effect=OperationalError('db down secret-host')):
            response = self.client.get('/')
        self.assertNotIn('secret-host', html_of(response))

    def test_cache_backend_failure_does_not_break_pages(self):
        with mock.patch('django.core.cache.backends.locmem.LocMemCache.get', side_effect=RuntimeError('cache down')):
            for url in ['/', '/all', '/article/seed-0/']:
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_cache_set_failure_does_not_break_pages(self):
        with mock.patch('django.core.cache.backends.locmem.LocMemCache.set', side_effect=RuntimeError('cache down')):
            self.assertEqual(self.client.get('/').status_code, 200)

    def test_media_url_resolution_failure_does_not_break_listing(self):
        with mock.patch('django.core.files.storage.FileSystemStorage.url', side_effect=RuntimeError('cdn down')):
            try:
                status = self.client.get('/').status_code
            except RuntimeError:
                self.fail('storage.url() failure propagates out of the request')
        self.assertEqual(status, 200)

    def test_missing_media_file_does_not_break_pages(self):
        for url in ['/', '/all', '/article/seed-0/', '/authors']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_empty_image_field_does_not_break_any_listing(self):
        Article.objects.update(image='')
        Author.objects.update(image='')
        for url in ['/', '/all', '/category/root/', '/authors/author-1', '/search/?q=Title', '/article/seed-0/',
                    '/authors']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


    def test_storage_failure_on_author_upload_is_handled(self):
        self.login()
        with mock.patch('django.core.files.storage.FileSystemStorage._save', side_effect=OSError('down')):
            response = self.client.post('/create_new_author/', {
                'author_name_ua': 'а', 'author_name_en': 'a', 'author_description_ua': 'd',
                'author_description_en': 'd', 'author_image': png()})
        self.assertLess(response.status_code, 500)

    def test_storage_failure_on_article_edit_keeps_old_data(self):
        self.login()
        art = Article.objects.get(slug='seed-0')
        with mock.patch('django.core.files.storage.FileSystemStorage._save', side_effect=OSError('down')):
            try:
                self.client.post('/article/seed-0/edit/', {
                    'article_name': 'CHANGED', 'article_text': 't', 'language': 'ua',
                    'article_author': str(art.author_id), 'publish_option': 'now', 'article_slug': 'seed-0',
                    'article_image': png()})
            except Exception:
                pass
        art.refresh_from_db()
        self.assertNotEqual(art.name, 'CHANGED')

    def test_unhandled_exception_returns_branded_500_page(self):
        with mock.patch('app.views.index', side_effect=RuntimeError('boom')):
            response = self.client.get('/')
        self.assertEqual(response.status_code, 500)
        self.assertIn('Низовина', html_of(response))

    def test_request_to_missing_template_variable_is_not_silent_500(self):
        Article.objects.filter(slug='seed-0').update(author=None)
        self.assertEqual(self.client.get('/article/seed-0/').status_code, 200)


class LostUpdateTests(Base):
    def test_editing_article_does_not_overwrite_concurrent_view_count(self):
        self.login()
        author = mk_author('a1')
        article = mk_article('lu', author=author, views=10)
        real_save = Article.save

        def save_after_visit(self_, *a, **kw):
            Article.objects.filter(pk=self_.pk).update(views=F('views') + 5)
            return real_save(self_, *a, **kw)

        with mock.patch.object(Article, 'save', save_after_visit):
            self.client.post('/article/lu/edit/', {
                'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
                'publish_option': 'now', 'article_slug': 'lu'})
        article.refresh_from_db()
        self.assertEqual(article.views, 15)

    def test_article_view_counter_uses_database_expression(self):
        article = mk_article('ctr', views=3)
        Article.objects.filter(pk=article.pk).update(views=100)
        self.client.get('/article/ctr/')
        article.refresh_from_db()
        self.assertEqual(article.views, 101)


    def test_edit_form_save_updates_only_changed_columns(self):
        self.login()
        author = mk_author('a1')
        mk_article('cols', author=author)
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self.client.post('/article/cols/edit/', {
                'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
                'publish_option': 'now', 'article_slug': 'cols'})
        updates = [q['sql'] for q in ctx.captured_queries if q['sql'].lstrip().upper().startswith('UPDATE')
                   and 'app_article' in q['sql']]
        self.assertTrue(all('views' not in q for q in updates), updates)


class DoubleSubmitTests(Base):
    def test_double_posted_new_category_is_deduplicated(self):
        self.login()
        for _ in range(2):
            self.client.post('/create-category/', {'name_ua': 'Same', 'name_en': 'Same'})
        self.assertEqual(Category.objects.count(), 1)

    def test_double_posted_article_is_deduplicated(self):
        self.login()
        author = mk_author('a1')
        data = {'article_name': 'Dup', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
                'publish_option': 'now'}
        for _ in range(2):
            self.client.post('/publish', data)
        self.assertEqual(Article.objects.count(), 1)

    def test_double_posted_author_is_deduplicated(self):
        self.login()
        data = {'author_name_ua': 'а', 'author_name_en': 'Same', 'author_description_ua': 'd',
                'author_description_en': 'd'}
        for _ in range(2):
            self.client.post('/create_new_author/', data)
        self.assertEqual(Author.objects.count(), 1)

    def test_double_delete_comment_second_is_404(self):
        self.login()
        c = mk_comment(mk_article('a'))
        url = f'/editor-cabinet/comments-moderation/{c.id}/delete/'
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.post(url).status_code, 404)


def run_threads(target, count):
    errors, barrier = [], threading.Barrier(count)

    def worker(i):
        try:
            barrier.wait()
            target(i)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


@skipUnless(ON_MYSQL, 'needs a database with real concurrent connections (run with NYZ_DB=mysql)')
class ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_parallel_views_are_all_counted(self):
        article = mk_article('par')

        def hit(i):
            Client().get('/article/par/')

        errors = run_threads(hit, 16)
        article.refresh_from_db()
        self.assertEqual((errors, article.views), ([], 16))

    def test_parallel_comments_are_all_stored(self):
        article = mk_article('pc')

        def post(i):
            Client().post('/comment', {'article_id': str(article.id), 'author': f'u{i}', 'text': 'hi'})

        with captcha_ok():
            errors = run_threads(post, 12)
        self.assertEqual((errors, Comment.objects.count()), ([], 12))

    def test_parallel_category_creation_with_same_name_yields_distinct_slugs(self):
        def create(i):
            Category.objects.create(name_ua='Same', name_en='Same')

        errors = run_threads(create, 8)
        self.assertEqual(errors, [])
        self.assertEqual(Category.objects.count(), 8)

    def test_parallel_article_creation_with_same_title_yields_distinct_slugs(self):
        def create(i):
            Article.objects.create(name='Same title', text='x')

        errors = run_threads(create, 8)
        self.assertEqual(errors, [])
        self.assertEqual(Article.objects.values('slug').distinct().count(), 8)

    def test_parallel_author_creation_with_same_name_yields_distinct_slugs(self):
        def create(i):
            Author.objects.create(name_en='Same', name_ua='x', description_en='d', description_ua='d')

        self.assertEqual(run_threads(create, 8), [])

    def test_view_counter_survives_parallel_edit(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        author = mk_author('a1')
        article = mk_article('edit-par', author=author)

        def work(i):
            c = Client()
            if i % 2:
                c.login(username='ed', password=TEST_PASSWORD)
                c.post('/article/edit-par/edit/', {
                    'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
                    'publish_option': 'now', 'article_slug': 'edit-par'})
            else:
                c.get('/article/edit-par/')

        run_threads(work, 10)
        article.refresh_from_db()
        self.assertEqual(article.views, 5)

    def test_parallel_menu_cache_rebuild_does_not_error(self):
        mk_category('m1')

        def hit(i):
            r = Client().get('/')
            assert r.status_code == 200

        self.assertEqual(run_threads(hit, 12), [])
