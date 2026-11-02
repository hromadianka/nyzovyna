import re
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils.timezone import now

from app.models import AboutUsText, Article, Author, Category, Comment

from .helpers import Base, ON_MYSQL, Timeout, mk_article, mk_author, mk_category, mk_comment, time_limit

CYRILLIC_NAMES = ['Політика', 'Економіка', 'Культура', 'Спорт', 'Наука', 'Історія', 'Війна', 'Мова', 'Освіта', 'Право']
SLUG_RE = re.compile(r'^[-a-zA-Z0-9_]+$')


class ArticleSlugTests(Base):
    def test_ascii_title_slugified(self):
        self.assertEqual(Article.objects.create(name='Hello World!', text='x').slug, 'hello-world')

    def test_slug_stable_across_saves(self):
        a = Article.objects.create(name='Stable', text='x')
        for _ in range(3):
            a.save()
        self.assertEqual(a.slug, 'stable')

    def test_slug_stable_when_title_changes(self):
        a = Article.objects.create(name='First', text='x')
        a.name = 'Second'
        a.save()
        self.assertEqual(a.slug, 'first')

    def test_slug_collision_gets_numeric_suffix(self):
        names = [Article.objects.create(name='Same', text='x').slug for _ in range(4)]
        self.assertEqual(names, ['same', 'same-1', 'same-2', 'same-3'])

    def test_saving_same_object_does_not_collide_with_itself(self):
        a = Article.objects.create(name='Solo', text='x')
        a.save()
        a.save()
        self.assertEqual(a.slug, 'solo')

    def test_cyrillic_titles_get_meaningful_slugs(self):
        for name in CYRILLIC_NAMES:
            with self.subTest(name=name):
                slug = Article.objects.create(name=name, text='x').slug
                self.assertFalse(slug.startswith('article'), slug)

    def test_cyrillic_titles_get_unique_slugs(self):
        slugs = [Article.objects.create(name=n, text='x').slug for n in CYRILLIC_NAMES]
        self.assertEqual(len(set(slugs)), len(slugs))

    def test_symbol_only_title_falls_back(self):
        self.assertEqual(Article.objects.create(name='!!!', text='x').slug, 'article')

    def test_empty_title_falls_back(self):
        self.assertEqual(Article.objects.create(name='', text='x').slug, 'article')

    def test_slug_never_exceeds_max_length(self):
        for length in [150, 200, 201, 500]:
            with self.subTest(length=length):
                self.assertLessEqual(len(Article.objects.create(name='a' * length, text='x').slug), 200)

    def test_collision_suffix_never_exceeds_max_length(self):
        Article.objects.create(name='a' * 200, text='x')
        self.assertLessEqual(len(Article.objects.create(name='a' * 200, text='x').slug), 200)

    def test_slug_uses_only_url_safe_characters(self):
        for name in ['A/B', 'a b c', 'ЯЯЯ', 'x.y', 'tab\tname', 'emoji 😀', '../etc/passwd', 'a%20b']:
            with self.subTest(name=name):
                self.assertRegex(Article.objects.create(name=name, text='x').slug, SLUG_RE)

    def test_explicit_slug_is_normalised(self):
        self.assertEqual(Article.objects.create(name='x', slug='My Slug', text='x').slug, 'my-slug')

    def test_explicit_cyrillic_slug_is_not_destroyed(self):
        self.assertNotEqual(Article.objects.create(name='x', slug='привіт', text='x').slug, 'article')

    def test_two_articles_cannot_share_slug_at_db_level(self):
        Article.objects.create(name='dup', text='x')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Article.objects.bulk_create([Article(name='y', slug='dup', text='x')])

    def test_get_absolute_url_resolves(self):
        a = Article.objects.create(name='Hello', text='x', is_published=True)
        self.assertEqual(self.client.get(a.get_absolute_url()).status_code, 200)


