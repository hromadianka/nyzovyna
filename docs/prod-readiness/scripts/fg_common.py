import json, re
from urllib.parse import urlparse
BASE = 'http://127.0.0.1:8124'
SP = '/private/tmp/claude-501/-Users-d-Development-Projects-nyz/5c322686-adbe-4aba-b94e-0bb59a636e3f/scratchpad'
VIEWPORTS = {'375': (375, 812), '768': (768, 1024), '1440': (1440, 900)}
PUBLIC = [
    ('home', '/'), ('all', '/all'), ('category_root', '/category/culture/'), ('category_nested', '/category/documentary/'),
    ('article_ua', '/article/test-article-0/'), ('article_en', '/article/test-article-1/'), ('authors', '/authors'),
    ('author_detail', '/authors/john-doe'), ('about_us', '/about-us'), ('search', '/search/?q=article'),
    ('login', '/login/'), ('404', '/does-not-exist/'),
]
AUTH = [
    ('editor_cabinet', '/editor-cabinet'), ('edit_article', '/article/test-article-0/edit/'),
    ('edit_author', '/authors/john-doe/edit'), ('comments_moderation', '/editor-cabinet/comments-moderation/'),
    ('category_order', '/editor-cabinet/categories/order/'),
]

def is_local(url):
    return urlparse(url).netloc in ('127.0.0.1:8124', '') or url.startswith(('data:', 'blob:', 'about:'))

def install_routes(ctx, external_log, recaptcha_stub=False):
    def handler(route):
        url = route.request.url
        if is_local(url):
            return route.continue_()
        external_log.append(url)
        if recaptcha_stub and 'recaptcha/api.js' in url:
            return route.fulfill(status=200, content_type='application/javascript', body='window.grecaptcha={ready:function(f){f()},render:function(){},execute:function(){},getResponse:function(){return "mock"}};')
        return route.abort('failed')
    ctx.route('**/*', handler)

def login(page):
    page.goto(BASE + '/login/')
    page.fill('input[name=login]', 'admin'); page.fill('input[name=password]', 'adminpass')
    page.click('button.btn'); page.wait_for_load_state('load')
