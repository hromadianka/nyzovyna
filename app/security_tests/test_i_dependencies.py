"""I. Dependencies and supply chain.

MIN_SAFE comes from `pip-audit -r requirements.txt --no-deps --disable-pip` (OSV/PyPI advisories, run on
2026-11-02): the lowest version that fixes every advisory listed for the pinned release (Django: last 4.2.x).
"""
import re

from django.core.checks import run_checks
from django.test import SimpleTestCase

from .base import REPO, SecBase, add_cases, known_open, tracked_files

# package -> (pinned-version advisories, minimum version fixing all of them)
MIN_SAFE = {
    'django': (91, '4.2.30'), 'pillow': (76, '13.0.0'), 'urllib3': (18, '2.8.0'), 'cryptography': (16, '49.0.0'),
    'pyasn1': (12, '0.6.5'), 'sqlparse': (12, '0.6.0'), 'requests': (8, '2.33.0'), 'jwcrypto': (6, '1.5.7'),
    'certifi': (4, '2026.10.18'), 'gunicorn': (4, '22.0.0'), 'idna': (4, '3.15'), 'protobuf': (4, '6.33.5'),
    'setuptools': (3, '84.1.0'), 'httplib2': (2, '0.32.0'), 'pycryptodome': (1, '3.19.1'), 'wheel': (1, '0.46.2'),
}

# requirement name -> top-level import name that would prove the project uses it
SUSPECT_UNUSED = {
    'Pyrebase4': 'pyrebase', 'gcloud': 'gcloud', 'python-firebase': 'firebase', 'python-jwt': 'python_jwt',
    'Radicale': 'radicale', 'rethinkdb': 'rethinkdb', 'oauth2client': 'oauth2client', 'vobject': 'vobject',
    'passlib': 'passlib', 'pybind11': 'pybind11', 'django-storages': 'storages', 'boto3': 'boto3',
    'google-cloud-storage': 'google.cloud', 'Markdown': 'markdown', 'looseversion': 'looseversion',
    'jwcrypto': 'jwcrypto', 'mysqlclient': 'MySQLdb',
}


def parse_requirements():
    pins = {}
    for raw in (REPO / 'requirements.txt').read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)\s*(==|>=|<=|~=|>|<)?\s*([\w.+!-]+)?', line)
        pins[match.group(1).lower()] = (match.group(2), match.group(3), line)
    return pins


def version_tuple(value):
    return tuple(int(part) for part in re.findall(r'\d+', value.split('.post')[0])[:4])


def project_sources():
    parts = []
    for rel in tracked_files():
        if rel.endswith(('.py', '.html')) and not rel.startswith(('staticfiles/', 'app/security_tests/', 'media/')) \
                and not rel.endswith(('test_findings.py', 'settings_test.py')):
            parts.append((REPO / rel).read_text(encoding='utf-8', errors='ignore'))
    return '\n'.join(parts)


class KnownVulnerableVersions(SecBase):
    pass


@add_cases(KnownVulnerableVersions, 'pinned_version_has_no_known_advisories', {k: k for k in MIN_SAFE})
def _pinned(self, name):
    operator, version, line = parse_requirements()[name]
    count, safe = MIN_SAFE[name]
    self.assertEqual(operator, '==')
    self.assertGreaterEqual(version_tuple(version), version_tuple(safe),
                            f'{name}=={version}: {count} known advisories (pip-audit/OSV); first fully fixed release: {safe}')


class UnusedPackages(SecBase):
    pass


@add_cases(UnusedPackages, 'requirement_is_imported_by_the_project', {k: k for k in SUSPECT_UNUSED})
def _unused(self, name):
    module = SUSPECT_UNUSED[name]
    sources = project_sources()
    used = re.search(rf'(^|\s)(import|from)\s+{re.escape(module)}\b|[\'"]{re.escape(module)}[\'".]', sources, re.M)
    self.assertTrue(used, f'{name} is in requirements.txt but nothing in app/, anarchia/ or templates imports {module!r}: dead weight and extra attack surface')


