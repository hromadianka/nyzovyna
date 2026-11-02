import json
import re
import uuid
from collections import deque
from urllib.parse import urldefrag, urlparse

from django.test import Client, TestCase
from django.urls import NoReverseMatch, get_resolver, reverse
from hypothesis import HealthCheck, given, settings, strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from .helpers import TEST_PASSWORD, make_editor, BASE_DIR, TEMPLATES_DIR, Base, captcha_ok, db_fingerprint, html_of, mk_article, mk_author, seed_site

DUMMY = str(uuid.UUID(int=7))
FUZZ = settings(max_examples=60, derandomize=True, deadline=None, suppress_health_check=list(HealthCheck))

PUBLIC_URLS = ['/', '/all', '/about-us', '/authors', '/authors/author-1', '/category/root/', '/category/child/',
               '/article/seed-0/', '/search/', '/search/?q=Title', '/feed/', '/sitemap.xml', '/login/']
GET_ONLY_PUBLIC = [u for u in PUBLIC_URLS if u != '/login/']


def top_level_names():
    names = {}
    for pattern in get_resolver().url_patterns:
        name = getattr(pattern, 'name', None)
        if name:
            names[name] = pattern
    return names


def dummy_args(pattern):
    from django.urls.converters import UUIDConverter
    return [DUMMY if isinstance(conv, UUIDConverter) else 'a-slug-1' for conv in pattern.pattern.converters.values()]


def template_url_tags():
    found = []
    for path in sorted(TEMPLATES_DIR.glob('*.html')):
        text = path.read_text(encoding='utf-8-sig')
        for match in re.finditer(r"{%\s*url\s+(['\"])([\w:-]+)\1([^%]*)%}", text):
            tail = re.sub(r'\bas\s+\w+\s*$', '', match.group(3).strip())
            found.append((path.name, match.group(2), len(tail.split()) if tail else 0))
    return found


def python_reverse_calls():
    found = []
    for path in sorted((BASE_DIR / 'app').glob('*.py')):
        if path.name.startswith('test'):
            continue
        text = path.read_text(encoding='utf-8-sig')
        for match in re.finditer(r"\b(reverse|reverse_lazy|redirect)\(\s*'([\w:-]+)'(.*?)\)", text):
            if '/' in match.group(2):
                continue
            tail = match.group(3)
            kwargs = len([k for k in re.findall(r'\b(\w+)=', tail) if k != 'permanent'])
            args_match = re.search(r'args=\[(.*?)\]', tail)
            positional = 0 if kwargs and not args_match else (len(args_match.group(1).split(',')) if args_match else 0)
            found.append((path.name, match.group(2), kwargs or positional, bool(kwargs and not args_match)))
    return found


class UrlContractTests(TestCase):
    def test_every_named_url_reverses_with_valid_arguments(self):
        for name, pattern in top_level_names().items():
            with self.subTest(name=name):
                url = reverse(name, args=dummy_args(pattern))
                self.assertTrue(url.startswith('/'))

    def test_every_named_url_rejects_wrong_argument_count(self):
        for name, pattern in top_level_names().items():
            expected = len(pattern.pattern.converters)
            with self.subTest(name=name):
                with self.assertRaises(NoReverseMatch):
                    reverse(name, args=[DUMMY] * (expected + 1))

    def test_template_url_tags_reference_existing_names(self):
        names = top_level_names()
        for template, name, argc in template_url_tags():
            if ':' in name:
                continue
            with self.subTest(template=template, name=name):
                self.assertIn(name, names)

    def test_template_url_tags_pass_correct_argument_count(self):
        names = top_level_names()
        for template, name, argc in template_url_tags():
            if name not in names:
                continue
            with self.subTest(template=template, name=name, argc=argc):
                self.assertEqual(argc, len(names[name].pattern.converters))

    def test_template_url_tags_exist(self):
        self.assertGreater(len(template_url_tags()), 20)

    def test_python_reverse_and_redirect_use_existing_names(self):
        names = top_level_names()
        for module, name, argc, kw in python_reverse_calls():
            with self.subTest(module=module, name=name):
                self.assertIn(name, names)

    def test_python_reverse_and_redirect_argument_counts(self):
        names = top_level_names()
        for module, name, argc, kw in python_reverse_calls():
            if name in names:
                with self.subTest(module=module, name=name):
                    self.assertEqual(argc, len(names[name].pattern.converters))

    def test_url_names_are_unique(self):
        seen = [getattr(p, 'name', None) for p in get_resolver().url_patterns]
        seen = [n for n in seen if n]
        self.assertEqual(len(seen), len(set(seen)))

    def test_every_route_is_reachable(self):
        for name, pattern in top_level_names().items():
            args = dummy_args(pattern)
            url = reverse(name, args=args)
            with self.subTest(name=name):
                self.assertEqual(get_resolver().resolve(url).url_name, name)

    def test_uuid_article_url_reaches_its_own_view(self):
        from django.urls import resolve
        self.assertEqual(resolve(f'/article/{DUMMY}/').url_name, 'article_by_id')


    def test_trailing_slash_consistency(self):
        urls = [reverse(n, args=dummy_args(p)) for n, p in top_level_names().items()]
        mixed = {u.endswith('/') for u in urls if u != '/'}
        self.assertEqual(len(mixed), 1)

    def test_sitemap_and_feed_urls_exist(self):
        self.assertEqual(reverse('sitemap'), '/sitemap.xml')
        self.assertEqual(reverse('post_feed'), '/feed/')

    def test_login_url_setting_points_to_real_route(self):
        from django.conf import settings as s
        from django.shortcuts import resolve_url
        self.assertEqual(self.client.get(resolve_url(s.LOGIN_URL), follow=True).status_code, 200)


