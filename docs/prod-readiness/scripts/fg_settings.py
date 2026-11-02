"""Local-only settings for F/G audit: settings_test + mocked reCAPTCHA server verification (no network)."""
from anarchia.settings_test import *  # noqa
from captcha import client as _c

class _Ok:
    is_valid = True
    error_codes = []
    extra_data = {}
_c.submit = lambda *a, **k: _Ok()

import os as _os
MEDIA_ROOT = _os.environ.get('NYZ_MEDIA_ROOT', MEDIA_ROOT)
