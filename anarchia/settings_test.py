"""Local test settings: reuse project settings but with sqlite, plain static storage and dummy env."""
import os

for key, value in {
    'DATABASE_URL': 'postgres://x:x@localhost/x',
    'DATABASE_NAME': 'x', 'DATABASE_USER': 'x', 'DATABASE_PASSWORD': 'x', 'DATABASE_HOST': 'x', 'CLOUDINARY_SECRET': 'x',
    'SECRET_KEY': 'test-only-secret-key-' + 'k8Zq3Vx9Lm2Pw7Rt5Yb1Nc4Hd6Jf0Sg' * 2,
    'CLOUDINARY_API_KEY': 'x', 'RECAPTCHA_PUBLIC_KEY': 'x', 'RECAPTCHA_PRIVATE_KEY': 'x',
}.items():
    os.environ.setdefault(key, value)

from anarchia.settings import *  # noqa: E402,F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
SILENCED_SYSTEM_CHECKS = ['captcha.recaptcha_test_key_error']
ALLOWED_HOSTS = ['*']
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
SECURE_SSL_REDIRECT = False

import atexit  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402

MEDIA_ROOT = tempfile.mkdtemp(prefix='nyz-test-media-')
atexit.register(shutil.rmtree, MEDIA_ROOT, ignore_errors=True)
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

if os.environ.get('NYZ_DB') == 'mysql':
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.mysql', 'NAME': 'nyz', 'USER': 'root', 'PASSWORD': 'rootpw',
        'HOST': '127.0.0.1', 'PORT': '33306',
        'OPTIONS': {'init_command': "SET sql_mode='STRICT_TRANS_TABLES'", 'charset': 'utf8mb4'},
        'TEST': {'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_0900_ai_ci'},
    }}
elif os.environ.get('NYZ_DB_FILE'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ['NYZ_DB_FILE']}}
