"""
Shared fixtures for the security audit.

Every test states the *desired* secure behaviour: a red test confirms a finding.
Run:  DJANGO_SETTINGS_MODULE=anarchia.settings_test PYTHONDONTWRITEBYTECODE=1 \
      python manage.py test app.security_tests -v 2
"""
import importlib
import io
import json
import subprocess
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils.timezone import now

from app.models import AboutUsText, Article, Author, Category, Comment, Editor

REPO = Path(__file__).resolve().parents[2]
PASSWORD = 'S3cure-passw0rd!'
MARK = 'XSSMARK'

XSS_PAYLOADS = {
    'script': f"<script>alert('{MARK}')</script>",
    'img_onerror': f"\"><img src=x onerror=alert('{MARK}')>",
    'svg_onload': f"<svg/onload=alert('{MARK}')>",
    'js_href': f"<a href=\"javascript:alert('{MARK}')\">x</a>",
    'iframe_data': f"<iframe src=\"data:text/html,<script>alert('{MARK}')</script>\"></iframe>",
    'quote_breakout': f"');alert('{MARK}');//",
    'nested_tags': f"<scr<script>ipt>alert('{MARK}')</scr</script>ipt>",
    'mixed_case_handler': f"<img src=x oNeRrOr=alert('{MARK}')>",
    'entity_handler': f"<img src=x onerror=&#97;lert('{MARK}')>",
    'body_onload': f"<body onload=alert('{MARK}')>",
    'unclosed_img': f"<img src=x onerror=alert('{MARK}')",
    'oembed_js': f"<oembed url=\"javascript:alert('{MARK}')\"></oembed>",
}

SQLI_PAYLOADS = {
    'tautology': "' OR '1'='1",
    'drop_table': "'; DROP TABLE app_article;--",
    'double_quote': '" OR ""="',
    'union': "1 UNION SELECT username, password FROM auth_user--",
    'like_break': "%' AND 1=1--",
    'backslash': "\\' OR 1=1 --",
    'stacked': "1; UPDATE auth_user SET is_superuser=1;--",
}

DANGEROUS_SCHEMES = ('javascript:', 'vbscript:', 'data:text/html')


class ActiveContentFinder(HTMLParser):
    """Finds places where text carrying MARK would execute in a browser."""

    def __init__(self, marker=MARK):
        super().__init__(convert_charrefs=True)
        self.marker = marker
        self.findings = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        self._in_script = tag == 'script'
        if tag == 'script' and any(self.marker in (v or '') for _, v in attrs):
            self.findings.append(('script-attr', tag))
        for name, value in attrs:
            value = value or ''
            if self.marker not in value:
                continue
            if name.startswith('on'):
                self.findings.append(('event-handler', f'{tag}[{name}]'))
            elif name in ('href', 'src', 'action', 'formaction', 'data', 'xlink:href', 'url') \
                    and value.strip().lower().startswith(DANGEROUS_SCHEMES):
                self.findings.append(('dangerous-url', f'{tag}[{name}]'))

    def handle_endtag(self, tag):
        if tag == 'script':
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and self.marker in data:
            self.findings.append(('inline-script', data.strip()[:60]))


def active_content(html, marker=MARK):
    finder = ActiveContentFinder(marker)
    finder.feed(html)
    return finder.findings


def mask(secret):
    return f'{secret[:4]}***'


def git(*args):
    return subprocess.run(['git', *args], cwd=REPO, capture_output=True, check=True).stdout


def tracked_files():
    return [p for p in git('ls-files', '-z').decode().split('\0') if p]


def prod_settings():
    """Effective production settings (the unmodified project module, not settings_test)."""
    return importlib.import_module('anarchia.settings')


def prod_setting(name):
    """Production value of a setting, falling back to Django's default when settings.py leaves it unset."""
    from django.conf import global_settings
    return getattr(prod_settings(), name, getattr(global_settings, name, None))


def add_cases(cls, name, cases):
    """Generate one named test method per case so each endpoint reports on its own."""
    def decorator(func):
        for key, case in cases.items():
            def test(self, case=case):
                func(self, case)
            test.__name__ = f'test_{name}__{key}'
            test.__doc__ = f'{name}: {key}'
            setattr(cls, test.__name__, test)
        return func
    return decorator


def png_bytes(width=4, height=4):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), 'red').save(buf, 'PNG')
    return buf.getvalue()


def upload(name, content, content_type):
    return SimpleUploadedFile(name, content, content_type=content_type)


