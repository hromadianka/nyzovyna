from .seo import html_lang


class ContentLanguageMiddleware:
    """LocaleMiddleware advertises the internal code 'ua'; send the valid BCP 47 tag 'uk' instead."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        code = response.headers.get('Content-Language')
        if code:
            response.headers['Content-Language'] = html_lang(code)
        return response