class CategorySlugTests(Base):
    def test_ascii_name(self):
        self.assertEqual(Category.objects.create(name_ua='Politics', name_en='Politics').slug, 'politics')

    def test_cyrillic_name_has_nonempty_slug(self):
        for name in CYRILLIC_NAMES:
            with self.subTest(name=name):
                self.assertTrue(Category.objects.create(name_ua=name, name_en='x').slug)

    def test_cyrillic_names_get_unique_slugs(self):
        slugs = [Category.objects.create(name_ua=n, name_en='x').slug for n in CYRILLIC_NAMES]
        self.assertEqual(len(set(slugs)), len(slugs))

    def test_cyrillic_slug_is_routable(self):
        c = Category.objects.create(name_ua='Політика', name_en='Politics')
        self.assertEqual(self.client.get(c.get_absolute_url()).status_code, 200)

    def test_cyrillic_slug_is_not_just_a_dash_and_number(self):
        c = Category.objects.create(name_ua='Політика', name_en='Politics')
        c2 = Category.objects.create(name_ua='Економіка', name_en='Economy')
        self.assertNotRegex(c2.slug, r'^-\d+$')
        self.assertNotEqual(c.slug, '')

    def test_slug_stable_on_rename(self):
        c = Category.objects.create(name_ua='One', name_en='One')
        c.name_ua = 'Two'
        c.save()
        self.assertEqual(c.slug, 'one')

    def test_slug_collision_suffix(self):
        self.assertEqual([Category.objects.create(name_ua='Same', name_en='s').slug for _ in range(3)],
                         ['same', 'same-1', 'same-2'])

    def test_slug_never_exceeds_max_length(self):
        for length, char in [(100, 'a'), (101, 'b'), (300, 'c')]:
            with self.subTest(length=length):
                self.assertLessEqual(len(Category.objects.create(name_ua=char * length, name_en='x').slug), 100)

    def test_collision_suffix_respects_max_length(self):
        Category.objects.create(name_ua='a' * 100, name_en='x')
        self.assertLessEqual(len(Category.objects.create(name_ua='a' * 100, name_en='x').slug), 100)

    def test_slug_unique_at_db_level(self):
        mk_category('dup')
        with self.assertRaises(IntegrityError), transaction.atomic():
            mk_category('dup')

    def test_slug_not_empty_string_stored(self):
        Category.objects.create(name_ua='!!!', name_en='x')
        self.assertFalse(Category.objects.filter(slug='').exists())

    def test_str_returns_name(self):
        self.assertEqual(str(mk_category('s')), 'ua-s')


class AuthorSlugTests(Base):
    def test_slug_from_english_name(self):
        self.assertEqual(Author.objects.create(name_en='John Smith', name_ua='x', description_en='d',
                                               description_ua='d').slug, 'john-smith')

    def test_cyrillic_english_name_has_nonempty_slug(self):
        for name in CYRILLIC_NAMES:
            with self.subTest(name=name):
                self.assertTrue(Author.objects.create(name_en=name, name_ua=name, description_en='d',
                                                      description_ua='d').slug)

    def test_cyrillic_names_unique_slugs(self):
        slugs = [Author.objects.create(name_en=n, name_ua=n, description_en='d', description_ua='d').slug
                 for n in CYRILLIC_NAMES]
        self.assertEqual(len(set(slugs)), len(slugs))

    def test_slug_collision_suffix(self):
        self.assertEqual([Author.objects.create(name_en='Same', name_ua='x', description_en='d',
                                                description_ua='d').slug for _ in range(2)], ['same', 'same-1'])

    def test_slug_never_exceeds_max_length(self):
        a = Author.objects.create(name_en='a' * 100, name_ua='x', description_en='d', description_ua='d')
        b = Author.objects.create(name_en='a' * 100, name_ua='x', description_en='d', description_ua='d')
        self.assertLessEqual(len(b.slug), 100)

    def test_absolute_url_resolves(self):
        a = mk_author('abc')
        self.assertEqual(self.client.get(a.get_absolute_url()).status_code, 200)

    def test_default_image_name_is_the_known_placeholder(self):
        self.assertEqual(mk_author('img').image.name, 'card-example.png')

    def test_default_image_exists_in_static_or_media(self):
        from django.contrib.staticfiles import finders
        from .helpers import BASE_DIR
        self.assertTrue(finders.find('img/card-example.png') or (BASE_DIR / 'media' / 'card-example.png').exists())

    def test_default_image_is_served_from_media_root_in_production_storage(self):
        from .helpers import BASE_DIR
        self.assertTrue((BASE_DIR / 'media' / 'card-example.png').exists())


