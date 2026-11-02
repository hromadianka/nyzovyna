"""C. Cross-site scripting: stored, reflected and DOM sinks, server-side sanitisation, browser-side headers."""
import xml.etree.ElementTree as ET

from django.urls import reverse

from app.models import AboutUsText, Article, Author, Category, Comment

from .base import MARK, XSS_PAYLOADS, SecBase, active_content, add_cases, body_text, known_open

LISTING_URLS = ['/', '/all', '/category/root/', '/authors/author', '/search/?q=BODY', '/search/']


class XssBase(SecBase):
    def assert_inert(self, html, where, payload_key):
        found = active_content(html)
        self.assertEqual(found, [], f'{where}: payload {payload_key!r} becomes active content in the page: {found}')

    def each_payload(self, apply, urls, client=None):
        client = client or self.make_client()
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                apply(payload)
                for url in urls:
                    self.assert_inert(body_text(client.get(url)), url, key)


class StoredXssInEscapedFields(XssBase):
    """Fields the templates are expected to auto-escape. Green = safe."""

    def test_comment_text(self):
        def apply(p):
            Comment.objects.filter(pk=self.comment.pk).update(text=p)
        self.each_payload(apply, ['/article/public/'])

    def test_comment_author(self):
        def apply(p):
            Comment.objects.filter(pk=self.comment.pk).update(author=p)
        self.each_payload(apply, ['/article/public/', '/editor-cabinet/comments-moderation/'], self.make_client(self.editor_user))

    def test_reply_posted_without_captcha(self):
        def apply(p):
            self.make_client().post(self.url('comment_reply'), {**self.data('comment_reply'), 'author': p, 'text': p})
        self.each_payload(apply, ['/article/public/'])

    def test_comment_reply_form_prefill(self):
        # <textarea>{{ comment.author }}, </textarea> breaks out with </textarea><script>
        def apply(p):
            Comment.objects.filter(pk=self.comment.pk).update(author='</textarea>' + p)
        self.each_payload(apply, ['/article/public/'])

    def test_search_query_reflection(self):
        client = self.make_client()
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                self.assert_inert(body_text(client.get('/search/', {'q': payload})), '/search/?q=', key)

    def test_author_names(self):
        for field in ('name_ua', 'name_en'):
            def apply(p, field=field):
                Author.objects.filter(pk=self.author.pk).update(**{field: p})
            with self.subTest(field=field):
                self.each_payload(apply, ['/authors', '/authors/author', '/article/public/', '/'])

    def test_author_descriptions(self):
        for field in ('description_ua', 'description_en'):
            def apply(p, field=field):
                Author.objects.filter(pk=self.author.pk).update(**{field: p})
            with self.subTest(field=field):
                self.each_payload(apply, ['/authors', '/authors/author', '/article/public/'])

    def test_author_edit_form_values(self):
        def apply(p):
            Author.objects.filter(pk=self.author.pk).update(name_ua=p, description_ua=p)
        self.each_payload(apply, [f'/authors/{self.author.slug}/edit'], self.make_client(self.editor_user))

    def test_article_title(self):
        def apply(p):
            Article.objects.filter(pk=self.article.pk).update(name=p)
        urls = LISTING_URLS + ['/article/public/', '/article/public/edit/', '/editor-cabinet']
        self.each_payload(apply, urls, self.make_client(self.editor_user))

    def test_category_names_in_menu_and_pages(self):
        for field in ('name_ua', 'name_en'):
            def apply(p, field=field):
                Category.objects.filter(pk=self.root_cat.pk).update(**{field: p})
                from app.menu_cache import invalidate_menu_cache
                invalidate_menu_cache()
            with self.subTest(field=field):
                self.each_payload(apply, ['/', '/article/public/', '/category/root/', '/editor-cabinet', '/publish'],
                                  self.make_client(self.editor_user))

    def test_slug_cannot_carry_markup(self):
        client = self.make_client(self.editor_user)
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                client.post(self.url('publish'), {**self.data('publish'), 'article_slug': payload})
                for slug in Article.objects.values_list('slug', flat=True):
                    self.assertRegex(slug, r'^[-\w]+$', f'unsafe slug stored for {key}: {slug!r}')

    def test_text_is_not_template_evaluated(self):
        Article.objects.filter(pk=self.article.pk).update(name='{{ 1234567|add:"1" }}{% now "Y" %}')
        Comment.objects.filter(pk=self.comment.pk).update(text='{{ settings.SECRET_KEY }}{{ 1234567|add:"1" }}')
        html = body_text(self.make_client().get('/article/public/'))
        self.assertNotIn('1234568', html, 'user text is evaluated as a template (SSTI)')
        self.assertNotIn('django-insecure', html)