class RequirementHygiene(SecBase):
    def test_every_requirement_is_pinned_exactly(self):
        loose = [line for _, (op, _, line) in parse_requirements().items() if op != '==']
        self.assertEqual(loose, [], f'unpinned requirements make builds non-reproducible and open to dependency hijacking: {loose}')

    def test_requirements_carry_hashes(self):
        text = (REPO / 'requirements.txt').read_text(encoding='utf-8-sig')
        self.assertIn('--hash=sha256:', text, 'requirements.txt has no hashes: pip cannot detect a tampered or substituted package')

    def test_only_one_mysql_driver(self):
        pins = parse_requirements()
        self.assertFalse('mysqlclient' in pins and 'pymysql' in pins, 'both mysqlclient and PyMySQL are listed; settings.py uses PyMySQL via install_as_MySQLdb')

    def test_no_unneeded_database_driver(self):
        engine_mysql = "django.db.backends.mysql" in (REPO / 'anarchia' / 'settings.py').read_text(encoding='utf-8')
        self.assertFalse(engine_mysql and 'psycopg2' in parse_requirements() and 'django-heroku' not in parse_requirements(),
                         'psycopg2 is installed for a MySQL project')

    def test_runtime_python_is_supported_by_pinned_django(self):
        python = re.search(r'python-(\d+)\.(\d+)', (REPO / 'runtime.txt').read_text()).groups()
        django = parse_requirements()['django'][1]
        supported = {'4.2': {(3, 8), (3, 9), (3, 10), (3, 11), (3, 12)}}[django.rsplit('.', 1)[0]]
        self.assertIn((int(python[0]), int(python[1])), supported, f'runtime.txt asks for Python {".".join(python)}, which Django {django} does not support (security fixes are not tested there)')

    def test_ckeditor4_is_not_in_use(self):
        ids = {m.id for m in run_checks()}
        self.assertNotIn('ckeditor.W001', ids, 'django-ckeditor 6.7.1 bundles CKEditor 4.22.1 which has unfixed security issues (system check ckeditor.W001)')


class FrontendSupplyChain(SecBase):
    def external_assets(self):
        found = []
        for path in sorted((REPO / 'templates').glob('*.html')):
            for tag in re.findall(r'<(?:script|link)\b[^>]*>', path.read_text(encoding='utf-8')):
                if re.search(r'(?:src|href)\s*=\s*["\'](?:https?:)?//', tag) and 'rel="icon"' not in tag \
                        and 'instagram' not in tag and 't.me' not in tag and 'youtube' not in tag:
                    found.append((path.name, tag))
        return found

    def test_external_scripts_use_subresource_integrity(self):
        missing = [f'{name}: {tag[:90]}' for name, tag in self.external_assets() if tag.startswith('<script') and 'integrity=' not in tag]
        self.assertEqual(missing, [], f'third-party scripts without integrity=: {missing}')

    def test_external_stylesheets_use_subresource_integrity(self):
        missing = [f'{name}: {tag[:90]}' for name, tag in self.external_assets() if tag.startswith('<link') and 'integrity=' not in tag]
        self.assertEqual(missing, [], f'third-party stylesheets without integrity=: {missing}')

    def test_external_assets_are_version_pinned(self):
        unpinned = [f'{name}: {tag[:90]}' for name, tag in self.external_assets() if tag.startswith('<script') and not re.search(r'@\d+\.\d+\.\d+|/\d+\.\d+\.\d+/', tag)]
        self.assertEqual(unpinned, [])

    def test_ckeditor_jquery_is_https_and_patched(self):
        from .base import prod_setting
        url = prod_setting('CKEDITOR_JQUERY_URL')
        self.assertTrue(url.startswith('https://'), f'CKEDITOR_JQUERY_URL is protocol-relative ({url}): downgradable to HTTP')
        version = version_tuple(re.search(r'/(\d+\.\d+\.\d+)/', url).group(1))
        self.assertGreaterEqual(version, (3, 5, 0), 'jQuery < 3.5.0 has known XSS issues (CVE-2020-11022/11023)')


# Open findings: dependency changes need an explicit decision (see docs/security/AUDIT.md, section 7).
known_open(KnownVulnerableVersions, 'test_pinned_version')
known_open(UnusedPackages, 'test_requirement_is_imported')
known_open(RequirementHygiene, 'test_every_requirement', 'test_requirements_carry', 'test_only_one_mysql',
           'test_runtime_python', 'test_ckeditor4')
known_open(FrontendSupplyChain, 'test_external_scripts', 'test_external_stylesheets')