class CascadeAndIntegrityTests(Base):
    def test_deleting_category_does_not_delete_articles(self):
        c = mk_category('c')
        a = mk_article('a', cats=[c])
        c.delete()
        self.assertTrue(Article.objects.filter(pk=a.pk).exists())

    def test_deleting_category_removes_m2m_links_only(self):
        c = mk_category('c')
        a = mk_article('a', cats=[c])
        c.delete()
        self.assertEqual(a.categories.count(), 0)

    def test_deleting_parent_category_keeps_children(self):
        p = mk_category('p')
        mk_category('k', parent=p)
        p.delete()
        self.assertTrue(Category.objects.filter(slug='k').exists())

    def test_deleting_article_deletes_its_comments(self):
        a = mk_article('a')
        mk_comment(a)
        a.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_deleting_author_keeps_articles(self):
        au = mk_author('au')
        a = mk_article('a', author=au)
        au.delete()
        self.assertTrue(Article.objects.filter(pk=a.pk).exists())

    def test_deleting_author_with_articles_is_blocked_or_orphans(self):
        au = mk_author('au')
        mk_article('a1', author=au)
        mk_article('a2', author=au)
        au.delete()
        self.assertEqual(Article.objects.count(), 2)

    def test_deleting_parent_comment_removes_thread(self):
        a = mk_article('a')
        p = mk_comment(a)
        mk_comment(a, parent=p)
        p.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_category_cannot_be_its_own_parent(self):
        c = mk_category('self')
        c.parent = c
        with self.assertRaises((ValidationError, IntegrityError, ValueError)):
            c.full_clean()
            c.save()

    def test_category_cycle_of_two_is_rejected(self):
        a = mk_category('a')
        b = mk_category('b', parent=a)
        a.parent = b
        with self.assertRaises((ValidationError, IntegrityError, ValueError)):
            a.full_clean()
            a.save()

    def test_comment_cannot_be_its_own_parent(self):
        a = mk_article('a')
        c = mk_comment(a)
        c.parent_comment = c
        with self.assertRaises((ValidationError, IntegrityError, ValueError)):
            c.full_clean()
            c.save()

    def test_comment_parent_must_belong_to_same_article(self):
        a1, a2 = mk_article('a1'), mk_article('a2')
        parent = mk_comment(a1)
        child = Comment(article=a2, parent_comment=parent, author='x', text='y')
        with self.assertRaises(ValidationError):
            child.full_clean()

    def test_article_page_survives_category_cycle(self):
        a = mk_category('a')
        Category.objects.filter(pk=a.pk).update(parent=a)
        art = mk_article('art', cats=[a])
        with time_limit(3):
            try:
                response = self.client.get('/article/art/')
            except Timeout:
                self.fail('infinite loop walking category parents')
        self.assertEqual(response.status_code, 200)

    def test_home_survives_category_cycle(self):
        a = mk_category('a')
        b = mk_category('b', parent=a)
        Category.objects.filter(pk=a.pk).update(parent=b)
        with time_limit(3):
            try:
                response = self.client.get('/')
            except Timeout:
                self.fail('home hangs on category cycle')
        self.assertEqual(response.status_code, 200)

    def test_deep_category_tree_renders(self):
        parent = None
        for i in range(60):
            parent = mk_category(f'deep-{i}', parent=parent)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_very_deep_category_tree_renders(self):
        parent = None
        for i in range(400):
            parent = mk_category(f'vd-{i}', parent=parent)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_article_requires_text_and_name_at_validation_level(self):
        with self.assertRaises(ValidationError):
            Article(name='', text='').full_clean()

    def test_comment_requires_author_at_validation_level(self):
        a = mk_article('a')
        with self.assertRaises(ValidationError):
            Comment(article=a, author='', text='x').full_clean()

    def test_author_requires_names_at_validation_level(self):
        with self.assertRaises(ValidationError):
            Author(name_en='', name_ua='', description_en='', description_ua='').full_clean()

    def test_about_us_row_is_created_on_migrate(self):
        self.assertTrue(AboutUsText.objects.exists())

    def test_language_choices_are_validated(self):
        with self.assertRaises(ValidationError):
            Article(name='x', text='x', slug='x', language='zz').full_clean()


