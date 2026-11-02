"""Settings wrapper for load/perf measurements (localhost only).

Env: NYZ_LOAD_DB (mysql db name, default nyz_load), NYZ_DEBUG (1/0, default 1 = as in repo),
     NYZ_LOAD_ENGINE=sqlite + NYZ_LOAD_SQLITE=<path> for sqlite comparison.
Usage: PYTHONPATH=<repo>:<this dir> DJANGO_SETTINGS_MODULE=nyz_load_settings
"""
import os
os.environ.setdefault('NYZ_DB', 'mysql')
from anarchia.settings_test import *  # noqa

if os.environ.get('NYZ_LOAD_ENGINE') == 'sqlite':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ['NYZ_LOAD_SQLITE']}}
else:
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.mysql', 'NAME': os.environ.get('NYZ_LOAD_DB', 'nyz_load'), 'USER': 'root', 'PASSWORD': 'rootpw',
        'HOST': '127.0.0.1', 'PORT': '33306',
        'OPTIONS': {'init_command': "SET sql_mode='STRICT_TRANS_TABLES'", 'charset': 'utf8mb4'}}}
    assert DATABASES['default']['NAME'] not in ('nyz', 'test_nyz'), 'refusing to touch shared DB'
DEBUG = os.environ.get('NYZ_DEBUG', '1') == '1'