class StoredXssInRawFields(XssBase):
    """Fields rendered through |safe / {% autoescape off %}: expected to be sanitised, therefore red today."""

    def test_article_body_on_article_page(self):
        def apply(p):
            Article.objects.filter(pk=self.article.pk).update(text=f'<p>intro</p>{p}')
        self.each_payload(apply, ['/article/public/'])

    def test_article_body_survives_editor_round_trip_unharmed(self):
        Article.objects.filter(pk=self.article.pk).update(text='<p>Hello <strong>world</strong></p><ul><li>x</li></ul>')
        html = body_text(self.make_client().get('/article/public/'))
        self.assertIn('<strong>world</strong>', html, 'a sanitiser must keep ordinary formatting')

    def test_about_us_text(self):
        for field in ('text_ua', 'text_en'):
            def apply(p, field=field):
                AboutUsText.objects.filter(pk=1).update(**{field: p})
            with self.subTest(field=field):
                self.each_payload(apply, ['/about-us'])

    def test_article_summary_cards_strip_markup_safely(self):
        def apply(p):
            Article.objects.filter(pk=self.article.pk).update(text=f'intro {p}')
        self.each_payload(apply, LISTING_URLS + ['/editor-cabinet'], self.make_client(self.editor_user))

    def test_summary_cards_with_html_tail_cut_by_truncation(self):
        # truncatechars runs after striptags, an unterminated tag then swallows the following markup.
        tail = f"<img src=x onerror=alert('{MARK}')"
        Article.objects.filter(pk=self.article.pk).update(text='x ' * 150 + tail)
        for url in LISTING_URLS:
            with self.subTest(url=url):
                self.assert_inert(body_text(self.make_client().get(url)), url, 'truncated_unclosed_tag')

    def test_rss_description_is_inert_html(self):
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                Article.objects.filter(pk=self.article.pk).update(text=f'<p>t</p>{payload}')
                root = ET.fromstring(self.make_client().get('/feed/').content)
                descriptions = [d.text or '' for d in root.iter('description')]
                for description in descriptions:
                    self.assert_inert(description, '/feed/ <description>', key)

    def test_oembed_url_scheme_is_restricted(self):
        # article.html turns <oembed url=...> into iframe.src in the browser (DOM sink)
        Article.objects.filter(pk=self.article.pk).update(text='<oembed url="javascript:alert(\'%s\')"></oembed>' % MARK)
        self.assert_inert(body_text(self.make_client().get('/article/public/')), '/article/public/', 'oembed_js')

    def test_article_text_is_sanitised_before_storage_via_publish(self):
        client = self.make_client(self.editor_user)
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                client.post(self.url('publish'), {**self.data('publish'), 'article_text': payload, 'article_name': f'T-{key}'})
                stored = Article.objects.get(name=f'T-{key}').text
                self.assertEqual(active_content(stored), [], f'{key}: markup is stored verbatim; there is no server-side allowlist/bleach')

    def test_about_us_is_sanitised_before_storage(self):
        client = self.make_client(self.editor_user)
        for key, payload in XSS_PAYLOADS.items():
            with self.subTest(payload=key):
                client.post(self.url('about_us_edit'), {'new_text_ua': payload, 'new_text_en': payload})
                self.assertEqual(active_content(AboutUsText.objects.get(pk=1).text_ua), [], f'{key} stored verbatim in AboutUsText')


