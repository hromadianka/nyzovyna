"""B. Authentication, authorization (broken access control / IDOR), login hardening, sessions."""
import re
from unittest import mock
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core import signing
from django.test import override_settings
from django.urls import NoReverseMatch, reverse

from app.models import Article, Comment

from .base import PASSWORD, REPO, SecBase, add_cases, prod_setting, prod_settings

PAGES = {k: k for k in SecBase.EDITOR_PAGES + SecBase.EDITOR_GET_DELETES + ['about_us_edit']}
POSTS = {k: k for k in SecBase.EDITOR_POSTS}
ALL_PRIVILEGED = {**{f'get_{k}': (k, 'get') for k in PAGES},
                  **{f'post_{k}': (k, 'post') for k in POSTS}}
# GET of about_us_edit has no template (see group D); the access check is still meaningful, the baseline is not.
BASELINE = {name: spec for name, spec in ALL_PRIVILEGED.items() if name not in ('get_about_us_edit', 'get_delete_article', 'get_delete_category')}


class PrivilegedAccess(SecBase):
    def request(self, user, key, method):
        return self.send(self.make_client(user), key, method)


@add_cases(PrivilegedAccess, 'anonymous_is_redirected_to_a_working_login', ALL_PRIVILEGED)
def _anon(self, spec):
    key, method = spec
    before = self.snapshot()
    response = self.request(None, key, method)
    self.assertEqual(response.status_code, 302, f'{method.upper()} {self.url(key)} anonymous -> {response.status_code}, expected redirect to login')
    followed = self.make_client().get(response['Location'], follow=True)
    self.assertEqual(followed.status_code, 200,
                     f'login redirect {response["Location"]!r} for {self.url(key)} does not lead to a working login page '
                     f'({followed.status_code}); LOGIN_URL is not configured')
    self.assertEqual(self.snapshot(), before, f'anonymous {method.upper()} {self.url(key)} changed data')


@add_cases(PrivilegedAccess, 'regular_user_without_editor_role_is_forbidden', ALL_PRIVILEGED)
def _regular(self, spec):
    key, method = spec
    before = self.snapshot()
    response = self.request(self.regular_user, key, method)
    self.assertEqual(response.status_code, 403,
                     f'{method.upper()} {self.url(key)}: a logged-in user WITHOUT an Editor record got {response.status_code}; '
                     f'views are guarded by @login_required only (app/views.py), the Editor model is never checked')
    self.assertEqual(self.snapshot(), before, f'a non-editor changed data through {self.url(key)}')


@add_cases(PrivilegedAccess, 'editor_baseline_works', BASELINE)
def _editor(self, spec):
    key, method = spec
    response = self.request(self.editor_user, key, method)
    self.assertIn(response.status_code, (200, 302), f'{method.upper()} {self.url(key)} as editor -> {response.status_code}')


class RoleEscalation(SecBase):
    def test_regular_user_cannot_delete_article(self):
        self.make_client(self.regular_user).get(self.url('delete_article'))
        self.assertTrue(Article.objects.filter(slug='public').exists(), 'a non-editor deleted an article')

    def test_regular_user_cannot_rewrite_article(self):
        data = {**self.data('edit_article'), 'article_name': 'DEFACED'}
        self.make_client(self.regular_user).post(self.url('edit_article'), data)
        self.assertNotEqual(Article.objects.get(pk=self.article.pk).name, 'DEFACED', 'a non-editor rewrote an article')

    def test_regular_user_cannot_delete_comments(self):
        self.make_client(self.regular_user).post(self.url('delete_comment'))
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists(), 'a non-editor moderated comments')

    def test_regular_user_can_not_read_unpublished_list(self):
        response = self.make_client(self.regular_user).get(self.url('editor_cabinet'))
        self.assertNotContains(response, 'SECRET DRAFT TITLE', status_code=response.status_code)

    def test_deactivated_editor_loses_access(self):
        client = self.make_client(self.editor_user)
        User.objects.filter(pk=self.editor_user.pk).update(is_active=False)
        self.assertEqual(client.get(self.url('editor_cabinet')).status_code, 302)

    def test_comment_reply_cannot_attach_to_a_comment_of_another_article(self):
        other = self.make_article('other', 'Other', 'other body')
        data = {**self.data('comment_reply'), 'article_id': str(other.id)}
        self.make_client().post(self.url('comment_reply'), data)
        cross = Comment.objects.filter(article=other, parent_comment=self.comment)
        self.assertFalse(cross.exists(), 'a reply is stored under article B but threaded under a comment of article A (no ownership check)')


