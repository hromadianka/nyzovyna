"""
Evidence tests for the performance / correctness findings.

Every test states the *desired* behaviour. A failing test = the finding is real.
Run:  DJANGO_SETTINGS_MODULE=anarchia.settings_test python manage.py test app.test_findings -v 2
"""
import re
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.db.models import F
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import Article, Author, Category, Comment, AboutUsText, Editor


def make_tree(roots=3, children=3, grandchildren=2):
    """roots*(1 + children*(1 + grandchildren)) categories."""
    n = 0
    all_cats = []
    for r in range(roots):
        root = Category.objects.create(name_ua=f'r{r}', name_en=f'r{r}', slug=f'r{r}', order=r)
        all_cats.append(root)
        for c in range(children):
            child = Category.objects.create(name_ua=f'c{r}{c}', name_en=f'c{r}{c}', slug=f'c{r}{c}', parent=root)
            all_cats.append(child)
            for g in range(grandchildren):
                n += 1
                all_cats.append(Category.objects.create(
                    name_ua=f'g{r}{c}{g}', name_en=f'g{r}{c}{g}', slug=f'g{r}{c}{g}', parent=child))
    return all_cats


def make_articles(count, cats, author=None, language='ua'):
    arts = []
    for i in range(count):
        a = Article.objects.create(
            name=f'Article {i}', slug=f'article-{i}', text='body', author=author,
            language=language, is_published=True, views=i)
        a.categories.add(*cats[:3])
        arts.append(a)
    return arts


def make_editor():
    user = User.objects.create_user('ed', password='x')
    Editor.objects.create(user=user)
    return user


def table_queries(ctx, table):
    pattern = re.compile(r'["`]%s["`]' % table)
    return [q['sql'] for q in ctx.captured_queries if pattern.search(q['sql'])]


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client.raise_request_exception = False


