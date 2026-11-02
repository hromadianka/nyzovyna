"""D. Injection and input validation: SQL/ORM safety, malformed input must give 4xx and never 500."""
import json
import re
from unittest import mock

from django.contrib.auth.models import User
from django.urls import NoReverseMatch, reverse

from app.models import AboutUsText, Article, Category, Comment

from .base import REPO, SQLI_PAYLOADS, SecBase, add_cases, body_text, tracked_files

BIG = 'x' * (3 * 1024 * 1024)


class SqlInjection(SecBase):
    def assert_database_intact(self, key):
        self.assertTrue(Article.objects.filter(pk=self.article.pk).exists(), f'{key}: articles table damaged')
        self.assertFalse(User.objects.filter(is_superuser=True).exclude(username='staffer').exists(), f'{key}: privilege escalation')
        self.assertEqual(User.objects.count(), 3, f'{key}: users changed')


@add_cases(SqlInjection, 'search_query_is_parametrised', SQLI_PAYLOADS)
def _sqli_search(self, payload):
    response = self.make_client().get('/search/', {'q': payload})
    self.assertEqual(response.status_code, 200)
    self.assertEqual(len(response.context['results']), 0, 'payload widened the result set: query is not parametrised')
    self.assert_database_intact(payload)


@add_cases(SqlInjection, 'comment_fields_are_parametrised', SQLI_PAYLOADS)
def _sqli_comment(self, payload):
    with captcha_ok():
        self.make_client().post(self.url('comment_reply'), {**self.data('comment_reply'), 'author': payload, 'text': payload})
    self.assertTrue(Comment.objects.filter(text=payload).exists(), 'payload must be stored verbatim as data')
    self.assert_database_intact(payload)


@add_cases(SqlInjection, 'login_is_parametrised', SQLI_PAYLOADS)
def _sqli_login(self, payload):
    response = self.make_client().post(reverse('login'), {'login': payload, 'password': payload})
    self.assertEqual(response.status_code, 200, 'login with an injection payload must just fail')
    self.assertNotIn('_auth_user_id', self.client.session)


@add_cases(SqlInjection, 'url_slug_is_parametrised', {k: v for k, v in SQLI_PAYLOADS.items()})
def _sqli_slug(self, payload):
    from urllib.parse import quote
    for prefix in ('/article/', '/category/', '/authors/'):
        response = self.make_client().get(f'{prefix}{quote(payload, safe="")}' + ('' if prefix == '/authors/' else '/'))
        self.assertEqual(response.status_code, 404, f'{prefix}: expected 404 for a non-matching slug')
    self.assert_database_intact(payload)


@add_cases(SqlInjection, 'category_order_json_id', SQLI_PAYLOADS)
def _sqli_json(self, payload):
    self.post_json(self.make_client(self.editor_user), self.url('update_category_order'), [{'id': payload, 'order': 1}])
    self.assertEqual(Category.objects.get(pk=self.root_cat.pk).order, 0)
    self.assert_database_intact(payload)


class OrmOnly(SecBase):
    PATTERNS = {
        'raw_sql': r'\.raw\(|\.extra\(|RawSQL|cursor\(\)|connection\.execute',
        'regex_lookups': r'__i?regex',
        'code_exec': r'\beval\(|\bexec\(|os\.system|subprocess|pickle\.loads|yaml\.load\(',
        'mark_safe': r'mark_safe|SafeString|format_html',
        'template_from_string': r'Template\(|from_string\(',
    }


def _app_sources():
    return [rel for rel in tracked_files() if rel.endswith('.py') and rel.startswith(('app/', 'anarchia/'))
            and '/migrations/' not in rel and 'security_tests' not in rel
            and not rel.endswith(('test_findings.py', 'settings_test.py', 'tests.py'))]