class CrawlerTests(Base):
    def crawl(self, start='/', limit=200):
        seen, queue, results = set(), deque([start]), {}
        while queue and len(seen) < limit:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            response = self.client.get(url)
            results[url] = response
            if response.status_code != 200 or 'text/html' not in response['Content-Type']:
                continue
            html = html_of(response)
            for href in re.findall(r'<a\b[^>]*?\bhref="([^"]*)"', html):
                href, _ = urldefrag(href)
                parsed = urlparse(href)
                if parsed.scheme or parsed.netloc or not href or href.startswith(('/static', '/media')):
                    continue
                queue.append(href)
        return results

    def seed_with_comments(self):
        root, child, author, arts = seed_site(5)
        from .helpers import mk_comment
        parent = mk_comment(arts[0])
        mk_comment(arts[0], parent=parent)
        return arts

    def test_crawl_from_home_finds_no_errors(self):
        self.seed_with_comments()
        results = self.crawl()
        self.assertGreater(len(results), 10)
        for url, response in results.items():
            with self.subTest(url=url):
                self.assertLess(response.status_code, 400, url)

    def test_crawl_english_interface_finds_no_errors(self):
        self.seed_with_comments()
        self.client.cookies['django_language'] = 'en'
        for url, response in self.crawl().items():
            with self.subTest(url=url):
                self.assertLess(response.status_code, 400, url)

    def test_crawl_with_cyrillic_content_finds_no_errors(self):
        from app.models import Category
        root, child, author, arts = seed_site(3)
        Category.objects.create(name_ua='Політика', name_en='Politics', parent=root)
        for url, response in self.crawl().items():
            with self.subTest(url=url):
                self.assertLess(response.status_code, 400, url)

    def test_anchor_targets_exist_on_every_page(self):
        arts = self.seed_with_comments()
        for url in ['/', '/all', '/article/seed-0/', '/authors', '/about-us']:
            html = html_of(self.get_ok(url))
            for anchor in set(re.findall(r'href="#([^"]+)"', html)):
                with self.subTest(url=url, anchor=anchor):
                    self.assertIn(f'id="{anchor}"', html)

    def test_no_internal_link_is_empty_or_javascript_void(self):
        self.seed_with_comments()
        for url in ['/', '/article/seed-0/', '/category/root/']:
            html = html_of(self.get_ok(url))
            for href in re.findall(r'<a\b[^>]*?\bhref="([^"]*)"', html):
                with self.subTest(url=url, href=href):
                    self.assertNotIn(href.strip().lower(), ('', '#', 'javascript:void(0)'))

    def test_every_page_links_logo_home_and_search(self):
        self.seed_with_comments()
        for url in [u for u in PUBLIC_URLS if u not in ('/feed/', '/sitemap.xml')]:
            html = html_of(self.client.get(url))
            with self.subTest(url=url):
                self.assertIn('href="/"', html)
                self.assertIn('action="/search/"', html)

    def test_all_static_assets_referenced_by_templates_exist(self):
        from django.contrib.staticfiles import finders
        for path in sorted(TEMPLATES_DIR.glob('*.html')):
            text = path.read_text(encoding='utf-8-sig')
            for ref in re.findall(r"{%\s*static\s+'([^']+)'", text) + re.findall(r"/static/([\w./-]+)", text):
                with self.subTest(template=path.name, ref=ref):
                    self.assertIsNotNone(finders.find(ref))

    def test_all_static_assets_referenced_by_css_exist(self):
        from django.contrib.staticfiles import finders
        css = (BASE_DIR / 'static' / 'style.css').read_text(encoding='utf-8')
        for ref in set(re.findall(r"url\(['\"]?(?!data:|http|//)([^'\")]+)['\"]?\)", css)):
            with self.subTest(ref=ref):
                self.assertIsNotNone(finders.find(ref.lstrip('/').replace('static/', '', 1).replace('../', '')), ref)


