from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.utils.translation import get_language, gettext as _

SITE_NAME = 'Низовина'
BCP47 = {'ua': 'uk', 'en': 'en'}
OG_LOCALE = {'ua': 'uk_UA', 'en': 'en_US'}


def html_lang(code=None):
    code = code or get_language()
    return BCP47.get(code, code)


def plain(text, limit):
    return Truncator(strip_tags(text or '').replace('\n', ' ').strip()).chars(limit)


def absolute(request, url):
    return url if url.startswith(('http://', 'https://')) else request.build_absolute_uri(url)


def page_meta(request, title='', description='', image_url='', kind='website', noindex=False):
    tagline = _('журнал сучасної лібертарної думки')
    return {
        'title': f'{title} — {SITE_NAME}' if title else f'{SITE_NAME} — {tagline}',
        'description': description if len(description) >= 20 else f'{SITE_NAME} — {tagline}',
        'canonical': request.build_absolute_uri(request.path),
        'og_type': kind,
        'og_image': absolute(request, image_url or static('img/logo.png')),
        'og_locale': OG_LOCALE.get(get_language(), 'uk_UA'),
        'noindex': noindex,
    }