# --------------------------------------------------------------------------- #
# Finding 0 / 1: base.html menu + footer
# --------------------------------------------------------------------------- #
class MenuQueryTests(Base):
    def render_home(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        return ctx

    def test_original_fix_works_cache_hit_has_zero_category_queries(self):
        """The commit 'Add cache to base.html' really removes menu queries on a warm cache."""
        make_tree()
        self.render_home()                       # warm
        warm = self.render_home()
        self.assertEqual(len(table_queries(warm, 'app_category')), 0)

    def test_cache_miss_category_queries_do_not_grow_with_tree_size(self):
        """Desired: O(1) queries to build the menu. Measures small vs large tree."""
        make_tree(roots=2, children=2, grandchildren=1)
        small = len(table_queries(self.render_home(), 'app_category'))
        cache.clear()
        Category.objects.all().delete()
        make_tree(roots=4, children=4, grandchildren=3)
        large = len(table_queries(self.render_home(), 'app_category'))
        print(f'\n[menu miss] category queries: small tree(14 nodes)={small}, large tree(84 nodes)={large}')
        self.assertEqual(small, large, 'menu rendering is O(N) in number of categories')

    def test_cache_miss_category_queries_absolute_budget(self):
        make_tree()   # 3 + 9 + 18 = 30 categories
        n = len(table_queries(self.render_home(), 'app_category'))
        print(f'\n[menu miss] 30 categories -> {n} category queries')
        self.assertLessEqual(n, 2)

    def test_breakdown_of_menu_queries(self):
        """Diagnostic: shows WHICH accesses cause the queries (parent FK vs children.all)."""
        make_tree()
        ctx = self.render_home()
        sqls = table_queries(ctx, 'app_category')
        parent_fetch = [s for s in sqls if re.search(r'"app_category"\."id" = ', s)]
        children_fetch = [s for s in sqls if re.search(r'"app_category"\."parent_id" = ', s)]
        listing = [s for s in sqls if s not in parent_fetch and s not in children_fetch]
        print(f'\n[menu breakdown] total={len(sqls)} parent-FK fetches={len(parent_fetch)} '
              f'children.all fetches={len(children_fetch)} list queries={len(listing)}')
        # Desired: no per-row parent fetch and no per-row children fetch.
        self.assertEqual(len(parent_fetch), 0, '`category.parent` is lazy-loaded once per child category')
        self.assertEqual(len(children_fetch), 0, '`category.children.all` is queried per node (twice in template)')

    def test_positive_control_prefetch_gives_constant_queries(self):
        """Shows the budget in the tests is achievable: 3 queries for any tree of depth 3."""
        make_tree()
        with CaptureQueriesContext(connection) as ctx:
            roots = list(Category.objects.filter(parent__isnull=True).prefetch_related('children__children'))
            _ = [g for r in roots for c in r.children.all() for g in c.children.all()]
        self.assertEqual(len(ctx), 3)

    def test_new_category_visible_without_waiting_an_hour(self):
        """Desired: editing categories invalidates the cached menu."""
        make_tree(roots=1, children=0, grandchildren=0)
        self.render_home()                                       # warm cache
        Category.objects.create(name_ua='Нова', name_en='New', slug='nova')
        # control: the only thing hiding it is the cache, not the query/template
        with mock.patch('app.context_processors.Category.objects.all', Category.objects.all):
            cache.clear()
            self.assertIn('/category/nova/', self.client.get(reverse('home')).content.decode())
        cache.clear(); self.render_home()
        Category.objects.create(name_ua='Нова2', name_en='New2', slug='nova2')
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('nova2', html, 'new category missing from menu until cache TTL (3600s) expires')

    def test_reorder_visible_immediately(self):
        make_tree(roots=2, children=0, grandchildren=0)
        self.render_home()
        u = make_editor()
        self.client.force_login(u)
        r0, r1 = Category.objects.get(slug='r0'), Category.objects.get(slug='r1')
        import json
        self.client.post(reverse('update_category_order'),
                         data=json.dumps([{'id': str(r0.id), 'order': 5}, {'id': str(r1.id), 'order': 1}]),
                         content_type='application/json')
        cache.clear()   # control: with a cold cache the new order is rendered correctly
        control = self.client.get(reverse('home')).content.decode()
        self.assertLess(control.index('/category/r1/'), control.index('/category/r0/'))
        Category.objects.filter(pk=r0.pk).update(order=0); Category.objects.filter(pk=r1.pk).update(order=1)
        cache.clear(); self.render_home()      # warm with the OLD order
        self.client.post(reverse('update_category_order'),
                         data=json.dumps([{'id': str(r0.id), 'order': 5}, {'id': str(r1.id), 'order': 1}]),
                         content_type='application/json')
        html = self.client.get(reverse('home')).content.decode()
        self.assertLess(html.index('/category/r1/'), html.index('/category/r0/'),
                        'reorder not reflected in cached menu')


# --------------------------------------------------------------------------- #
# Finding 2: article view = write per view
# --------------------------------------------------------------------------- #
class ArticleViewWriteTests(Base):
    def setUp(self):
        super().setUp()
        self.author = Author.objects.create(name_en='A', name_ua='А', description_en='d', description_ua='д', slug='a')
        self.cats = make_tree(roots=1, children=1, grandchildren=1)
        self.article = make_articles(1, self.cats[:1], self.author)[0]
        Article.objects.filter(pk=self.article.pk).update(views=0)

    def get_article(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('article', args=[self.article.slug]))
        self.assertEqual(resp.status_code, 200)
        return ctx

    def test_view_increment_is_single_narrow_update(self):
        ctx = self.get_article()
        writes = [q['sql'] for q in ctx.captured_queries if q['sql'].lstrip().upper().startswith(('UPDATE', 'INSERT', 'DELETE'))]
        print(f'\n[article view] write queries: {len(writes)}; first UPDATE touches full row: {"text" in writes[0]}')
        self.assertEqual(len(writes), 1)
        self.assertNotIn('"text"', writes[0], 'UPDATE rewrites the whole row incl. rich text')

    def test_view_does_not_run_slug_uniqueness_scan(self):
        ctx = self.get_article()
        slug_checks = [q['sql'] for q in ctx.captured_queries
                       if 'LIMIT 1' in q['sql'] and '"slug" =' in q['sql'] and 'app_article' in q['sql']
                       and 'NOT' in q['sql']]
        self.assertEqual(slug_checks, [], 'Article.save() override runs a uniqueness SELECT on every page view')

    def test_concurrent_views_are_not_lost(self):
        """Simulates a second request incrementing between our read and write."""
        import app.views as views
        real = views.get_object_or_404

        def racing(*a, **kw):
            obj = real(*a, **kw)
            Article.objects.filter(pk=obj.pk).update(views=F('views') + 10)   # concurrent requests
            return obj

        with mock.patch.object(views, 'get_object_or_404', racing):
            self.get_article()
        self.article.refresh_from_db()
        self.assertEqual(self.article.views, 11, f'lost update: views={self.article.views} (expected 10 + 1)')

    def test_parent_walk_queries_do_not_grow_with_depth(self):
        def depth_chain(d):
            parent = None
            for i in range(d):
                parent = Category.objects.create(name_ua=f'd{d}{i}', name_en=f'd{d}{i}', slug=f'd{d}-{i}', parent=parent)
            return parent
        results = {}
        for d in (1, 6):
            leaf = depth_chain(d)
            a = Article.objects.create(name=f'x{d}', slug=f'x{d}', text='t', is_published=True)
            a.categories.add(leaf)
            cache.clear()
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse('article', args=[a.slug]))
            results[d] = len(ctx)
        print(f'\n[article depth] total queries depth1={results[1]} depth6={results[6]}')
        self.assertEqual(results[1], results[6], 'one extra query per category level while walking to the root')

    def test_comment_count_queried_once(self):
        Comment.objects.create(article=self.article, author='x', text='y')
        ctx = self.get_article()
        counts = [q['sql'] for q in ctx.captured_queries if 'COUNT(' in q['sql'] and 'app_comment' in q['sql']]
        print(f'\n[article] COUNT queries on comments: {len(counts)}')
        self.assertLessEqual(len(counts), 1)