class SafeMethodTests(Base):
    def setUp(self):
        super().setUp()
        seed_site(4)

    def test_get_does_not_change_state_except_article_counter(self):
        for url in PUBLIC_URLS:
            if url.startswith('/article/'):
                continue
            before = db_fingerprint()
            self.client.get(url)
            with self.subTest(url=url):
                self.assertEqual(before, db_fingerprint())

    def test_head_does_not_change_state(self):
        for url in PUBLIC_URLS:
            before = db_fingerprint()
            self.client.head(url)
            with self.subTest(url=url):
                self.assertEqual(before, db_fingerprint())

    def test_options_does_not_change_state(self):
        for url in PUBLIC_URLS:
            before = db_fingerprint()
            self.client.options(url)
            with self.subTest(url=url):
                self.assertEqual(before, db_fingerprint())

    def test_head_responses_have_no_body_and_ok_status(self):
        for url in PUBLIC_URLS:
            with self.subTest(url=url):
                response = self.client.head(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, b'')

    def test_options_is_answered_without_server_error(self):
        for url in PUBLIC_URLS:
            with self.subTest(url=url):
                self.assertLess(self.client.options(url).status_code, 500)

    def test_get_is_idempotent_for_content(self):
        for url in ['/', '/all', '/authors', '/category/root/', '/search/?q=Title', '/about-us']:
            first = re.sub(rb'csrfmiddlewaretoken" value="[^"]+"', b'', self.client.get(url).content)
            second = re.sub(rb'csrfmiddlewaretoken" value="[^"]+"', b'', self.client.get(url).content)
            with self.subTest(url=url):
                self.assertEqual(first, second)

    def test_prefetch_style_requests_do_not_count_views(self):
        article = mk_article('pf')
        self.client.get('/article/pf/', HTTP_PURPOSE='prefetch')
        self.client.get('/article/pf/', HTTP_SEC_PURPOSE='prefetch')
        article.refresh_from_db()
        self.assertEqual(article.views, 0)

    def test_crawler_user_agents_do_not_count_views(self):
        article = mk_article('bots')
        for ua in ['Googlebot/2.1', 'bingbot/2.0', 'AhrefsBot', 'curl/8.0', 'Mozilla/5.0 (compatible; YandexBot/3.0)']:
            self.client.get('/article/bots/', HTTP_USER_AGENT=ua)
        article.refresh_from_db()
        self.assertEqual(article.views, 0)

    def test_repeated_refresh_by_same_visitor_counts_once(self):
        article = mk_article('refresh')
        for _ in range(5):
            self.client.get('/article/refresh/', HTTP_USER_AGENT='Mozilla/5.0')
        article.refresh_from_db()
        self.assertEqual(article.views, 1)


class StatusCodeTests(Base):
    def setUp(self):
        super().setUp()
        seed_site(3)

    def test_wrong_method_on_read_only_public_pages_is_405(self):
        for url in GET_ONLY_PUBLIC:
            for method in ['post', 'put', 'patch', 'delete']:
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 405)

    def test_get_on_post_only_endpoints_is_405(self):
        self.login()
        for url in ['/create-category/', '/create_new_author/', '/about-us-edit']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_post_only_endpoints_reject_other_methods(self):
        self.login()
        for url in ['/create-category/', '/create_new_author/', '/about-us-edit', '/comment',
                    '/editor-cabinet/categories/order/update/']:
            for method in ['put', 'delete', 'patch']:
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 405)

    def test_unknown_resources_are_404(self):
        for url in ['/article/nope/', '/category/nope/', '/authors/nope', '/no/such/page', '/article/nope/edit/',
                    '/authors/nope/edit']:
            with self.subTest(url=url):
                self.login('u' + str(abs(hash(url)))[:6]) if 'edit' in url else None
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_unknown_resources_with_every_public_method_are_404_not_500(self):
        for method in ['get', 'head', 'options', 'post']:
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)('/article/nope/').status_code, 404 if method != 'options' else 404)

    def test_malformed_percent_encoding_is_not_500(self):
        for url in ['/search/?q=%', '/search/?q=%ZZ', '/category/%E0%A4%A/', '/article/%00/', '/%ff']:
            with self.subTest(url=url):
                self.assertLess(self.client.get(url).status_code, 500)

    def test_huge_query_string_is_not_500(self):
        self.assertLess(self.client.get('/search/?q=' + 'a' * 100_000).status_code, 500)

    def test_null_byte_in_query_is_not_500(self):
        self.assertLess(self.client.get('/search/?q=a%00b').status_code, 500)

    def test_duplicate_query_parameters_are_not_500(self):
        self.assertLess(self.client.get('/search/?q=a&q=b&q=').status_code, 500)

    def test_unicode_slug_in_url_is_404_not_500(self):
        for url in ['/article/привіт/', '/category/політика/', '/authors/іван']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_extremely_long_slug_is_404_not_500(self):
        for url in [f'/article/{"a" * 5000}/', f'/category/{"a" * 5000}/']:
            with self.subTest(url=url[:30]):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_set_language_garbage_is_not_500(self):
        for payload in [{}, {'language': ''}, {'language': 'xx'}, {'language': 'en', 'next': 'http://evil.example/'},
                        {'language': 'en', 'next': '//evil.example'}, {'language': 'en', 'next': 'javascript:alert(1)'}]:
            with self.subTest(payload=payload):
                response = self.client.post('/set-language/', payload)
                self.assertLess(response.status_code, 500)
                self.assertNotIn('evil', response.get('Location', ''))

    def test_set_language_invalid_code_does_not_poison_cookie(self):
        response = self.client.post('/set-language/', {'language': 'xx'})
        self.assertNotEqual(response.cookies.get('django_language') and response.cookies['django_language'].value, 'xx')


