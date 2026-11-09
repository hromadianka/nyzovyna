import importlib

from django.test import SimpleTestCase


def prod_settings():
    return importlib.import_module('anarchia.settings')


class ProductionSettingsTests(SimpleTestCase):
    def test_database_connection_is_pinned_to_utf8mb4(self):
        options = prod_settings().DATABASES['default']['OPTIONS']
        self.assertEqual(options.get('charset'), 'utf8mb4')

    def test_database_connection_keeps_strict_mode(self):
        options = prod_settings().DATABASES['default']['OPTIONS']
        self.assertIn('STRICT_TRANS_TABLES', options.get('init_command', ''))


class ProductionLoggingTests(SimpleTestCase):
    def emit(self, logger_name, level):
        import contextlib
        import copy
        import io
        import logging
        import logging.config

        from django.utils.log import DEFAULT_LOGGING
        stream = io.StringIO()
        saved = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).level) for name in
                 ('', 'django', 'django.request', 'app')}
        with contextlib.redirect_stdout(stream):
            try:
                logging.config.dictConfig(copy.deepcopy(DEFAULT_LOGGING))
                logging.config.dictConfig(copy.deepcopy(prod_settings().LOGGING))
                logging.getLogger(logger_name).log(level, 'probe message %s', logger_name)
            finally:
                for name, (handlers, lvl) in saved.items():
                    logging.getLogger(name).handlers[:] = handlers
                    logging.getLogger(name).setLevel(lvl)
        return stream.getvalue()

    def test_request_errors_reach_stdout_when_debug_is_off(self):
        import logging
        self.assertIn('probe message django.request', self.emit('django.request', logging.ERROR))

    def test_application_warnings_reach_stdout(self):
        import logging
        self.assertIn('probe message app.views', self.emit('app.views', logging.WARNING))

    def test_log_lines_carry_a_timestamp_and_level(self):
        import logging
        self.assertRegex(self.emit('django.request', logging.ERROR), r'\d{4}-\d{2}-\d{2}.*ERROR')


class DeploymentFilesTests(SimpleTestCase):
    def read(self, name):
        from pathlib import Path
        return (Path(prod_settings().BASE_DIR) / name).read_text(encoding='utf-8')

    def test_migrations_run_in_the_release_phase(self):
        self.assertRegex(self.read('Procfile'), r'(?m)^release:\s*python manage.py migrate')

    def test_web_process_sets_workers_timeout_and_request_logging(self):
        web = [line for line in self.read('Procfile').splitlines() if line.startswith('web:')][0]
        for flag in ('--workers', '--timeout', '--access-logfile', '--max-requests'):
            with self.subTest(flag=flag):
                self.assertIn(flag, web)

    def test_menu_cache_expires_within_a_minute_so_workers_converge(self):
        import re
        base = self.read('templates/base.html')
        for ttl in re.findall(r'{% cache (\d+) ', base):
            with self.subTest(ttl=ttl):
                self.assertLessEqual(int(ttl), 60)

    def test_one_off_slug_rewrite_script_is_not_in_the_repository(self):
        from pathlib import Path
        self.assertFalse((Path(prod_settings().BASE_DIR) / 'fill_slugs.py').exists())


class DependencyTests(SimpleTestCase):
    def requirement_names(self):
        from pathlib import Path

        from django.conf import settings
        lines = (Path(settings.BASE_DIR) / 'requirements.txt').read_text().splitlines()
        return {line.split('==')[0].strip().lower() for line in lines if line.strip() and not line.startswith('#')}

    def test_cryptography_is_pinned_because_pymysql_needs_it_for_mysql_8_login(self):
        """MySQL 8 authenticates with caching_sha2_password; without cryptography PyMySQL raises RuntimeError on
        every connection, so the whole site answers 500. A virtualenv that still has the package hides this."""
        self.assertIn('cryptography', self.requirement_names())
