"""A. CSRF: token enforcement, state changes over GET, cookie settings, templates, exemptions."""
import re

from django.test import Client
from django.urls import reverse, resolve

from .base import REPO, SecBase, add_cases, prod_setting, tracked_files

ATTACKER_SECRET = 'a' * 32
BAD_TOKEN = 'z' * 32

POST_ENDPOINTS = {key: key for key in (
    SecBase.EDITOR_POSTS + SecBase.PUBLIC_POSTS)}
GET_ENDPOINTS = {key: key for key in (SecBase.EDITOR_PAGES + SecBase.EDITOR_GET_DELETES)}


class CsrfTokenEnforcement(SecBase):
    def actor(self, key):
        return None if key in self.PUBLIC_POSTS else self.editor_user

    def post_form(self, client, key, token=None, header_token=None):
        extra = {'HTTP_X_CSRFTOKEN': header_token} if header_token else {}
        data = self.data(key)
        if token is not None and isinstance(data, dict):
            data = {**data, 'csrfmiddlewaretoken': token}
        client.cookies['csrftoken'] = ATTACKER_SECRET
        if key in self.JSON_POSTS:
            return client.post(self.url(key), data=data, content_type='application/json', **extra)
        return client.post(self.url(key), data=data, **extra)


@add_cases(CsrfTokenEnforcement, 'post_without_token_is_rejected', POST_ENDPOINTS)
def _no_token(self, key):
    client = self.make_client(self.actor(key), csrf=True)
    before = self.snapshot()
    response = self.send(client, key)
    self.assertEqual(response.status_code, 403, f'{key}: POST without a CSRF token got {response.status_code}, expected 403')
    self.assertEqual(self.snapshot(), before, f'{key}: data changed although the request had no CSRF token')


@add_cases(CsrfTokenEnforcement, 'post_with_wrong_token_is_rejected', POST_ENDPOINTS)
def _wrong_token(self, key):
    client = self.make_client(self.actor(key), csrf=True)
    before = self.snapshot()
    header = BAD_TOKEN if key in self.JSON_POSTS else None
    response = self.post_form(client, key, token=BAD_TOKEN, header_token=header)
    self.assertEqual(response.status_code, 403, f'{key}: a wrong CSRF token was accepted ({response.status_code})')
    self.assertEqual(self.snapshot(), before, f'{key}: data changed with a wrong CSRF token')


class CsrfOriginChecks(SecBase):
    def valid_token_client(self):
        client = self.make_client(self.editor_user, csrf=True)
        client.get(reverse('login'), secure=True)
        return client, client.cookies['csrftoken'].value

    def test_cross_origin_post_over_https_is_rejected(self):
        client, token = self.valid_token_client()
        response = client.post(reverse('create_category'), {'name_ua': 'X', 'name_en': 'X', 'csrfmiddlewaretoken': token},
                               secure=True, HTTP_ORIGIN='https://evil.example')
        self.assertEqual(response.status_code, 403, 'a POST with a foreign Origin header was accepted')

    def test_foreign_referer_over_https_is_rejected(self):
        client, token = self.valid_token_client()
        response = client.post(reverse('create_category'), {'name_ua': 'X', 'name_en': 'X', 'csrfmiddlewaretoken': token},
                               secure=True, HTTP_REFERER='https://evil.example/page')
        self.assertEqual(response.status_code, 403, 'a POST with a foreign Referer was accepted over HTTPS')

    def test_missing_referer_over_https_is_rejected(self):
        client, token = self.valid_token_client()
        response = client.post(reverse('create_category'), {'name_ua': 'X', 'name_en': 'X', 'csrfmiddlewaretoken': token},
                               secure=True)
        self.assertEqual(response.status_code, 403, 'an HTTPS POST without Referer/Origin was accepted')

    def test_same_origin_post_still_works(self):
        client, token = self.valid_token_client()
        response = client.post(reverse('create_category'), {'name_ua': 'X', 'name_en': 'X', 'csrfmiddlewaretoken': token},
                               secure=True, HTTP_ORIGIN='https://testserver')
        self.assertEqual(response.status_code, 302, 'baseline: a legitimate same-origin POST must succeed')

    def test_trusted_origins_are_not_wildcards(self):
        for origin in prod_setting('CSRF_TRUSTED_ORIGINS'):
            with self.subTest(origin=origin):
                self.assertTrue(origin.startswith('https://') and '*' not in origin,
                                f'CSRF_TRUSTED_ORIGINS contains a weak entry: {origin}')


