"""Local test settings: reuse project settings but with sqlite, plain static storage and dummy env."""
import os

for key, value in {
    'DATABASE_URL': 'postgres://x:x@localhost/x',
    'DATABASE_NAME': 'x', 'DATABASE_USER': 'x', 'DATABASE_PASSWORD': 'x', 'DATABASE_HOST': 'x', 'CLOUDINARY_SECRET': 'x',
}.items():
    os.environ.setdefault(key, value)

from anarchia.settings import *  # noqa: E402,F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
SILENCED_SYSTEM_CHECKS = ['captcha.recaptcha_test_key_error']
ALLOWED_HOSTS = ['*']
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
SECURE_SSL_REDIRECT = False
