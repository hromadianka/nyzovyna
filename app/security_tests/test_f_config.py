"""F. Configuration, response headers, secrets in the repository (files, history, committed artefacts)."""
import ast
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from django.core.checks import run_checks
from django.test import override_settings

from .base import REPO, SecBase, add_cases, git, known_open, mask, prod_setting, prod_settings, tracked_files

SETTINGS_PY = REPO / 'anarchia' / 'settings.py'


def settings_assignments():
    tree = ast.parse(SETTINGS_PY.read_text(encoding='utf-8'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node
    return found


def literal_secret(name):
    node = settings_assignments().get(name)
    if node is not None and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
        return node.value.value, node.lineno
    return None, None


class ProductionSettings(SecBase):
    def test_debug_is_disabled(self):
        self.assertFalse(prod_settings().DEBUG, 'DEBUG = True is hard-coded (anarchia/settings.py:%d)' % settings_assignments()['DEBUG'].lineno)

    def test_secret_key_is_not_hardcoded(self):
        value, line = literal_secret('SECRET_KEY')
        self.assertIsNone(value, f'SECRET_KEY literal {mask(value or "")} committed at anarchia/settings.py:{line}; read it from the environment')

    def test_secret_key_is_strong(self):
        key = prod_settings().SECRET_KEY
        self.assertFalse(key.startswith('django-insecure-'), f'SECRET_KEY {mask(key)} is the auto-generated insecure one')
        self.assertGreaterEqual(len(key), 50)
        self.assertGreaterEqual(len(set(key)), 5)

    def test_recaptcha_private_key_is_not_hardcoded(self):
        value, line = literal_secret('RECAPTCHA_PRIVATE_KEY')
        self.assertIsNone(value, f'RECAPTCHA_PRIVATE_KEY {mask(value or "")} committed at anarchia/settings.py:{line}')

    def test_cloudinary_credentials_are_not_hardcoded(self):
        source = SETTINGS_PY.read_text(encoding='utf-8')
        match = re.search(r"'API_KEY':\s*'(\d+)'", source)
        self.assertIsNone(match, f"CLOUDINARY_STORAGE API_KEY {mask(match.group(1)) if match else ''} committed (settings.py); only API_SECRET is read from env")

    def test_allowed_hosts_has_no_wildcard(self):
        self.assertNotIn('*', prod_setting('ALLOWED_HOSTS'),
                         'effective ALLOWED_HOSTS is ["*"]: django_heroku.settings(locals()) (settings.py:179) overwrites the explicit list; pass allowed_hosts=False')

    def test_explicit_allowed_hosts_survive_django_heroku(self):
        declared = ast.literal_eval(settings_assignments()['ALLOWED_HOSTS'].value)
        self.assertEqual(prod_setting('ALLOWED_HOSTS'), declared, 'the ALLOWED_HOSTS list declared in settings.py is silently replaced at import time')

    def test_ssl_redirect_enabled(self):
        self.assertTrue(prod_setting('SECURE_SSL_REDIRECT'))

    def test_proxy_ssl_header_configured_for_heroku(self):
        self.assertEqual(prod_setting('SECURE_PROXY_SSL_HEADER'), ('HTTP_X_FORWARDED_PROTO', 'https'))

    def test_hsts_lifetime_at_least_one_year(self):
        self.assertGreaterEqual(prod_setting('SECURE_HSTS_SECONDS'), 31536000)

    def test_hsts_covers_subdomains_and_preload(self):
        self.assertTrue(prod_setting('SECURE_HSTS_INCLUDE_SUBDOMAINS') and prod_setting('SECURE_HSTS_PRELOAD'))

    def test_session_and_csrf_cookie_flags(self):
        for name in ('SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'SESSION_COOKIE_HTTPONLY'):
            with self.subTest(setting=name):
                self.assertTrue(prod_setting(name), f'{name} is False in production settings')

    def test_cookie_samesite(self):
        for name in ('SESSION_COOKIE_SAMESITE', 'CSRF_COOKIE_SAMESITE'):
            with self.subTest(setting=name):
                self.assertIn(prod_setting(name), ('Lax', 'Strict'))

    def test_x_frame_options_deny(self):
        self.assertIn(prod_setting('X_FRAME_OPTIONS'), ('DENY', 'SAMEORIGIN'))
        self.assertTrue(prod_setting('SECURE_CONTENT_TYPE_NOSNIFF'))

    def test_referrer_and_opener_policy(self):
        self.assertTrue(prod_setting('SECURE_REFERRER_POLICY'))
        self.assertTrue(prod_setting('SECURE_CROSS_ORIGIN_OPENER_POLICY'))

    def test_password_validators_enabled(self):
        self.assertGreaterEqual(len(prod_setting('AUTH_PASSWORD_VALIDATORS')), 3)

    def test_session_engine_allows_server_side_revocation(self):
        self.assertNotIn('signed_cookies', prod_setting('SESSION_ENGINE'),
                         'signed_cookies sessions cannot be revoked and are forgeable with a leaked SECRET_KEY')


class DeploymentChecks(SecBase):
    def test_check_deploy_with_production_settings_is_clean(self):
        prod = prod_settings()
        names = [n for n in dir(prod) if n.isupper() and n.startswith(('SECURE_', 'SESSION_', 'CSRF_', 'X_FRAME'))
                 or n in ('DEBUG', 'SECRET_KEY', 'ALLOWED_HOSTS')]
        with override_settings(**{n: getattr(prod, n) for n in names}):
            issues = [m.id for m in run_checks(include_deployment_checks=True) if m.id != 'ckeditor.W001']
        self.assertEqual(issues, [], f'manage.py check --deploy reports: {sorted(issues)}')


class ResponseHeaders(SecBase):
    def test_hsts_header_on_https(self):
        header = self.make_client().get('/', secure=True).get('Strict-Transport-Security', '')
        self.assertIn('max-age=31536000', header)
        self.assertIn('includeSubDomains', header)

    def test_hsts_is_not_sent_over_http(self):
        self.assertNotIn('Strict-Transport-Security', self.make_client().get('/'))

    def test_referrer_policy_header(self):
        self.assertIn(self.make_client().get('/', secure=True)['Referrer-Policy'], ('same-origin', 'strict-origin', 'no-referrer', 'strict-origin-when-cross-origin'))

    def test_opener_policy_header(self):
        self.assertEqual(self.make_client().get('/', secure=True)['Cross-Origin-Opener-Policy'], 'same-origin')

    def test_no_server_version_leak_in_headers(self):
        response = self.make_client().get('/', secure=True)
        for header in ('X-Powered-By', 'X-Django-Version'):
            self.assertNotIn(header, response)

    def test_permissions_policy_present(self):
        self.assertIn('Permissions-Policy', self.make_client().get('/', secure=True), 'no Permissions-Policy (camera/microphone/geolocation are not restricted)')

    def test_cache_headers_on_editor_pages_forbid_shared_caching(self):
        response = self.make_client(self.editor_user).get('/editor-cabinet')
        directives = response.get('Cache-Control', '')
        self.assertTrue('private' in directives or 'no-store' in directives,
                        f'editor-only pages carry no Cache-Control private/no-store ({directives!r}): a shared cache may store drafts')


SECRET_PATTERNS = {
    'django_insecure_secret_key': r"django-insecure-[\w!@#$%^&*()+=.-]{20,}",
    'recaptcha_private_key': r"RECAPTCHA_PRIVATE_KEY\s*=\s*['\"][\w-]{20,}",
    'cloudinary_api_key': r"'API_KEY':\s*'\d{12,}'",
    'cloudinary_api_secret': r"'API_SECRET':\s*'[\w-]{20,}'",
    'aws_access_key_id': r"AKIA[0-9A-Z]{16}",
    'private_key_block': r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    'url_with_credentials': r"[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s:@'\"]{3,}@[\w.-]+",
    'hardcoded_password_assignment': r"(?i)\b(password|passwd|secret|api_?key|token)\b\s*[:=]\s*['\"][^'\"\s$%{}<>]{8,}['\"]",
}
SKIP_PREFIXES = ('staticfiles/', 'media/', 'locale/', '.idea/', '.vs/', 'app/security_tests/', 'docs/', 'static/img/')
SKIP_FILES = ('app/test_findings.py', 'anarchia/settings_test.py', 'requirements.txt')


def text_files():
    for rel in tracked_files():
        if rel.startswith(SKIP_PREFIXES) or rel in SKIP_FILES or rel.endswith(('.pyc', '.sqlite3', '.png', '.jpg', '.svg', '.suo', '.bin', '.sqlite', '.mo')):
            continue
        yield rel


class SecretsInRepository(SecBase):
    pass


@add_cases(SecretsInRepository, 'not_in_tracked_files', SECRET_PATTERNS)
def _in_files(self, pattern):
    regex = re.compile(pattern)
    hits = []
    for rel in text_files():
        for number, line in enumerate((REPO / rel).read_text(encoding='utf-8', errors='ignore').splitlines(), 1):
            match = regex.search(line)
            if match:
                hits.append(f'{rel}:{number} {mask(match.group(0))}')
    self.assertEqual(hits, [], f'secret-like values committed: {hits}')


def added_lines_by_commit():
    log = git('log', '--all', '-p', '--no-color', '--format=%x01%h', '--',
              'anarchia', 'app', 'templates', 'Procfile', 'requirements.txt').decode('utf-8', 'ignore')
    commit, lines = None, []
    for line in log.splitlines():
        if line.startswith('\x01'):
            commit = line[1:]
        elif line.startswith('+') and not line.startswith('+++'):
            lines.append((commit, line[1:]))
    return lines


@add_cases(SecretsInRepository, 'not_in_git_history', {k: v for k, v in SECRET_PATTERNS.items() if k != 'hardcoded_password_assignment'})
def _in_history(self, pattern):
    regex = re.compile(pattern)
    commits = sorted({commit for commit, line in added_lines_by_commit() if regex.search(line)})
    self.assertEqual(commits, [], f'{len(commits)} commit(s) in history ever added this secret ({commits[:3]}); rotate it, deleting the line is not enough')


known_open(SecretsInRepository, 'test_not_in_git_history__cloudinary', 'test_not_in_git_history__django', 'test_not_in_git_history__recaptcha')  # needs a history rewrite and credential rotation by the owner


class CommittedArtefacts(SecBase):
    def tracked(self, *suffixes, prefix=None):
        return [p for p in tracked_files() if (not suffixes or p.endswith(suffixes)) and (prefix is None or p.startswith(prefix))]

    def test_no_bytecode_is_tracked(self):
        files = self.tracked('.pyc')
        self.assertEqual(files, [], f'{len(files)} .pyc files are tracked (e.g. {files[:2]}); they embed settings values')

    def test_no_database_file_is_tracked(self):
        files = self.tracked('.sqlite3', '.sqlite', '.db')
        self.assertEqual(files, [], f'database files tracked: {files}')

    def test_no_ide_state_is_tracked(self):
        files = self.tracked(prefix='.vs/') + self.tracked(prefix='.idea/')
        self.assertEqual(files, [], f'{len(files)} IDE files tracked (.vs/, .idea/)')

    def test_gitignored_settings_file_is_not_tracked(self):
        ignored = subprocess.run(['git', 'check-ignore', '--no-index', 'anarchia/settings.py'], cwd=REPO, capture_output=True).returncode == 0
        self.assertEqual(ignored and 'anarchia/settings.py' in tracked_files(), False,
                         'settings.py is listed in .gitignore but is tracked, so the ignore rule gives a false sense of safety')

    def test_ignored_bytecode_of_settings_is_not_tracked(self):
        self.assertNotIn('anarchia/__pycache__/settings.cpython-311.pyc', tracked_files())

    def test_gitignore_covers_secrets_and_artefacts(self):
        text = (REPO / '.gitignore').read_text(encoding='utf-8')
        for needed in ('__pycache__', '*.pyc', '.env', '*.sqlite3', '.idea', '.vs'):
            with self.subTest(pattern=needed):
                self.assertIn(needed, text, f'.gitignore lacks {needed!r}')

    def test_pyc_files_do_not_embed_secrets(self):
        secrets = [v for v in (literal_secret('SECRET_KEY')[0], literal_secret('RECAPTCHA_PRIVATE_KEY')[0]) if v]
        leaking = [p for p in self.tracked('.pyc') if any(s.encode() in (REPO / p).read_bytes() for s in secrets)]
        self.assertEqual(leaking, [], f'compiled settings with secrets are committed: {leaking}')

    def committed_db(self):
        try:
            blob = git('show', 'HEAD:db.sqlite3')
        except subprocess.CalledProcessError:
            return None
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False)
        tmp.write(blob)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return sqlite3.connect(f'file:{tmp.name}?mode=ro', uri=True)

    def test_committed_database_has_no_user_accounts(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute('select count(*) from auth_user').fetchone()[0]
        self.assertEqual(count, 0, f'db.sqlite3 in HEAD holds {count} auth_user rows')

    def test_committed_database_has_no_password_hashes(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute("select count(*) from auth_user where password like '%$%'").fetchone()[0]
        self.assertEqual(count, 0, f'{count} password hashes (PBKDF2) are downloadable for offline cracking')

    def test_committed_database_has_no_personal_data(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute("select count(*) from auth_user where email like '%@%'").fetchone()[0]
        self.assertEqual(count, 0, f'{count} account e-mail addresses are committed (personal data)')

    def test_committed_database_has_no_privileged_accounts(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute('select count(*) from auth_user where is_superuser=1').fetchone()[0]
        self.assertEqual(count, 0, f'{count} superuser accounts in the committed database')

    def test_committed_database_has_no_sessions(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute('select count(*) from django_session').fetchone()[0]
        self.assertEqual(count, 0, f'{count} session rows committed')

    def test_committed_database_has_no_comments_or_visitor_data(self):
        db = self.committed_db()
        count = 0 if db is None else db.execute('select count(*) from app_comment').fetchone()[0]
        self.assertEqual(count, 0)

    def test_committed_media_has_no_gps_exif(self):
        from PIL import Image
        leaking = []
        for rel in self.tracked(prefix='media/'):
            try:
                with Image.open(REPO / rel) as image:
                    if image.getexif().get_ifd(0x8825):
                        leaking.append(rel)
            except OSError:
                continue
        self.assertEqual(leaking, [])

    def test_no_env_file_is_tracked(self):
        self.assertEqual([p for p in tracked_files() if Path(p).name.startswith('.env')], [])
