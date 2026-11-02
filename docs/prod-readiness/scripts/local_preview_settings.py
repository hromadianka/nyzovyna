"""Settings for looking at the site in a browser on http://127.0.0.1:8000 (not for production)."""
from fg_settings import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
STORAGES = {**STORAGES, 'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'}}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
RECAPTCHA_PUBLIC_KEY = '6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
RECAPTCHA_PRIVATE_KEY = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'
SILENCED_SYSTEM_CHECKS = ['captcha.recaptcha_test_key_error']
