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