class CsrfCookieAndSession(SecBase):
    def test_csrf_cookie_has_secure_flag(self):
        self.assertTrue(prod_setting('CSRF_COOKIE_SECURE'),
                        'CSRF_COOKIE_SECURE is not enabled: the token cookie is also sent over plain HTTP (anarchia/settings.py)')

    def test_csrf_cookie_samesite(self):
        self.assertIn(prod_setting('CSRF_COOKIE_SAMESITE'), ('Lax', 'Strict'), 'CSRF cookie lacks SameSite=Lax/Strict')

    def test_csrf_cookie_is_actually_set_with_samesite_in_response(self):
        response = Client().get(reverse('login'))
        self.assertEqual(response.cookies['csrftoken']['samesite'], 'Lax')

    def test_token_is_rotated_on_login(self):
        client = self.make_client(csrf=True)
        client.get(reverse('login'))
        before = client.cookies['csrftoken'].value
        client.post(reverse('login'), {'login': 'editor', 'password': 'S3cure-passw0rd!', 'csrfmiddlewaretoken': before})
        client.get(reverse('login'))
        self.assertNotEqual(client.cookies['csrftoken'].value, before, 'CSRF token survives login (no rotation)')

    def test_csrf_token_is_bound_to_the_session(self):
        # Cookie tossing from a sibling subdomain: attacker plants a known csrftoken cookie
        # and submits a form with the matching token on behalf of a logged-in editor.
        client = self.make_client(self.editor_user, csrf=True)
        client.cookies['csrftoken'] = ATTACKER_SECRET
        response = client.post(reverse('create_category'),
                               {'name_ua': 'Planted', 'name_en': 'Planted', 'csrfmiddlewaretoken': ATTACKER_SECRET})
        self.assertEqual(response.status_code, 403,
                         'an attacker-chosen CSRF cookie/token pair is accepted for an authenticated session '
                         '(token is not bound to the session; set CSRF_USE_SESSIONS=True)')


class GetNeverChangesState(SecBase):
    PUBLIC_GETS = {
        'index': '/', 'about_us': '/about-us', 'authors': '/authors', 'author_detail': '/authors/author',
        'all_articles': '/all', 'category': '/category/root/', 'article': '/article/public/',
        'search': '/search/?q=body', 'feed': '/feed/', 'sitemap': '/sitemap.xml', 'login': '/login/',
        'comment_get': '/comment',
    }


@add_cases(GetNeverChangesState, 'public_get_is_read_only', GetNeverChangesState.PUBLIC_GETS)
def _public_get(self, url):
    before = self.snapshot()
    self.make_client().get(url)
    self.assertEqual(self.snapshot(), before, f'GET {url} modified data')


@add_cases(GetNeverChangesState, 'editor_get_is_read_only', GET_ENDPOINTS)
def _editor_get(self, key):
    before = self.snapshot()
    self.send(self.make_client(self.editor_user), key, 'get')
    self.assertEqual(self.snapshot(), before,
                     f'GET {self.url(key)} changed data: state changes must use POST/DELETE with a CSRF token')


@add_cases(GetNeverChangesState, 'cross_site_get_cannot_delete', {k: k for k in SecBase.EDITOR_GET_DELETES})
def _cross_site_delete(self, key):
    before = self.snapshot()
    self.send(self.make_client(self.editor_user), key, 'get',
              HTTP_REFERER='https://evil.example/page.html', HTTP_SEC_FETCH_SITE='cross-site', HTTP_SEC_FETCH_DEST='image')
    self.assertEqual(self.snapshot(), before,
                     f'a cross-site <img src="{self.url(key)}"> deletes data for a logged-in editor')


class CsrfExemptions(SecBase):
    def test_project_code_has_no_csrf_exempt(self):
        offenders = []
        for rel in tracked_files():
            if rel.endswith('.py') and rel.startswith(('app/', 'anarchia/')) and 'security_tests' not in rel \
                    and not rel.endswith(('test_findings.py', 'settings_test.py')):
                if 'csrf_exempt' in (REPO / rel).read_text(encoding='utf-8', errors='ignore'):
                    offenders.append(rel)
        self.assertEqual(offenders, [], f'csrf_exempt found in: {offenders}')

    def test_no_installed_state_changing_route_is_csrf_exempt(self):
        exempt = []
        for name in ('ckeditor_upload', 'login', 'comment', 'set_language', 'publish'):
            match = resolve(reverse(name))
            if getattr(match.func, 'csrf_exempt', False):
                exempt.append(f'{name} -> {match.func.__module__}')
        self.assertEqual(exempt, [], f'CSRF-exempt endpoints reachable by a logged-in staff user: {exempt}')

    def test_language_form_requires_token(self):
        response = self.make_client(csrf=True).post(reverse('set_language'), {'language': 'en', 'next': '/'})
        self.assertEqual(response.status_code, 403)

    def test_json_endpoint_rejects_text_plain_cross_site_form(self):
        client = self.make_client(self.editor_user, csrf=True)
        response = client.post(reverse('update_category_order'), data='[]', content_type='text/plain')
        self.assertEqual(response.status_code, 403, 'JSON endpoint processed a CSRF-able text/plain request')


def _post_forms_in_templates():
    cases = {}
    for path in sorted((REPO / 'templates').glob('*.html')):
        source = path.read_text(encoding='utf-8')
        forms = re.findall(r'<form\b([^>]*)>(.*?)</form>', source, re.S | re.I)
        posts = [(attrs, body) for attrs, body in forms if re.search(r'method\s*=\s*["\']?post', attrs, re.I)]
        if posts:
            cases[path.stem.replace('-', '_')] = (path.name, posts)
    return cases


class TemplateForms(SecBase):
    pass


@add_cases(TemplateForms, 'every_post_form_has_csrf_token', _post_forms_in_templates())
def _forms_have_token(self, case):
    name, posts = case
    for attrs, body in posts:
        with self.subTest(form=attrs.strip()[:60]):
            self.assertIn('{% csrf_token %}', body, f'{name}: POST form without {{% csrf_token %}}: <form {attrs.strip()[:80]}>')
            self.assertNotRegex(attrs, r'action\s*=\s*["\']?https?://', f'{name}: form posts to an external URL')
