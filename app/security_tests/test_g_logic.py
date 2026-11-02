"""G. Information disclosure and business logic: drafts, view counter, comments, error pages."""
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from app.models import Article, Comment

from .base import REPO, SecBase, add_cases, body_text, prod_setting, tracked_files

HIDDEN = {'draft': ('SECRET DRAFT TITLE', 'secret-draft'), 'scheduled': ('SCHEDULED TITLE', 'future-post')}
SURFACES = {
    'index': '/', 'all_articles': '/all', 'category_page': '/category/root/', 'subcategory_page': '/category/child/',
    'author_page': '/authors/author', 'search_by_title': '/search/?q=TITLE', 'search_by_body': '/search/?q=BODY',
    'search_all': '/search/', 'rss_feed': '/feed/', 'sitemap': '/sitemap.xml', 'other_article_sidebar': '/article/public/',
}


class UnpublishedContent(SecBase):
    def setUp(self):
        super().setUp()
        Article.objects.filter(pk__in=[self.draft.pk, self.scheduled.pk]).update(views=9999)


CASES = {f'{surface}__{kind}': (surface, kind) for surface in SURFACES for kind in HIDDEN}


@add_cases(UnpublishedContent, 'anonymous_cannot_see', CASES)
def _hidden(self, spec):
    surface, kind = spec
    title, slug = HIDDEN[kind]
    html = body_text(self.make_client().get(SURFACES[surface]))
    self.assertNotIn(title, html, f'{kind} article title leaks through {SURFACES[surface]}')
    self.assertNotIn(f'/article/{slug}/', html, f'{kind} article link leaks through {SURFACES[surface]}')


@add_cases(UnpublishedContent, 'direct_url_is_not_public', {k: k for k in HIDDEN})
def _direct(self, kind):
    title, slug = HIDDEN[kind]
    response = self.make_client().get(f'/article/{slug}/')
    self.assertEqual(response.status_code, 404, f'/article/{slug}/ is open to anyone who guesses the slug ({kind}): article_detail has no is_published/publish_at check')
    self.assertNotContains(response, title, status_code=response.status_code)


@add_cases(UnpublishedContent, 'editor_can_still_preview', {k: k for k in HIDDEN})
def _preview(self, kind):
    self.assertEqual(self.make_client(self.editor_user).get(f'/article/{HIDDEN[kind][1]}/').status_code, 200)


@add_cases(UnpublishedContent, 'comment_on_unpublished_is_refused', {k: k for k in HIDDEN})
def _comment_hidden(self, kind):
    article = Article.objects.get(slug=HIDDEN[kind][1])
    with mock.patch('app.views.CommentCaptchaForm.is_valid', return_value=True):
        self.make_client().post(self.url('comment_root'), {'article_id': str(article.id), 'author': 'a', 'text': 'spy'})
    self.assertFalse(Comment.objects.filter(article=article).exists(), f'comments accepted on a {kind} article (also confirms its UUID is valid)')


class ViewCounter(SecBase):
    def views(self):
        return Article.objects.get(pk=self.article.pk).views

    def test_repeated_requests_from_one_client_count_once(self):
        client = self.make_client()
        for _ in range(20):
            client.get('/article/public/')
        self.assertLessEqual(self.views(), 1, f'20 reloads gave {self.views()} views: the counter has no per-visitor throttle')

    def test_head_requests_do_not_count(self):
        client = self.make_client()
        for _ in range(5):
            client.head('/article/public/')
        self.assertEqual(self.views(), 0, 'HEAD requests increment the view counter')

    def test_crawlers_do_not_inflate_views(self):
        client = self.make_client()
        for _ in range(5):
            client.get('/article/public/', HTTP_USER_AGENT='Googlebot/2.1 (+http://www.google.com/bot.html)')
        self.assertEqual(self.views(), 0, 'crawler hits are counted as readers')

    def test_counter_update_is_atomic(self):
        with CaptureQueriesContext(connection) as ctx:
            self.make_client().get('/article/public/')
        updates = [q['sql'] for q in ctx.captured_queries if q['sql'].startswith('UPDATE "app_article"')]
        self.assertTrue(updates and '"views" + 1' in updates[0], 'views must be incremented in SQL (F expression), not read-modify-write')

    def test_popular_list_cannot_be_hijacked_by_one_client(self):
        client = self.make_client()
        other = self.make_article('rival', 'Rival', 'x')
        for _ in range(50):
            client.get(f'/article/{other.slug}/')
        self.assertLess(Article.objects.get(pk=other.pk).views, 50, 'one client can push any article to the top of the popular list')


