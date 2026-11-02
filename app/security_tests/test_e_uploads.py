"""E. File uploads: model image fields (publish/edit article, create/edit author) and CKEditor upload/browse."""
import os
import struct
import zlib

from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse

from app.models import Article, Author

from .base import SecBase, add_cases, png_bytes, upload

MB = 1024 * 1024
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script></svg>'
HTML = b'<html><body><script>alert(document.domain)</script></body></html>'
PHP = b'GIF89a;<?php system($_GET["c"]); ?>'
DEFAULT_IMAGE = 'card-example.png'


def bomb_png():
    """A syntactically valid PNG header that declares 100000x100000 pixels with a tiny body."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', 100000, 100000, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(b'\0' * 1024)) + chunk(b'IEND', b'')


# case -> (filename, content factory, declared content type, reason it must be rejected)
REJECT = {
    'html_declared_as_png': ('x.png', lambda: HTML, 'image/png', 'content is HTML, only the client-supplied Content-Type says image'),
    'svg_declared_as_png': ('x.png', lambda: SVG, 'image/png', 'SVG with script served from the site origin'),
    'svg_declared_as_svg': ('x.svg', lambda: SVG, 'image/svg+xml', 'image/* prefix check lets SVG (script carrier) in'),
    'php_polyglot_gif': ('shell.php', lambda: PHP, 'image/gif', 'executable extension kept'),
    'php_double_extension': ('shell.php.png', lambda: PHP, 'image/png', 'polyglot payload inside a .png name'),
    'png_double_extension_php': ('pic.png.php', lambda: png_bytes(), 'image/png', 'real PNG but .php extension'),
    'html_extension_with_png_body': ('page.html', lambda: png_bytes(), 'image/png', '.html extension is stored and would be served as HTML'),
    'executable_declared_as_image': ('setup.exe', lambda: b'MZ' + b'\0' * 64, 'image/png', 'arbitrary binary accepted'),
    'truncated_png': ('cut.png', lambda: png_bytes()[:24], 'image/png', 'broken image accepted without decoding'),
    'zero_bytes': ('empty.png', lambda: b'', 'image/png', 'empty file accepted'),
    'oversized_11mb': ('big.png', lambda: png_bytes() + b'\0' * (11 * MB), 'image/png', 'no upload size limit'),
    'decompression_bomb': ('bomb.png', bomb_png, 'image/png', '100000x100000 px declared: dimensions are never checked'),
}

# stored must stay inside MEDIA_ROOT whatever the client calls the file
NAMES = {
    'dotdot_slash': '../../evil.png',
    'dotdot_backslash': '..\\..\\evil.png',
    'absolute_path': '/etc/cron.d/evil.png',
    'null_byte': 'evil\x00.php.png',
    'very_long_name': 'a' * 300 + '.png',
    'unicode_rtl_override': 'photo‮gnp.php',
}

UPLOAD_ENDPOINTS = {
    'publish': ('publish', 'article_image'),
    'edit_article': ('edit_article', 'article_image'),
    'create_new_author': ('create_new_author', 'author_image'),
    'edit_author': ('edit_author', 'author_image'),
}


class UploadBase(SecBase):
    def submit(self, key, field, uploaded):
        data = {**self.data(key), field: uploaded}
        return self.make_client(self.editor_user).post(self.url(key), data)

    def stored_name(self, key):
        if key == 'publish':
            created = Article.objects.exclude(pk__in=[self.article.pk, self.draft.pk, self.scheduled.pk]).first()
            return created.image.name if created else None
        if key == 'edit_article':
            return Article.objects.get(pk=self.article.pk).image.name
        if key == 'create_new_author':
            created = Author.objects.exclude(pk=self.author.pk).first()
            return created.image.name if created else None
        return Author.objects.get(pk=self.author.pk).image.name

    def was_stored(self, key):
        name = self.stored_name(key)
        return bool(name) and name != DEFAULT_IMAGE


class ModelImageUploads(UploadBase):
    pass


CASES = {f'{ep}__{case}': (ep, case) for ep in UPLOAD_ENDPOINTS for case in REJECT}


@add_cases(ModelImageUploads, 'hostile_upload_is_rejected', CASES)
def _hostile(self, spec):
    endpoint, case = spec
    key, field = UPLOAD_ENDPOINTS[endpoint]
    filename, content, ctype, why = REJECT[case]
    response = self.submit(key, field, upload(filename, content(), ctype))
    self.assertLess(response.status_code, 500, f'{endpoint}/{case}: server error')
    self.assertFalse(self.was_stored(key), f'{endpoint}: stored {self.stored_name(key)!r}. {why} (views check only content_type.startswith("image"))')


NAME_CASES = {f'{ep}__{n}': (ep, n) for ep in UPLOAD_ENDPOINTS for n in NAMES}


@add_cases(ModelImageUploads, 'filename_cannot_escape_media_root', NAME_CASES)
def _names(self, spec):
    endpoint, name_key = spec
    key, field = UPLOAD_ENDPOINTS[endpoint]
    response = self.submit(key, field, upload(NAMES[name_key], png_bytes(), 'image/png'))
    self.assertLess(response.status_code, 500, f'{endpoint}/{name_key}: server error on odd filename')
    stored = self.stored_name(key)
    if self.was_stored(key):
        full = os.path.realpath(os.path.join(settings.MEDIA_ROOT, stored))
        self.assertTrue(full.startswith(os.path.realpath(settings.MEDIA_ROOT) + os.sep), f'stored outside MEDIA_ROOT: {full}')
        self.assertNotIn('..', stored)
        self.assertFalse(stored.lower().endswith(('.php', '.html', '.svg', '.exe')), f'dangerous extension survives: {stored}')


@add_cases(ModelImageUploads, 'valid_png_is_accepted', {k: k for k in UPLOAD_ENDPOINTS})
def _valid(self, endpoint):
    key, field = UPLOAD_ENDPOINTS[endpoint]
    self.submit(key, field, upload('ok.png', png_bytes(), 'image/png'))
    self.assertTrue(self.was_stored(key), 'baseline: a legitimate PNG must still be accepted')


@add_cases(ModelImageUploads, 'non_image_content_type_is_refused', {k: k for k in ('publish', 'edit_article', 'edit_author', 'create_new_author')})
def _ctype(self, endpoint):
    key, field = UPLOAD_ENDPOINTS[endpoint]
    self.submit(key, field, upload('doc.txt', b'plain', 'text/plain'))
    self.assertFalse(self.was_stored(key))


class CkeditorEndpoints(SecBase):
    UPLOAD = '/ckeditor/upload/?responseType=json'

    def push(self, user, filename, content, ctype):
        return self.make_client(user).post(self.UPLOAD, {'upload': upload(filename, content, ctype)})

    def test_upload_requires_login(self):
        self.assertEqual(self.push(None, 'a.png', png_bytes(), 'image/png').status_code, 302)

    def test_upload_refused_for_regular_user(self):
        self.assertEqual(self.push(self.regular_user, 'a.png', png_bytes(), 'image/png').status_code, 302)

    def test_upload_refused_for_editor_without_staff_flag(self):
        self.assertEqual(self.push(self.editor_user, 'a.png', png_bytes(), 'image/png').status_code, 302,
                         'editors cannot use the CKEditor uploader unless they are staff (not a vulnerability, just a note)')

    def test_browse_requires_staff(self):
        for user in (None, self.regular_user):
            with self.subTest(user=user):
                self.assertEqual(self.make_client(user).get('/ckeditor/browse/').status_code, 302)

    def test_upload_get_is_not_allowed(self):
        self.assertIn(self.make_client(self.staff_user).get('/ckeditor/upload/').status_code, (302, 405))

    def test_staff_can_upload_a_png(self):
        response = self.push(self.staff_user, 'ok.png', png_bytes(), 'image/png')
        self.assertEqual(response.status_code, 200)
        self.assertIn('url', response.json())

    def test_upload_requires_csrf_token(self):
        client = self.make_client(self.staff_user, csrf=True)
        response = client.post(self.UPLOAD, {'upload': upload('ok.png', png_bytes(), 'image/png')})
        self.assertEqual(response.status_code, 403, 'ckeditor_uploader wraps the upload view in csrf_exempt: cross-site upload on behalf of a logged-in staff user')

    def test_non_image_files_are_refused(self):
        for name, content, ctype in (('x.html', HTML, 'text/html'), ('x.svg', SVG, 'image/svg+xml'),
                                     ('shell.php', PHP, 'image/gif'), ('x.png', HTML, 'image/png')):
            with self.subTest(file=name):
                response = self.push(self.staff_user, name, content, ctype)
                accepted = response.status_code == 200 and b'"url"' in response.content
                self.assertFalse(accepted, f'{name}: CKEDITOR_ALLOW_NONIMAGE_FILES defaults to True, so any file type is stored')

    def test_decompression_bomb_is_handled(self):
        response = self.push(self.staff_user, 'bomb.png', bomb_png(), 'image/png')
        self.assertLess(response.status_code, 500, 'uploader opens the image with Pillow: bomb gives a server error')

    def test_oversized_upload_is_refused(self):
        response = self.push(self.staff_user, 'big.png', png_bytes() + b'\0' * (11 * MB), 'image/png')
        self.assertNotEqual(response.status_code, 200, 'no size limit on /ckeditor/upload/')

    def test_filename_traversal_stays_inside_media_root(self):
        response = self.push(self.staff_user, '../../evil.png', png_bytes(), 'image/png')
        self.assertLess(response.status_code, 500)
        if response.status_code == 200 and 'url' in response.json():
            self.assertNotIn('..', response.json()['url'])

    def test_staff_user_can_exist_without_unlocking_admin_for_regular_users(self):
        self.assertEqual(self.make_client(self.regular_user).get('/admin/').status_code, 302)
        self.assertEqual(self.make_client(None).get('/admin/').status_code, 302)
        self.assertTrue(User.objects.get(username='staffer').is_staff)

    def test_admin_login_page_is_the_only_anonymous_admin_view(self):
        for path in ('/admin/auth/user/', '/admin/app/article/', '/admin/app/comment/', '/admin/jsi18n/'):
            with self.subTest(path=path):
                response = self.make_client().get(path)
                self.assertIn(response.status_code, (302,), f'{path} reachable anonymously ({response.status_code})')