class LoginHardening(SecBase):
    def attempt(self, client, password, username='editor'):
        return client.post(reverse('login'), {'login': username, 'password': password})

    def error_text(self, response):
        return ' '.join(m.message for m in response.context['messages'])

    def test_login_is_throttled_after_repeated_failures(self):
        client = self.make_client()
        statuses = [self.attempt(client, f'guess-{i}').status_code for i in range(30)]
        self.assertTrue(any(s in (403, 429) for s in statuses), f'30 wrong passwords in a row were all processed normally: {set(statuses)}')

    def test_correct_password_is_refused_while_locked_out(self):
        client = self.make_client()
        for i in range(30):
            self.attempt(client, f'guess-{i}')
        response = self.attempt(client, PASSWORD)
        self.assertNotEqual(response.status_code, 302, 'after 30 failures the account/IP is not locked: brute force succeeds')

    def test_admin_login_is_throttled(self):
        client = self.make_client()
        for i in range(30):
            client.post('/admin/login/?next=/admin/', {'username': 'staffer', 'password': f'guess-{i}', 'next': '/admin/'})
        response = client.post('/admin/login/?next=/admin/', {'username': 'staffer', 'password': PASSWORD, 'next': '/admin/'})
        self.assertNotEqual(response.status_code, 302, '/admin/login/ has no throttling: 30 failures then the right password works')

    def test_unknown_and_known_user_get_identical_responses(self):
        client = self.make_client()
        known = self.attempt(client, 'wrong')
        unknown = self.attempt(client, 'wrong', username='no-such-user')
        self.assertEqual((known.status_code, self.error_text(known)), (unknown.status_code, self.error_text(unknown)),
                         'login errors differ between existing and non-existing accounts (user enumeration)')

    def test_deactivated_account_is_indistinguishable(self):
        User.objects.filter(pk=self.regular_user.pk).update(is_active=False)
        client = self.make_client()
        disabled = self.attempt(client, PASSWORD, username='reader')
        wrong = self.attempt(client, 'wrong')
        self.assertEqual(self.error_text(disabled), self.error_text(wrong))

    def test_password_hasher_runs_for_unknown_user_to_equalise_timing(self):
        with mock.patch.object(User, 'set_password') as dummy:
            self.attempt(self.make_client(), 'x', username='no-such-user')
        self.assertTrue(dummy.called, 'no dummy password hash for unknown users: response time reveals which logins exist')

    def test_failed_login_does_not_echo_password(self):
        response = self.attempt(self.make_client(), 'my-secret-guess')
        self.assertNotContains(response, 'my-secret-guess')

    def test_login_ignores_external_next_parameter(self):
        for nxt in ('https://evil.example/', '//evil.example', '/\\evil.example', 'javascript:alert(1)'):
            with self.subTest(next=nxt):
                response = self.make_client().post(f'{reverse("login")}?next={nxt}',
                                                   {'login': 'editor', 'password': PASSWORD, 'next': nxt})
                self.assertEqual(response.status_code, 302)
                self.assertNotIn('evil', response['Location'], f'login redirects to attacker-controlled next={nxt}')

    def test_login_required_redirect_carries_local_next_only(self):
        response = self.make_client().get(reverse('editor_cabinet'))
        self.assertEqual(urlparse(response['Location']).netloc, '')

    def test_login_with_correct_password_works_baseline(self):
        response = self.attempt(self.make_client(), PASSWORD)
        self.assertRedirects(response, reverse('editor_cabinet'), fetch_redirect_response=False)


class OpenRedirects(SecBase):
    NEXT_VALUES = {
        'absolute': 'https://evil.example/', 'scheme_relative': '//evil.example/', 'backslash': '/\\evil.example',
        'triple_slash': '///evil.example', 'javascript': 'javascript:alert(1)', 'tab_trick': '/\t/evil.example',
        'no_slashes': 'https:evil.example', 'userinfo': 'https://testserver@evil.example/', 'data': 'data:text/html,x',
    }


@add_cases(OpenRedirects, 'set_language_next_is_local', OpenRedirects.NEXT_VALUES)
def _next(self, value):
    response = self.make_client().post(reverse('set_language'), {'language': 'en', 'next': value})
    location = urlparse(response['Location'])
    self.assertIn(location.netloc, ('', 'testserver'), f'set_language redirects to {response["Location"]!r} for next={value!r}')


class HostHeader(SecBase):
    def test_unknown_host_is_rejected_with_production_allowed_hosts(self):
        with override_settings(ALLOWED_HOSTS=prod_setting('ALLOWED_HOSTS')):
            response = self.make_client().get('/', HTTP_HOST='evil.example')
        self.assertEqual(response.status_code, 400,
                         f'Host: evil.example is accepted; effective ALLOWED_HOSTS={prod_setting("ALLOWED_HOSTS")} '
                         f'(django_heroku.settings() overwrites the list from settings.py with ["*"])')

    def test_host_header_cannot_turn_set_language_into_open_redirect(self):
        with override_settings(ALLOWED_HOSTS=prod_setting('ALLOWED_HOSTS')):
            response = self.make_client().post(reverse('set_language'), {'language': 'en', 'next': 'https://evil.example/x'},
                                               HTTP_HOST='evil.example')
        self.assertNotIn('evil.example', response.get('Location', ''), 'Host-header + set_language gives an open redirect')

    def test_password_reset_style_links_do_not_use_host_header(self):
        response = self.make_client().get('/', HTTP_HOST='testserver')
        self.assertNotContains(response, 'evil.example')


