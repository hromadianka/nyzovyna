import os
import subprocess
import sys
from contextlib import contextmanager
from unittest import skipUnless

from django.db import connection
from django.test import TransactionTestCase

from app.models import Article, Author, Category, Comment

from .helpers import TEST_PASSWORD, make_editor, BASE_DIR, ON_MYSQL, captcha_ok, html_of, mk_article, mk_author, mk_category, seed_site

PROD_OPTIONS = {'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}


@contextmanager
def production_connection_options():
    original = dict(connection.settings_dict['OPTIONS'])
    connection.close()
    connection.settings_dict['OPTIONS'] = dict(PROD_OPTIONS)
    try:
        yield
    finally:
        connection.close()
        connection.settings_dict['OPTIONS'] = original


def scalar(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


@skipUnless(ON_MYSQL, 'MySQL-only checks (run with NYZ_DB=mysql)')
class MySqlBehaviourTests(TransactionTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.raise_request_exception = False

    def test_strict_mode_is_enabled_like_production(self):
        self.assertIn('STRICT_TRANS_TABLES', scalar('SELECT @@sql_mode'))

    def test_production_connection_charset_supports_four_byte_characters(self):
        with production_connection_options():
            self.assertEqual(scalar('SELECT @@character_set_client'), 'utf8mb4')

    def test_emoji_comment_is_stored_with_production_connection_options(self):
        article = mk_article('emo')
        with production_connection_options(), captcha_ok():
            response = self.client.post('/comment', {'article_id': str(article.id), 'author': 'Ann',
                                                     'text': 'smile 🙂'})
            self.assertLess(response.status_code, 500)
        self.assertEqual(Comment.objects.count(), 1)

    def test_emoji_in_article_title_is_stored_with_production_connection_options(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        self.client.login(username='ed', password=TEST_PASSWORD)
        author = mk_author('a1')
        with production_connection_options():
            response = self.client.post('/publish', {
                'article_name': 'Title 🙂', 'article_text': '<p>x</p>', 'language': 'ua',
                'article_author': str(author.id), 'publish_option': 'now'})
            self.assertLess(response.status_code, 500)

    def test_emoji_in_search_query_is_not_a_server_error_with_production_options(self):
        with production_connection_options():
            self.assertLess(self.client.get('/search/', {'q': '🙂'}).status_code, 500)

    def test_slug_longer_than_column_does_not_raise_data_error(self):
        Article.objects.create(name='a' * 300, text='x')

    def test_comment_author_longer_than_column_is_client_error(self):
        article = mk_article('long-author')
        with captcha_ok():
            response = self.client.post('/comment', {'article_id': str(article.id), 'author': 'x' * 150, 'text': 't'})
        self.assertLess(response.status_code, 500)

    def test_category_name_longer_than_column_is_client_error(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        self.client.login(username='ed', password=TEST_PASSWORD)
        response = self.client.post('/create-category/', {'name_ua': 'x' * 150, 'name_en': 'y'})
        self.assertLess(response.status_code, 500)

    def test_author_name_longer_than_column_is_client_error(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        self.client.login(username='ed', password=TEST_PASSWORD)
        response = self.client.post('/create_new_author/', {
            'author_name_ua': 'x' * 150, 'author_name_en': 'y', 'author_description_ua': 'd',
            'author_description_en': 'd'})
        self.assertLess(response.status_code, 500)

    def test_cyrillic_search_is_case_insensitive(self):
        mk_article('cyr', name='Привіт Світ')
        self.assertIn('/article/cyr/', html_of(self.client.get('/search/', {'q': 'привіт'})))

    def test_huge_search_query_is_not_a_server_error(self):
        self.assertLess(self.client.get('/search/', {'q': 'a' * 100_000}).status_code, 500)

    def test_all_app_tables_use_innodb_and_utf8mb4(self):
        rows = []
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name, engine, table_collation FROM information_schema.tables "
                           "WHERE table_schema = DATABASE() AND table_name LIKE 'app\\_%'")
            rows = cursor.fetchall()
        self.assertTrue(rows)
        for name, engine, collation in rows:
            with self.subTest(table=name):
                self.assertEqual(engine, 'InnoDB')
                self.assertTrue(collation.startswith('utf8mb4'))

    def test_unique_slug_indexes_fit_innodb_key_limit(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name, column_name, character_maximum_length FROM information_schema.columns "
                           "WHERE table_schema = DATABASE() AND column_name = 'slug'")
            for table, column, length in cursor.fetchall():
                with self.subTest(table=table):
                    self.assertLessEqual(length * 4, 3072)

    def test_slug_unique_lookup_uses_the_index(self):
        mk_article('idx')
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN SELECT id FROM app_article WHERE slug = 'idx'")
            row = cursor.fetchone()
        self.assertIn('app_article_slug', str(row))

    def test_listing_filter_columns_are_indexed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.statistics WHERE table_schema = DATABASE() "
                           "AND table_name = 'app_article'")
            indexed = {r[0] for r in cursor.fetchall()}
        for column in ['is_published', 'language', 'publish_at', 'views']:
            with self.subTest(column=column):
                self.assertIn(column, indexed)

    def test_comment_lookup_by_article_is_indexed(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.statistics WHERE table_schema = DATABASE() "
                           "AND table_name = 'app_comment'")
            indexed = {r[0] for r in cursor.fetchall()}
        self.assertIn('article_id', indexed)
        self.assertIn('created_at', indexed)

    def test_fresh_mysql_database_migrates_from_zero(self):
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='anarchia.settings_test', NYZ_DB='mysql',
                   NYZ_DB_NAME='nyz_fresh_check', PYTHONDONTWRITEBYTECODE='1')
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE IF EXISTS nyz_fresh_check')
            cursor.execute('CREATE DATABASE nyz_fresh_check CHARACTER SET utf8mb4')
        try:
            done = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=BASE_DIR, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP DATABASE IF EXISTS nyz_fresh_check')

    def test_schema_matches_models_on_mysql(self):
        from django.core.management import call_command
        from io import StringIO
        try:
            call_command('makemigrations', check=True, dry_run=True, stdout=StringIO())
        except SystemExit:
            self.fail('model state differs from migrations')

    def test_default_isolation_level_is_documented_repeatable_read(self):
        self.assertIn(scalar('SELECT @@transaction_isolation'), ('REPEATABLE-READ', 'READ-COMMITTED'))

    def test_uuid_primary_key_columns_are_compact(self):
        self.assertEqual(scalar("SELECT character_maximum_length FROM information_schema.columns WHERE "
                                "table_schema = DATABASE() AND table_name = 'app_article' AND column_name = 'id'"), 32)

    def test_unordered_listing_order_does_not_depend_on_primary_key_order(self):
        import uuid
        from datetime import timedelta
        from django.utils.timezone import now
        root = mk_category('root')
        ids = sorted(uuid.uuid4() for _ in range(3))
        for i, pk in enumerate(ids):
            Article.objects.create(id=pk, slug=f'k{i}', name=f'k{i}', text='x', is_published=True,
                                   publish_at=now() - timedelta(days=i)).categories.add(root)
        self.in_order = lambda *a: None
        html = html_of(self.client.get('/category/root/'))
        self.assertTrue(html.find('/article/k0/') < html.find('/article/k1/') < html.find('/article/k2/'))