class Endpoints:
    """Registry of every state-changing or privileged route, resolved per test instance."""

    EDITOR_PAGES = ['editor_cabinet', 'publish', 'edit_article', 'edit_author', 'comments_moderation',
                    'category_order_editor', 'create_category', 'create_new_author']
    EDITOR_POSTS = ['publish', 'edit_article', 'create_category', 'about_us_edit', 'create_new_author',
                    'edit_author', 'delete_comment', 'update_category_order', 'delete_article', 'delete_category']
    EDITOR_GET_DELETES = ['delete_article', 'delete_category']
    PUBLIC_POSTS = ['login', 'comment_root', 'comment_reply', 'set_language']
    JSON_POSTS = ['update_category_order']

    def url(self, key):
        from django.urls import reverse
        return {
            'editor_cabinet': reverse('editor_cabinet'),
            'publish': reverse('publish'),
            'edit_article': reverse('edit_article', args=[self.article.slug]),
            'edit_author': reverse('edit_author', args=[self.author.slug]),
            'comments_moderation': reverse('comments_moderation'),
            'category_order_editor': reverse('category_order_editor'),
            'create_category': reverse('create_category'),
            'create_new_author': reverse('create_new_author'),
            'about_us_edit': reverse('about_us_edit'),
            'delete_comment': reverse('delete_comment', args=[self.comment.id]),
            'update_category_order': reverse('update_category_order'),
            'delete_article': reverse('delete', args=[self.article.slug]),
            'delete_category': reverse('delete_category', args=[self.child_cat.slug]),
            'login': reverse('login'),
            'comment_root': reverse('comment'),
            'comment_reply': reverse('comment'),
            'set_language': reverse('set_language'),
        }[key]

    def data(self, key):
        article_form = {
            'article_name': 'Valid title', 'article_text': '<p>valid</p>', 'language': 'ua',
            'article_author': str(self.author.id), 'publish_option': 'now',
            'categories': [str(self.child_cat.id)], 'article_slug': '',
        }
        return {
            'publish': article_form,
            'edit_article': article_form,
            'create_category': {'name_ua': 'Cat', 'name_en': 'Cat'},
            'about_us_edit': {'new_text_ua': 'ua', 'new_text_en': 'en'},
            'create_new_author': {
                'author_name_ua': 'Нов', 'author_name_en': 'New', 'author_description_ua': 'd',
                'author_description_en': 'd', 'author_image': upload('a.png', png_bytes(), 'image/png')},
            'edit_author': {'name_ua': 'Нов', 'name_en': 'New', 'description_ua': 'd', 'description_en': 'd'},
            'delete_comment': {}, 'delete_article': {}, 'delete_category': {},
            'update_category_order': json.dumps([{'id': str(self.root_cat.id), 'order': 3}]),
            'login': {'login': 'editor', 'password': 'wrong-password'},
            'comment_root': {'article_id': str(self.article.id), 'author': 'A', 'text': 'T'},
            'comment_reply': {'article_id': str(self.article.id), 'author': 'A', 'text': 'T',
                              'parent_comment_id': str(self.comment.id)},
            'set_language': {'language': 'en', 'next': '/'},
        }[key]

    def send(self, client, key, method='post', **extra):
        url = self.url(key)
        if method == 'get':
            return client.get(url, **extra)
        if key in self.JSON_POSTS:
            return client.post(url, data=self.data(key), content_type='application/json', **extra)
        return client.post(url, data=self.data(key), **extra)


class SecBase(Endpoints, TestCase):
    def setUp(self):
        cache.clear()
        self.editor_user = User.objects.create_user('editor', password=PASSWORD)
        Editor.objects.create(user=self.editor_user)
        self.regular_user = User.objects.create_user('reader', password=PASSWORD)
        self.staff_user = User.objects.create_user('staffer', password=PASSWORD, is_staff=True, is_superuser=True)

        self.author = Author.objects.create(
            name_ua='Автор', name_en='Author', description_ua='опис', description_en='bio', slug='author')
        self.root_cat = Category.objects.create(name_ua='Root', name_en='Root', slug='root')
        self.child_cat = Category.objects.create(name_ua='Child', name_en='Child', slug='child', parent=self.root_cat)

        self.article = self.make_article('public', 'Public article', 'PUBLIC BODY')
        self.draft = self.make_article('secret-draft', 'SECRET DRAFT TITLE', 'SECRET DRAFT BODY',
                                       is_published=False, publish_at=now() + timedelta(days=1))
        self.scheduled = self.make_article('future-post', 'SCHEDULED TITLE', 'SCHEDULED BODY',
                                           is_published=True, publish_at=now() + timedelta(days=1))
        self.comment = Comment.objects.create(article=self.article, author='Visitor', text='first!')
        AboutUsText.objects.create(pk=1, text_ua='про нас', text_en='about us')

    def make_article(self, slug, name, text, **extra):
        extra.setdefault('is_published', True)
        article = Article.objects.create(
            slug=slug, name=name, text=text, author=self.author, language='ua', **extra)
        article.categories.add(self.child_cat, self.root_cat)
        return article

    def make_client(self, user=None, csrf=False):
        client = Client(enforce_csrf_checks=csrf, raise_request_exception=False)
        if user is not None:
            client.force_login(user)
        return client

    def snapshot(self):
        return {
            'articles': sorted(Article.objects.values_list('pk', 'slug', 'is_published', 'name', 'text')),
            'categories': sorted(Category.objects.values_list('pk', 'slug', 'order', 'parent_id')),
            'comments': sorted(Comment.objects.values_list('pk', 'text')),
            'authors': sorted(Author.objects.values_list('pk', 'name_en')),
            'users': sorted(User.objects.values_list('pk', 'username')),
            'about': list(AboutUsText.objects.values_list('text_ua', 'text_en')),
        }

    def post_json(self, client, url, payload):
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        return client.post(url, data=body, content_type='application/json')



def body_text(response):
    return response.content.decode('utf-8', 'replace')