@add_cases(OrmOnly, 'no_dangerous_construct', OrmOnly.PATTERNS)
def _no_construct(self, pattern):
    hits = []
    for rel in _app_sources():
        for number, line in enumerate((REPO / rel).read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            if re.search(pattern, line) and not (rel == 'app/templatetags/app_tags.py' and 'mark_safe' in pattern):
                hits.append(f'{rel}:{number}: {line.strip()}')
    self.assertEqual(hits, [], f'dangerous constructs: {hits}')


def captcha_ok():
    return mock.patch('app.views.CommentCaptchaForm.is_valid', return_value=True)


def post_as(self, key, **overrides):
    client = self.make_client(self.editor_user)
    data = {**self.data(key), **overrides}
    return client.post(self.url(key), data)


def drop(data, field):
    return {k: v for k, v in data.items() if k != field}


# key -> (request callable, state change allowed when the input is actually valid)
GARBAGE = {
    # public comment endpoint
    'comment_missing_article_id': lambda s: s.make_client().post('/comment', {'author': 'a', 'text': 't', 'parent_comment_id': str(s.comment.id)}),
    'comment_article_id_not_uuid': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'article_id': 'not-a-uuid'}),
    'comment_unknown_article': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'article_id': '00000000-0000-0000-0000-000000000000'}),
    'comment_parent_not_uuid': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'parent_comment_id': "1' OR '1'='1"}),
    'comment_reply_without_author': lambda s: s.make_client().post('/comment', drop(s.data('comment_reply'), 'author')),
    'comment_reply_without_text': lambda s: s.make_client().post('/comment', drop(s.data('comment_reply'), 'text')),
    'comment_reply_author_101_chars': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'author': 'a' * 101}),
    'comment_reply_blank_fields': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'author': '  ', 'text': ''}),
    'comment_reply_text_3mb': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'text': BIG}),
    'comment_reply_text_1mb': lambda s: s.make_client().post('/comment', {**s.data('comment_reply'), 'text': 'y' * 1024 * 1024}),
    'comment_root_without_author': lambda s: _with_captcha(s, drop(s.data('comment_root'), 'author')),
    'comment_root_without_text': lambda s: _with_captcha(s, drop(s.data('comment_root'), 'text')),
    # public read endpoints
    'article_by_uuid_route': lambda s: s.make_client().get(f'/article/{s.article.id}/'),
    'search_q_5000_chars': lambda s: s.make_client().get('/search/', {'q': 'a' * 5000}),
    'search_q_null_byte': lambda s: s.make_client().get('/search/?q=a%00b'),
    'search_q_invalid_utf8': lambda s: s.make_client().get('/search/?q=%ED%A0%80%FF'),
    'search_q_unicode_exotic': lambda s: s.make_client().get('/search/', {'q': 'ᾨ‮🏴\u0000é'}),
    'article_slug_5000_chars': lambda s: s.make_client().get('/article/' + 'a' * 5000 + '/'),
    'category_slug_5000_chars': lambda s: s.make_client().get('/category/' + 'a' * 5000 + '/'),
    'article_slug_null_byte': lambda s: s.make_client().get('/article/a%00b/'),
    'login_null_byte': lambda s: s.make_client().post('/login/', {'login': 'a\x00b', 'password': 'c\x00d'}),
    'login_missing_fields': lambda s: s.make_client().post('/login/', {}),
    'login_huge_password': lambda s: s.make_client().post('/login/', {'login': 'editor', 'password': 'p' * 1_000_000}),
    'set_language_unknown_code': lambda s: s.make_client().post('/set-language/', {'language': 'zz', 'next': '/'}),
    'set_language_missing': lambda s: s.make_client().post('/set-language/', {}),
    # publish / edit article
    'publish_date_garbage': lambda s: post_as(s, 'publish', publish_option='schedule', publish_datetime='tomorrow'),
    'publish_date_out_of_range': lambda s: post_as(s, 'publish', publish_option='schedule', publish_datetime='9999-13-45T99:99'),
    'publish_without_name': lambda s: s.make_client(s.editor_user).post('/publish', drop(s.data('publish'), 'article_name')),
    'publish_without_text': lambda s: s.make_client(s.editor_user).post('/publish', drop(s.data('publish'), 'article_text')),
    'publish_without_language': lambda s: s.make_client(s.editor_user).post('/publish', drop(s.data('publish'), 'language')),
    'publish_author_not_uuid': lambda s: post_as(s, 'publish', article_author='abc'),
    'publish_category_not_uuid': lambda s: post_as(s, 'publish', categories=['abc']),
    'publish_language_not_in_choices': lambda s: post_as(s, 'publish', language='zz'),
    'publish_language_too_long': lambda s: post_as(s, 'publish', language='ua' * 10),
    'publish_text_3mb': lambda s: post_as(s, 'publish', article_text=BIG),
    'publish_slug_path_traversal': lambda s: post_as(s, 'publish', article_slug='../../etc/passwd'),
    'edit_article_date_garbage': lambda s: post_as(s, 'edit_article', publish_option='schedule', publish_datetime='soon'),
    'edit_article_author_not_uuid': lambda s: post_as(s, 'edit_article', article_author='abc'),
    'edit_article_category_not_uuid': lambda s: post_as(s, 'edit_article', categories=['abc']),
    'edit_article_without_name': lambda s: s.make_client(s.editor_user).post(s.url('edit_article'), drop(s.data('edit_article'), 'article_name')),
    'edit_article_language_not_in_choices': lambda s: post_as(s, 'edit_article', language='zz'),
    # categories, authors, about us
    'create_category_parent_not_uuid': lambda s: post_as(s, 'create_category', parent_id='abc'),
    'create_category_without_names': lambda s: s.make_client(s.editor_user).post('/create-category/', {}),
    'create_category_name_101_chars': lambda s: post_as(s, 'create_category', name_ua='n' * 101),
    'create_author_without_image': lambda s: s.make_client(s.editor_user).post('/create_new_author/', drop(s.data('create_new_author'), 'author_image')),
    'create_author_without_fields': lambda s: s.make_client(s.editor_user).post('/create_new_author/', {}),
    'create_author_name_101_chars': lambda s: post_as(s, 'create_new_author', author_name_en='n' * 101),
    'edit_author_without_fields': lambda s: s.make_client(s.editor_user).post(s.url('edit_author'), {}),
    'about_us_edit_without_fields': lambda s: s.make_client(s.editor_user).post('/about-us-edit', {}),
    'about_us_edit_get': lambda s: s.make_client(s.editor_user).get('/about-us-edit'),
    'delete_article_get': lambda s: s.make_client(s.editor_user).get(s.url('delete_article')),
    'delete_category_get': lambda s: s.make_client(s.editor_user).get(s.url('delete_category')),
    # category order JSON
    'order_body_not_json': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), 'garbage{'),
    'order_body_empty': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), ''),
    'order_body_json_object': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), {'id': 'x'}),
    'order_body_json_null': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), 'null'),
    'order_items_are_ints': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [1, 2, 3]),
    'order_item_missing_keys': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{}]),
    'order_item_id_not_uuid': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{'id': 'abc', 'order': 1}]),
    'order_item_order_not_int': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{'id': str(s.root_cat.id), 'order': 'abc'}]),
    'order_item_order_beyond_int32': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{'id': str(s.root_cat.id), 'order': 2 ** 40}]),
    'order_item_order_huge': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{'id': str(s.root_cat.id), 'order': 10 ** 30}]),
    'order_item_order_null': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), [{'id': str(s.root_cat.id), 'order': None}]),
    'order_body_3mb': lambda s: s.post_json(s.make_client(s.editor_user), s.url('update_category_order'), json.dumps([{'id': 'x', 'order': 1, 'pad': BIG}])),
}


