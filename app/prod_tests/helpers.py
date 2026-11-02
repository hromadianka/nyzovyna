import os
import re
import signal
import tempfile
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from app.forms import CommentCaptchaForm
from app.models import AboutUsText, Article, Author, Category, Comment, Editor

BASE_DIR = Path(settings.BASE_DIR)
TEMPLATES_DIR = BASE_DIR / 'templates'
ON_MYSQL = os.environ.get('NYZ_DB') == 'mysql'

def _valid_png():
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new('RGB', (4, 4), (200, 30, 30)).save(buffer, 'PNG')
    return buffer.getvalue()


PNG = _valid_png()


def png(name='pic.png'):
    return SimpleUploadedFile(name, PNG, content_type='image/png')


def mk_category(slug, parent=None, order=0, name_ua=None, name_en=None):
    return Category.objects.create(
        slug=slug, parent=parent, order=order,
        name_ua=name_ua or f'ua-{slug}', name_en=name_en or f'en-{slug}')


def mk_author(slug='author-1', **kw):
    kw.setdefault('name_en', f'En {slug}')
    kw.setdefault('name_ua', f'Ua {slug}')
    return Author.objects.create(slug=slug, description_en='d', description_ua='d', **kw)


def mk_article(slug='a-1', name=None, cats=(), published=True, language='ua', author=None,
               publish_at=None, views=0, text='<p>body</p>', **kw):
    article = Article.objects.create(
        slug=slug, name=name or f'Title {slug}', text=text, language=language, author=author,
        is_published=published, publish_at=publish_at or now(), views=views, **kw)
    if cats:
        article.categories.add(*cats)
    return article


def mk_comment(article, parent=None, author='anon', text='hello'):
    return Comment.objects.create(article=article, parent_comment=parent, author=author, text=text)


def seed_site(n_articles=6):
    root = mk_category('root', order=1)
    child = mk_category('child', parent=root)
    author = mk_author()
    arts = [mk_article(f'seed-{i}', cats=[root, child], author=author, views=i,
                       publish_at=now() - timedelta(hours=i)) for i in range(n_articles)]
    AboutUsText.objects.create(pk=1, text_ua='про нас', text_en='about us')
    return root, child, author, arts


def table_count(table):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        return cursor.fetchone()[0]


def db_fingerprint():
    return {
        'article': table_count('app_article'), 'category': table_count('app_category'),
        'author': table_count('app_author'), 'comment': table_count('app_comment'),
        'about': table_count('app_aboutustext'),
        'views': sum(Article.objects.values_list('views', flat=True)),
        'published': Article.objects.filter(is_published=True).count(),
    }


def html_of(response):
    return response.content.decode('utf-8', 'replace')


def visible_text(html):
    return re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style)\b.*?</\1>', '', html, flags=re.S | re.I))


class Timeout(Exception):
    pass


@contextmanager
def time_limit(seconds):
    def handler(signum, frame):
        raise Timeout(f'exceeded {seconds}s')
    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class QueryLimit:
    def __init__(self, limit):
        self.limit, self.count, self.exceeded = limit, 0, False

    def __call__(self, execute, sql, params, many, context):
        self.count += 1
        if self.count == self.limit + 1:
            self.exceeded = True
            raise Timeout(f'more than {self.limit} queries')
        return execute(sql, params, many, context)


@contextmanager
def query_limit(limit):
    guard = QueryLimit(limit)
    with connection.execute_wrapper(guard):
        yield guard


@contextmanager
def captcha_ok(valid=True):
    with mock.patch.object(CommentCaptchaForm, 'is_valid', return_value=valid):
        yield


class SavepointClient(Client):
    def request(self, **request):
        with transaction.atomic():
            return super().request(**request)


class Base(TestCase):
    client_class = SavepointClient
    password = 'pw-for-tests-123'

    def setUp(self):
        cache.clear()
        self.client.raise_request_exception = False
        self._media = tempfile.TemporaryDirectory()
        self.addCleanup(self._media.cleanup)
        self._override = self.settings(MEDIA_ROOT=self._media.name)
        self._override.enable()
        self.addCleanup(self._override.disable)

    def login(self, username='editor'):
        user = User.objects.create_user(username, password=self.password)
        Editor.objects.create(user=user)
        self.client.login(username=username, password=self.password)
        return user

    def get_ok(self, url, **kw):
        response = self.client.get(url, **kw)
        self.assertEqual(response.status_code, 200, f'{url} -> {response.status_code}')
        return response

    def queries(self, url, method='get', **kw):
        with CaptureQueriesContext(connection) as ctx:
            response = getattr(self.client, method)(url, **kw)
        return response, len(ctx)

    def in_order(self, html, *needles):
        positions = [html.find(n) for n in needles]
        self.assertTrue(all(p >= 0 for p in positions), f'missing in html: {list(zip(needles, positions))}')
        self.assertEqual(positions, sorted(positions), f'wrong order: {list(zip(needles, positions))}')


def make_editor(username='editor', password='pw-for-tests-123'):
    user = User.objects.create_user(username, password=password)
    Editor.objects.create(user=user)
    return user


def new_uuid():
    return uuid.uuid4()