class SessionLifecycle(SecBase):
    def session_cookie(self, client):
        return client.cookies['sessionid'].value

    def test_app_provides_a_logout_route(self):
        try:
            reverse('logout')
        except NoReverseMatch:
            self.fail('no logout route in the editor cabinet: editors cannot end a session (only /admin/logout/ exists)')

    def test_session_is_revoked_server_side_on_logout(self):
        victim = self.make_client(self.staff_user)
        stolen = self.session_cookie(victim)
        victim.post('/admin/logout/')
        attacker = self.make_client()
        attacker.cookies['sessionid'] = stolen
        self.assertEqual(attacker.get(reverse('editor_cabinet')).status_code, 302,
                         'a captured session cookie keeps working after logout (SESSION_ENGINE=signed_cookies cannot be revoked)')

    def test_password_change_invalidates_existing_sessions(self):
        client = self.make_client(self.editor_user)
        self.editor_user.set_password('another-Passw0rd!')
        self.editor_user.save()
        self.assertEqual(client.get(reverse('editor_cabinet')).status_code, 302)

    def test_tampered_session_cookie_is_ignored(self):
        client = self.make_client(self.editor_user)
        cookie = self.session_cookie(client)
        forged = self.make_client()
        forged.cookies['sessionid'] = cookie[:-4] + ('AAAA' if not cookie.endswith('AAAA') else 'BBBB')
        self.assertEqual(forged.get(reverse('editor_cabinet')).status_code, 302)

    def test_session_cannot_be_minted_with_the_secret_key_from_the_repository(self):
        source = (REPO / 'anarchia' / 'settings.py').read_text(encoding='utf-8')
        found = re.search(r"SECRET_KEY\s*=\s*'([^']+)'", source)
        if found is None:
            return
        repo_key = found.group(1)
        payload = {'_auth_user_id': str(self.editor_user.pk),
                   '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend',
                   '_auth_user_hash': self.editor_user.get_session_auth_hash()}
        cookie = signing.dumps(payload, key=repo_key, salt='django.contrib.sessions.backends.signed_cookies',
                               serializer=signing.JSONSerializer, compress=True)
        forged = self.make_client()
        forged.cookies['sessionid'] = cookie
        self.assertEqual(forged.get(reverse('editor_cabinet')).status_code, 302,
                         'anyone holding the committed SECRET_KEY plus a password hash (db.sqlite3 is committed too) can mint an editor session')

    def test_session_cookie_secure_flag_is_configured(self):
        self.assertTrue(prod_setting('SESSION_COOKIE_SECURE'), 'SESSION_COOKIE_SECURE is False: the session cookie travels over HTTP')

    def test_session_cookie_secure_flag_in_real_response(self):
        response = self.make_client().post(reverse('login'), {'login': 'editor', 'password': PASSWORD}, secure=True)
        self.assertTrue(response.cookies['sessionid']['secure'], 'Set-Cookie: sessionid has no Secure attribute')

    def test_session_cookie_is_httponly(self):
        response = self.make_client().post(reverse('login'), {'login': 'editor', 'password': PASSWORD})
        self.assertTrue(response.cookies['sessionid']['httponly'])

    def test_session_cookie_samesite(self):
        response = self.make_client().post(reverse('login'), {'login': 'editor', 'password': PASSWORD})
        self.assertIn(response.cookies['sessionid']['samesite'], ('Lax', 'Strict'))

    def test_session_lifetime_is_at_most_two_weeks(self):
        self.assertLessEqual(prod_setting('SESSION_COOKIE_AGE'), 14 * 24 * 3600)

    def test_login_issues_a_new_session_cookie(self):
        client = self.make_client()
        client.get(reverse('login'))
        before = client.cookies.get('sessionid')
        client.post(reverse('login'), {'login': 'editor', 'password': PASSWORD})
        self.assertNotEqual(getattr(before, 'value', None), client.cookies['sessionid'].value)

    def test_anonymous_session_cookie_does_not_grant_access_after_login_elsewhere(self):
        anon = self.make_client()
        anon.get(reverse('login'))
        self.make_client().post(reverse('login'), {'login': 'editor', 'password': PASSWORD})
        self.assertEqual(anon.get(reverse('editor_cabinet')).status_code, 302)