class CommentAbuse(SecBase):
    def reply(self, **extra):
        return self.make_client().post(self.url('comment_reply'), {**self.data('comment_reply'), **extra})

    def root(self, valid_captcha=True, **extra):
        with mock.patch('app.views.CommentCaptchaForm.is_valid', return_value=valid_captcha):
            return self.make_client().post(self.url('comment_root'), {**self.data('comment_root'), **extra})

    def test_reply_requires_captcha(self):
        with mock.patch('app.views.CommentCaptchaForm.is_valid', return_value=False):
            self.reply(text='spam reply')
        self.assertFalse(Comment.objects.filter(text='spam reply').exists(), 'replies (parent_comment_id set) skip the captcha entirely')

    def test_root_comment_requires_captcha(self):
        self.root(valid_captcha=False, text='spam root')
        self.assertFalse(Comment.objects.filter(text='spam root').exists())

    def test_root_comment_with_valid_captcha_is_stored(self):
        self.root(text='legit')
        self.assertTrue(Comment.objects.filter(text='legit').exists())

    def test_reply_flood_is_rate_limited(self):
        client = self.make_client()
        statuses = [client.post(self.url('comment_reply'), self.data('comment_reply')).status_code for _ in range(40)]
        self.assertTrue(any(s in (403, 429) for s in statuses), f'40 replies in a burst were all accepted ({Comment.objects.count()} comments stored)')

    def test_root_comment_flood_is_rate_limited(self):
        client = self.make_client()
        with mock.patch('app.views.CommentCaptchaForm.is_valid', return_value=True):
            statuses = [client.post(self.url('comment_root'), self.data('comment_root')).status_code for _ in range(40)]
        self.assertTrue(any(s in (403, 429) for s in statuses), 'a solved captcha can be replayed for unlimited comments')

    def test_author_length_is_validated(self):
        self.reply(author='a' * 101, text='long author')
        self.assertFalse(Comment.objects.filter(text='long author').exists(), 'Comment.author is max_length=100 but the view never validates it (MySQL strict mode: 500)')

    def test_text_length_is_limited(self):
        self.reply(text='z' * 100_000)
        self.assertFalse(Comment.objects.filter(text__startswith='zzzz').exists(), 'unbounded comment text (up to the 2.5 MB request cap)')

    def test_blank_comments_are_refused(self):
        self.reply(author='   ', text='   ')
        self.assertEqual(Comment.objects.filter(author='   ').count(), 0, 'whitespace-only comments are stored')

    def test_html_in_comment_author_is_escaped_in_page(self):
        self.reply(author='<b>x</b>', text='<i>y</i>')
        html = body_text(self.make_client().get('/article/public/'))
        self.assertNotIn('<b>x</b>', html)
        self.assertNotIn('<i>y</i>', html)

    def test_comment_get_does_not_create_anything(self):
        before = Comment.objects.count()
        self.make_client().get('/comment', {'article_id': str(self.article.id), 'author': 'a', 'text': 't'})
        self.assertEqual(Comment.objects.count(), before)

    def test_no_mail_sending_code_to_abuse(self):
        offenders = [p for p in tracked_files() if p.startswith('app/') and p.endswith('.py') and 'send_mail' in (REPO / p).read_text(encoding='utf-8', errors='ignore')]
        self.assertEqual([p for p in offenders if 'security_tests' not in p], [])


class ErrorPages(SecBase):
    def production_debug(self):
        return override_settings(DEBUG=prod_setting('DEBUG'))

    def test_404_does_not_reveal_url_map_with_production_debug(self):
        with self.production_debug():
            body = body_text(self.make_client().get('/no-such-page/'))
        self.assertNotIn('editor-cabinet', body, 'DEBUG=True turns every 404 into a page listing all routes (admin, ckeditor, editor-cabinet ...)')

    def test_500_does_not_reveal_paths_with_production_debug(self):
        with self.production_debug():
            body = body_text(self.make_client(self.editor_user).get('/about-us-edit'))
        self.assertNotIn('Traceback', body, 'DEBUG=True renders full tracebacks, local variables and file paths to visitors')
        self.assertNotIn(str(REPO), body)

    def test_500_is_generic_when_debug_is_off(self):
        response = self.make_client(self.editor_user).get('/about-us-edit')
        body = body_text(response)
        self.assertEqual(response.status_code, 500)
        for leak in ('Traceback', str(REPO), 'views.py', 'ValueError'):
            self.assertNotIn(leak, body)

    def test_404_is_generic_when_debug_is_off(self):
        body = body_text(self.make_client().get('/no-such-page/'))
        for leak in ('URLconf', 'editor-cabinet', str(REPO)):
            self.assertNotIn(leak, body)

    def test_uuid_article_route_does_not_leak_internals(self):
        body = body_text(self.make_client().get(f'/article/{self.article.id}/'))
        for leak in ('TypeError', 'article_detail', 'Traceback'):
            self.assertNotIn(leak, body)

    def test_article_by_id_route_is_dead_code(self):
        from django.urls import resolve
        self.assertEqual(resolve(f'/article/{self.article.id}/').url_name, 'article_by_id',
                         'article/<uuid:id>/ is shadowed by article/<slug:slug>/ (a UUID is a valid slug), so it is unreachable')

    def test_media_and_static_not_served_by_django_without_debug(self):
        self.assertEqual(self.make_client().get('/media/card-example.png').status_code, 404)

    def test_debug_static_serving_is_off_in_production(self):
        self.assertFalse(prod_setting('DEBUG'), 'with DEBUG=True django.conf.urls.static serves MEDIA_ROOT and STATIC_ROOT through the app (anarchia/urls.py)')

    def test_error_pages_have_no_stack_for_method_errors(self):
        body = body_text(self.make_client(self.editor_user).post(self.url('delete_article')))
        self.assertNotIn('Traceback', body)