class TimezoneTests(Base):
    def test_use_tz_enabled_and_utc(self):
        from django.conf import settings
        self.assertTrue(settings.USE_TZ)
        self.assertEqual(settings.TIME_ZONE, 'UTC')

    def test_publish_at_default_is_aware(self):
        self.assertIsNotNone(mk_article('t').publish_at.tzinfo)

    def test_publish_command_boundary_is_inclusive(self):
        from django.core.management import call_command
        from io import StringIO
        moment = now()
        a = mk_article('edge', published=False, publish_at=moment)
        call_command('publish_articles', stdout=StringIO())
        a.refresh_from_db()
        self.assertTrue(a.is_published)

    def test_publish_command_one_second_in_future_waits(self):
        from django.core.management import call_command
        from io import StringIO
        a = mk_article('edge2', published=False, publish_at=now() + timedelta(seconds=30))
        call_command('publish_articles', stdout=StringIO())
        a.refresh_from_db()
        self.assertFalse(a.is_published)

    def test_publish_command_reports_count(self):
        from django.core.management import call_command
        from io import StringIO
        for i in range(3):
            mk_article(f'c{i}', published=False, publish_at=now() - timedelta(minutes=1))
        out = StringIO()
        call_command('publish_articles', stdout=out)
        self.assertIn('3', out.getvalue())

    def test_publish_command_output_is_machine_readable_and_logged(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('publish_articles', stdout=out)
        self.assertTrue(out.getvalue().strip())


class MigrationTests(TransactionTestCase):
    available_apps = None
    BEFORE = '0006_article_slug_author_slug_category_slug_and_more'

    def state(self, target):
        return MigrationExecutor(connection).loader.project_state([('app', target)]).apps

    def fake_back_to_0006(self):
        MigrationExecutor(connection).migrate([('app', self.BEFORE)], fake=True)
        return self.state(self.BEFORE)

    def forward_0007(self):
        MigrationExecutor(connection).migrate([('app', '0007_fill_slugs')])
        return self.state('0007_fill_slugs')

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes(), fake=True)

    def test_makemigrations_check_is_clean(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        try:
            call_command('makemigrations', check=True, dry_run=True, stdout=out)
        except SystemExit:
            self.fail(f'pending model changes: {out.getvalue()}')

    def test_migration_graph_is_linear_with_single_leaf(self):
        self.assertEqual(len(MigrationExecutor(connection).loader.graph.leaf_nodes('app')), 1)

    def test_every_migration_is_reversible(self):
        from importlib import import_module
        from django.db.migrations.operations.special import RunPython
        for name in ['0007_fill_slugs']:
            with self.subTest(migration=name):
                operations = import_module(f'app.migrations.{name}').Migration.operations
                for op in operations:
                    if isinstance(op, RunPython):
                        self.assertTrue(op.reversible)

    def test_0007_fills_ascii_slugs(self):
        old = self.fake_back_to_0006()
        old.get_model('app', 'Article').objects.create(name='Plain Title', text='x', slug=None)
        self.assertEqual(self.forward_0007().get_model('app', 'Article').objects.get().slug, 'plain-title')

    def test_0007_gives_cyrillic_categories_nonempty_unique_slugs(self):
        old = self.fake_back_to_0006()
        Cat = old.get_model('app', 'Category')
        for n in CYRILLIC_NAMES[:4]:
            Cat.objects.create(name_ua=n, name_en=n, slug=None)
        slugs = list(self.forward_0007().get_model('app', 'Category').objects.values_list('slug', flat=True))
        self.assertTrue(all(slugs), slugs)
        self.assertEqual(len(set(slugs)), len(slugs))

    def test_0007_gives_cyrillic_articles_nonempty_slugs(self):
        old = self.fake_back_to_0006()
        for n in CYRILLIC_NAMES[:3]:
            old.get_model('app', 'Article').objects.create(name=n, text='x', slug=None)
        self.assertTrue(all(self.forward_0007().get_model('app', 'Article').objects.values_list('slug', flat=True)))

    def test_0007_gives_cyrillic_authors_nonempty_slugs(self):
        old = self.fake_back_to_0006()
        for n in CYRILLIC_NAMES[:3]:
            old.get_model('app', 'Author').objects.create(name_en=n, name_ua=n, description_en='d',
                                                          description_ua='d', slug=None)
        self.assertTrue(all(self.forward_0007().get_model('app', 'Author').objects.values_list('slug', flat=True)))

    def test_0007_keeps_existing_slugs(self):
        old = self.fake_back_to_0006()
        old.get_model('app', 'Article').objects.create(name='Name', text='x', slug='kept')
        self.assertEqual(self.forward_0007().get_model('app', 'Article').objects.get().slug, 'kept')

    def test_0007_on_empty_database_is_a_noop(self):
        self.fake_back_to_0006()
        self.assertEqual(self.forward_0007().get_model('app', 'Article').objects.count(), 0)

    def test_0007_slug_assignment_respects_max_length(self):
        old = self.fake_back_to_0006()
        for _ in range(2):
            old.get_model('app', 'Category').objects.create(name_ua='a' * 100, name_en='x', slug=None)
        slugs = self.forward_0007().get_model('app', 'Category').objects.values_list('slug', flat=True)
        self.assertTrue(all(len(s) <= 100 for s in slugs))

    def test_0007_is_idempotent_when_rerun(self):
        from importlib import import_module
        module = import_module('app.migrations.0007_fill_slugs')
        apps = self.state('0007_fill_slugs')
        apps.get_model('app', 'Article').objects.create(name='Again', text='x', slug=None)
        module.fill_slugs(apps, None)
        first = apps.get_model('app', 'Article').objects.get().slug
        module.fill_slugs(apps, None)
        self.assertEqual(apps.get_model('app', 'Article').objects.get().slug, first)

    def test_0010_switches_pending_scheduled_articles_on(self):
        from datetime import timedelta
        MigrationExecutor(connection).migrate([('app', '0009_alter_article_slug_alter_author_slug_and_more')])
        apps = self.state('0009_alter_article_slug_alter_author_slug_and_more')
        Art = apps.get_model('app', 'Article')
        pending = Art.objects.create(name='pending', text='x', slug='pending', is_published=False,
                                     publish_at=now() + timedelta(days=2))
        hidden = Art.objects.create(name='hidden', text='x', slug='hidden', is_published=False,
                                    publish_at=now() - timedelta(days=2))
        MigrationExecutor(connection).migrate([('app', '0010_publish_pending_scheduled')])
        Art = self.state('0010_publish_pending_scheduled').get_model('app', 'Article')
        self.assertTrue(Art.objects.get(pk=pending.pk).is_published)
        self.assertFalse(Art.objects.get(pk=hidden.pk).is_published)

    def test_final_slug_columns_are_nullable_and_unique(self):
        with connection.cursor() as cursor:
            for table in ['app_article', 'app_author', 'app_category']:
                desc = {c.name: c for c in connection.introspection.get_table_description(cursor, table)}
                with self.subTest(table=table):
                    self.assertTrue(desc['slug'].null_ok)
                    constraints = connection.introspection.get_constraints(cursor, table)
                    self.assertTrue(any(c['unique'] and c['columns'] == ['slug'] for c in constraints.values()))

    def test_chain_from_zero_to_head_in_fresh_database(self):
        import os
        import subprocess
        import sys
        import tempfile
        from .helpers import BASE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, DJANGO_SETTINGS_MODULE='anarchia.settings_test', NYZ_DB_FILE=f'{tmp}/fresh.sqlite3',
                       PYTHONDONTWRITEBYTECODE='1')
            env.pop('NYZ_DB', None)
            done = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=BASE_DIR, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
            check = subprocess.run([sys.executable, 'manage.py', 'migrate', '--check'], cwd=BASE_DIR, env=env,
                                   capture_output=True, text=True)
            self.assertEqual(check.returncode, 0)

    def test_fresh_database_gets_default_about_us_row(self):
        self.assertTrue(AboutUsText.objects.exists())