def _with_captcha(self, data):
    with captcha_ok():
        return self.make_client().post('/comment', data)


# Inputs that are legitimately valid: the request may change state, it just must not crash.
VALID_INPUT = {'search_q_5000_chars', 'search_q_null_byte', 'search_q_invalid_utf8', 'search_q_unicode_exotic',
               'login_null_byte', 'login_missing_fields', 'login_huge_password', 'set_language_unknown_code',
               'set_language_missing', 'create_author_without_image', 'article_by_uuid_route', 'about_us_edit_get',
               'article_slug_5000_chars', 'category_slug_5000_chars', 'article_slug_null_byte', 'publish_slug_path_traversal'}


class MalformedInput(SecBase):
    pass


@add_cases(MalformedInput, 'never_a_server_error', {k: k for k in GARBAGE})
def _no_500(self, key):
    before = self.snapshot()
    response = GARBAGE[key](self)
    self.assertLess(response.status_code, 500, f'{key}: HTTP {response.status_code} on malformed input (unhandled exception); expected a 4xx')
    if key not in VALID_INPUT:
        self.assertEqual(self.snapshot(), before, f'{key}: invalid input was accepted and stored')


class MissingSingletons(SecBase):
    def test_about_us_page_survives_missing_row(self):
        AboutUsText.objects.all().delete()
        self.assertLess(self.make_client().get('/about-us').status_code, 500, 'public /about-us crashes when AboutUsText pk=1 does not exist')

    def test_editor_cabinet_survives_missing_about_row(self):
        AboutUsText.objects.all().delete()
        self.assertLess(self.make_client(self.editor_user).get('/editor-cabinet').status_code, 500)

    def test_about_us_edit_survives_missing_row(self):
        AboutUsText.objects.all().delete()
        self.assertLess(post_as(self, 'about_us_edit').status_code, 500)


class NonAsciiNames(SecBase):
    def test_cyrillic_category_gets_a_routable_slug(self):
        post_as(self, 'create_category', name_ua='Культура', name_en='Culture')
        category = Category.objects.get(name_ua='Культура')
        self.assertTrue(category.slug, f'slugify() of a Cyrillic name yields an empty slug: {category.slug!r}')
        try:
            reverse('category_articles', args=[category.slug])
        except NoReverseMatch:
            self.fail('category without a routable slug breaks every page (menu in base.html)')

    def test_site_survives_cyrillic_category_created_by_editor(self):
        post_as(self, 'create_category', name_ua='Культура', name_en='Культура')
        for url in ('/', '/article/public/', '/authors'):
            with self.subTest(url=url):
                self.assertEqual(self.make_client().get(url).status_code, 200, f'{url} returns 5xx after creating a Cyrillic category')

    def test_cyrillic_author_gets_a_routable_slug(self):
        post_as(self, 'create_new_author', author_name_en='Іван', author_name_ua='Іван')
        from app.models import Author
        author = Author.objects.get(name_ua='Іван')
        self.assertTrue(author.slug)
        self.assertEqual(self.make_client().get(f'/authors/{author.slug}').status_code, 200)


class SstiAndUnicode(SecBase):
    def test_template_syntax_in_search_is_inert(self):
        html = body_text(self.make_client().get('/search/', {'q': '{{ 1234567|add:"1" }}{% load os %}'}))
        self.assertNotIn('1234568', html)

    def test_slug_input_cannot_escape_url_space(self):
        for raw in ('../../admin/', 'a/b', 'a b', 'a?b=c', 'a#b', '%2e%2e%2f'):
            with self.subTest(slug=raw):
                post_as(self, 'publish', article_slug=raw, article_name=f'N {raw}')
        for slug in Article.objects.values_list('slug', flat=True):
            self.assertRegex(slug, r'^[-\w]+$')