# --------------------------------------------------------------------------- #
# Finding 3: comment tree N+1
# --------------------------------------------------------------------------- #
class CommentTreeTests(Base):
    def build(self, n_roots, replies_each):
        art = Article.objects.create(name='c', slug='c', text='t', is_published=True)
        for i in range(n_roots):
            root = Comment.objects.create(article=art, author=f'u{i}', text='t')
            parent = root
            for j in range(replies_each):
                parent = Comment.objects.create(article=art, author='r', text='t', parent_comment=parent)
        return art

    def comment_queries(self, art):
        cache.clear()
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse('article', args=[art.slug])).status_code, 200)
        return len(table_queries(ctx, 'app_comment'))

    def test_comment_queries_constant_in_comment_count(self):
        small = self.comment_queries(self.build(1, 1))     # 2 comments
        Article.objects.all().delete()
        large = self.comment_queries(self.build(5, 4))     # 25 comments
        print(f'\n[comments] comment-table queries: 2 comments={small}, 25 comments={large}')
        self.assertEqual(small, large)


# --------------------------------------------------------------------------- #
# Finding 4: home page N+1 on article.categories
# --------------------------------------------------------------------------- #
class IndexQueryTests(Base):
    def test_home_category_queries_constant_in_article_count(self):
        cats = make_tree(roots=1, children=1, grandchildren=1)
        make_articles(2, cats)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('home'))
        few = len(ctx)
        Article.objects.all().delete()
        cache.clear()
        make_articles(15, cats)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('home'))
        many = len(ctx)
        print(f'\n[home] total queries: 2 articles={few}, 15 articles={many}')
        self.assertEqual(few, many, 'home page issues one categories query per article per loop')