class FuzzTests(HypothesisTestCase):
    @property
    def client(self):
        if '_fuzz_client' not in self.__dict__:
            self.__dict__['_fuzz_client'] = Client(raise_request_exception=False)
        return self.__dict__['_fuzz_client']

    @client.setter
    def client(self, value):
        pass

    @FUZZ
    @given(st.text(max_size=200))
    def test_fuzz_search_query(self, q):
        self.assertLess(self.client.get('/search/', {'q': q}).status_code, 500)

    @FUZZ
    @given(st.text(max_size=200), st.text(max_size=300))
    def test_fuzz_comment_form(self, author, text):
        article = mk_article('fz')
        with captcha_ok():
            response = self.client.post('/comment', {'article_id': str(article.id), 'author': author, 'text': text})
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.text(max_size=60), st.text(max_size=60))
    def test_fuzz_comment_ids(self, article_id, parent_id):
        mk_article('fz0')
        response = self.client.post('/comment', {'article_id': article_id, 'parent_comment_id': parent_id,
                                                 'author': 'a', 'text': 't'})
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.text(max_size=30), st.text(max_size=100))
    def test_fuzz_set_language(self, language, nxt):
        self.assertLess(self.client.post('/set-language/', {'language': language, 'next': nxt}).status_code, 500)

    @FUZZ
    @given(st.text(max_size=30), st.text(max_size=30))
    def test_fuzz_login(self, login, password):
        self.assertLess(self.client.post('/login/', {'login': login, 'password': password}).status_code, 500)

    @FUZZ
    @given(st.binary(max_size=200))
    def test_fuzz_category_order_body(self, body):
        self.login_editor()
        response = self.client.post('/editor-cabinet/categories/order/update/', data=body,
                                    content_type='application/json')
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.one_of(st.none(), st.integers(), st.text(max_size=20),
                     st.lists(st.dictionaries(st.sampled_from(['id', 'order']), st.one_of(st.text(max_size=40), st.integers(), st.none())), max_size=3)))
    def test_fuzz_category_order_json(self, payload):
        self.login_editor()
        response = self.client.post('/editor-cabinet/categories/order/update/', data=json.dumps(payload),
                                    content_type='application/json')
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.text(max_size=40), st.text(max_size=40), st.text(max_size=40), st.text(max_size=30), st.text(max_size=30))
    def test_fuzz_publish_form(self, name, text, language, option, when):
        self.login_editor()
        author = mk_author('fzauthor')
        response = self.client.post('/publish', {'article_name': name, 'article_text': text, 'language': language,
                                                 'article_author': str(author.id), 'publish_option': option,
                                                 'publish_datetime': when})
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.text(max_size=40), st.text(max_size=40))
    def test_fuzz_create_category(self, ua, en):
        self.login_editor()
        self.assertLess(self.client.post('/create-category/', {'name_ua': ua, 'name_en': en}).status_code, 500)

    @FUZZ
    @given(st.text(max_size=40), st.text(max_size=40))
    def test_fuzz_create_author(self, ua, en):
        self.login_editor()
        response = self.client.post('/create_new_author/', {'author_name_ua': ua, 'author_name_en': en,
                                                            'author_description_ua': 'd', 'author_description_en': 'd'})
        self.assertLess(response.status_code, 500)

    @FUZZ
    @given(st.text(alphabet=st.characters(blacklist_categories=('Cs',)), max_size=80))
    def test_fuzz_arbitrary_path_never_500(self, path):
        from urllib.parse import quote
        self.assertLess(self.client.get('/' + quote(path)).status_code, 500)

    def login_editor(self):
        from django.contrib.auth.models import User
        if not User.objects.filter(username='fuzz').exists():
            make_editor('fuzz', TEST_PASSWORD)
        self.client.login(username='fuzz', password=TEST_PASSWORD)
