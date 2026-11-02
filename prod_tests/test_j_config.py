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