# --------------------------------------------------------------------------- #
# Side bugs
# --------------------------------------------------------------------------- #
class SideBugTests(Base):
    def test_footer_category_links_resolve(self):
        make_tree(roots=1, children=0, grandchildren=0)
        html = self.client.get(reverse('home')).content.decode()
        footer = html.split('footer-row2')[1].split('</div>')[0]
        hrefs = re.findall(r'href="([^"]+)"', footer)
        self.assertTrue(hrefs)
        for h in hrefs:
            self.assertEqual(self.client.get(h).status_code, 200, f'footer link {h} is broken')

    def test_rss_feed_item_links_resolve(self):
        Article.objects.create(name='f', slug='f', text='t', is_published=True)
        resp = self.client.get(reverse('post_feed'))
        self.assertEqual(resp.status_code, 200)
        link = re.search(r'<item>.*?<link>https?://[^/]+(/[^<]*)</link>', resp.content.decode(), re.S).group(1)
        self.assertEqual(self.client.get(link).status_code, 200, f'feed item link {link} is a 404')

    def test_rss_feed_hides_unpublished(self):
        Article.objects.create(name='secret draft', slug='draft', text='t', is_published=False)
        self.assertNotIn('secret draft', self.client.get(reverse('post_feed')).content.decode())

    def test_sitemap_renders(self):
        AboutUsText.objects.create(pk=1)
        Article.objects.create(name='s', slug='s', text='t', is_published=True)
        Author.objects.create(name_en='A', name_ua='А', description_en='d', description_ua='д', slug='a')
        self.assertEqual(self.client.get(reverse('sitemap')).status_code, 200)

    def test_delete_category_works(self):
        self.client.force_login(make_editor())
        Category.objects.create(name_ua='z', name_en='z', slug='z')
        self.assertEqual(self.client.post(reverse('delete_category', args=['z'])).status_code, 200)
        self.assertFalse(Category.objects.filter(slug='z').exists())

    def test_edit_author_redirects(self):
        self.client.force_login(make_editor())
        Author.objects.create(name_en='A', name_ua='А', description_en='d', description_ua='д', slug='a')
        resp = self.client.post(reverse('edit_author', args=['a']),
                                {'name_ua': 'x', 'name_en': 'x', 'description_ua': 'x', 'description_en': 'x'})
        self.assertEqual(resp.status_code, 302)


# --------------------------------------------------------------------------- #
# Regression: output is unchanged by the query optimisations
# --------------------------------------------------------------------------- #
class OutputRegressionTests(Base):
    def test_menu_renders_all_levels_in_order(self):
        make_tree(roots=2, children=2, grandchildren=1)
        html = self.client.get(reverse('home')).content.decode()
        menu = html.split('<ul class="menu">')[1].split('</ul>\n                 \n')[0]
        for slug in ('r0', 'r1', 'c00', 'c01', 'g000', 'g010'):
            self.assertIn(f'/category/{slug}/', menu)
        self.assertLess(menu.index('/category/r0/'), menu.index('/category/c00/'))
        self.assertLess(menu.index('/category/c00/'), menu.index('/category/g000/'))
        self.assertLess(menu.index('/category/g000/'), menu.index('/category/r1/'))
        self.assertEqual(menu.count('class="sub-menu'), 2 + 4)   # 2 roots + 4 children have sub-menus

    def test_nested_replies_and_count_rendered(self):
        art = Article.objects.create(name='c', slug='c', text='t', is_published=True)
        root = Comment.objects.create(article=art, author='A-root', text='t')
        r1 = Comment.objects.create(article=art, author='B-reply', text='t', parent_comment=root)
        Comment.objects.create(article=art, author='C-deep', text='t', parent_comment=r1)
        html = self.client.get(reverse('article', args=['c'])).content.decode()
        for name in ('A-root', 'B-reply', 'C-deep'):
            self.assertEqual(html.count(f'>{name}</p>'), 1, name)
        self.assertLess(html.index('A-root'), html.index('B-reply'))
        self.assertLess(html.index('B-reply'), html.index('C-deep'))

    def test_view_counter_shown_and_persisted(self):
        Article.objects.create(name='v', slug='v', text='t', is_published=True, views=4)
        self.client.get(reverse('article', args=['v']))
        self.assertEqual(Article.objects.get(slug='v').views, 5)

    def test_recommended_articles_use_root_category(self):
        root = Category.objects.create(name_ua='R', name_en='R', slug='rr')
        leaf = Category.objects.create(name_ua='L', name_en='L', slug='ll', parent=root)
        a = Article.objects.create(name='main', slug='main', text='t', is_published=True)
        a.categories.add(leaf)
        other = Article.objects.create(name='Other-Rec', slug='other', text='t', is_published=True)
        other.categories.add(root)
        html = self.client.get(reverse('article', args=['main'])).content.decode()
        self.assertIn('Other-Rec', html)
