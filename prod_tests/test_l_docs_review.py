from unittest import mock

from django.db import OperationalError
from django.test import Client, SimpleTestCase, override_settings

from app.resilience import ResilientLocMemCache

from .helpers import Base, html_of, mk_article, mk_author, seed_site


class MiddlewarePhaseOutageTests(Base):
    def test_database_error_while_saving_the_session_is_a_503(self):
        seed_site(1)
        with mock.patch('django.contrib.sessions.middleware.SessionMiddleware.process_response',
                        side_effect=OperationalError('db down')):
            response = Client(raise_request_exception=False).get('/')
        self.assertEqual(response.status_code, 503)


class CacheBackendContractTests(SimpleTestCase):
    def test_default_timeout_comes_from_the_cache_settings(self):
        cache = ResilientLocMemCache('contract-1', {'TIMEOUT': None})
        cache.set('key', 1)
        cache.add('other', 1)
        self.assertEqual([cache._expire_info[cache.make_key(k)] for k in ('key', 'other')], [None, None])

    def test_clear_and_touch_survive_a_backend_failure(self):
        cache = ResilientLocMemCache('contract-2', {})
        with mock.patch('django.core.cache.backends.locmem.LocMemCache.clear', side_effect=RuntimeError('down')), \
                mock.patch('django.core.cache.backends.locmem.LocMemCache.touch', side_effect=RuntimeError('down')):
            cache.clear()
            self.assertFalse(cache.touch('missing'))


class CaptchaOutageTests(Base):
    def test_unreachable_recaptcha_service_does_not_crash_the_comment_endpoint(self):
        import urllib.error
        article = mk_article('cap')
        for error in (urllib.error.URLError('down'), TimeoutError('slow')):
            with self.subTest(error=type(error).__name__), mock.patch('captcha.client.submit', side_effect=error):
                response = self.client.post('/comment', {'article_id': str(article.id), 'author': 'a', 'text': 't',
                                                         'g-recaptcha-response': 'token'})
                self.assertLess(response.status_code, 500)

    def test_verification_timeout_is_short_enough_for_a_30_second_worker(self):
        from django.conf import settings
        import importlib
        prod = importlib.import_module('anarchia.settings')
        self.assertLessEqual(prod.RECAPTCHA_VERIFY_REQUEST_TIMEOUT, 5)


class TemplateDetailTests(Base):
    def test_search_query_with_a_slash_is_fully_encoded_in_page_links(self):
        for i in range(30):
            mk_article(f'sl{i}', name='a/b match')
        self.assertIn('q=a%2Fb', html_of(self.get_ok('/search/', data={'q': 'a/b'})))

    def test_article_microdata_names_the_author(self):
        mk_article('au', author=mk_author('writer'))
        self.assertIn('itemprop="author"', html_of(self.get_ok('/article/au/')))

    def test_opening_a_reply_form_closes_the_others(self):
        from .helpers import mk_comment
        mk_comment(mk_article('rf'))
        self.assertIn("querySelectorAll('.reply-form')", html_of(self.get_ok('/article/rf/')))


class MiddlewareOrderTests(SimpleTestCase):
    def test_whitenoise_is_listed_once_right_after_security_middleware(self):
        import importlib
        middleware = importlib.import_module('anarchia.settings').MIDDLEWARE
        names = [m for m in middleware if 'WhiteNoise' in m]
        self.assertEqual(len(names), 1)
        self.assertEqual(middleware.index(names[0]), middleware.index('django.middleware.security.SecurityMiddleware') + 1)