class InlineJsContexts(XssBase):
    def test_ids_used_in_onclick_are_uuids(self):
        client = self.make_client(self.editor_user)
        html = body_text(client.get('/article/public/'))
        import re
        for value in re.findall(r"toggleReplyForm\('([^']*)'\)", html):
            self.assertRegex(value, r'^[0-9a-f-]{36}$', f'non-UUID value inside inline JS: {value!r}')

    def test_slug_in_editor_onclick_is_plain(self):
        html = body_text(self.make_client(self.editor_user).get('/editor-cabinet'))
        import re
        for value in re.findall(r"confirmDelete\(event, '([^']*)'\)", html):
            self.assertRegex(value, r'^[-\w]+$')

    def test_javascript_url_in_text_fields_is_never_linked(self):
        Comment.objects.filter(pk=self.comment.pk).update(author="javascript:alert('XSSMARK')", text="javascript:alert('XSSMARK')")
        self.assert_inert(body_text(self.make_client().get('/article/public/')), '/article/public/', 'js_url_text')

    def test_next_parameter_is_not_reflected_on_login_page(self):
        response = self.make_client().get('/login/', {'next': f"\"><script>alert('{MARK}')</script>"})
        self.assert_inert(body_text(response), '/login/?next=', 'next')

    def test_request_path_in_language_form_is_escaped(self):
        response = self.make_client().get(f'/search/%22%3E%3Cscript%3Ealert(\'{MARK}\')%3C/script%3E')
        self.assert_inert(body_text(response), '404 page', 'path')

    def test_templates_do_not_disable_escaping_for_unsanitised_fields(self):
        import re
        from .base import REPO
        offenders = []
        for path in (REPO / 'templates').glob('*.html'):
            source = path.read_text(encoding='utf-8')
            if '|safe' in source:
                offenders.append(f'{path.name}: |safe')
            for block in re.findall(r'\{% autoescape off %\}(.*?)\{% endautoescape %\}', source, re.S):
                if '|striptags' not in block:
                    offenders.append(f'{path.name}: autoescape off without striptags')
        self.assertEqual(offenders, [], f'escaping is disabled for user-controlled fields: {offenders}')


PAGES = {'index': '/', 'article': '/article/public/', 'login': '/login/', 'category': '/category/root/'}
HEADERS = {
    'content_security_policy': 'Content-Security-Policy',
    'x_content_type_options': 'X-Content-Type-Options',
    'x_frame_options': 'X-Frame-Options',
    'referrer_policy': 'Referrer-Policy',
}


class BrowserSideDefences(SecBase):
    pass


for _hname, _header in HEADERS.items():
    @add_cases(BrowserSideDefences, f'{_hname}_header_present', PAGES)
    def _header_present(self, url, _header=_header):
        response = self.make_client().get(url, secure=True)
        self.assertIn(_header, response, f'{url}: no {_header} header in the response')


class HeaderValues(SecBase):
    def test_nosniff_value(self):
        self.assertEqual(self.make_client().get('/', secure=True)['X-Content-Type-Options'], 'nosniff')

    def test_frame_options_value(self):
        self.assertIn(self.make_client().get('/', secure=True)['X-Frame-Options'], ('DENY', 'SAMEORIGIN'))

    def test_csp_blocks_inline_script_and_foreign_origins(self):
        policy = self.make_client().get('/', secure=True).get('Content-Security-Policy', '')
        self.assertTrue(policy and "'unsafe-inline'" not in policy.split('script-src')[-1].split(';')[0],
                        f'CSP missing or allows unsafe-inline scripts: {policy!r}')

    def test_error_pages_also_carry_security_headers(self):
        response = self.make_client().get('/definitely-missing/', secure=True)
        self.assertIn('X-Content-Type-Options', response)


# CSP needs nonces for every inline script and a browser smoke test of the editor pages: deferred.
known_open(BrowserSideDefences, 'test_content_security_policy')
known_open(HeaderValues, 'test_csp_blocks')
