from django.conf import settings
from django.core.cache import cache
from django.core.cache.utils import make_template_fragment_key

FRAGMENTS = ('site_menu', 'footer_categories')


def invalidate_menu_cache():
    """Drop the cached menu/footer fragments for every configured language."""
    keys = [
        make_template_fragment_key(name, [code])
        for name in FRAGMENTS
        for code, _ in settings.LANGUAGES
    ]
    cache.delete_many(keys)
