import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED_TAGS = {
    'a', 'b', 'blockquote', 'br', 'caption', 'code', 'div', 'em', 'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4',
    'h5', 'h6', 'hr', 'i', 'iframe', 'img', 'li', 'oembed', 'ol', 'p', 'pre', 's', 'source', 'span', 'strong',
    'sub', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul', 'video',
}
VOID_TAGS = {'br', 'hr', 'img', 'source'}
DROP_WITH_CONTENT = {'script', 'style', 'object', 'embed', 'template', 'noscript', 'textarea', 'title', 'svg', 'math'}
ALLOWED_ATTRS = {
    'a': {'href', 'title'},
    'img': {'src', 'alt', 'title', 'width', 'height'},
    'iframe': {'src', 'width', 'height', 'allowfullscreen'},
    'oembed': {'url'},
    'video': {'src', 'controls', 'width', 'height', 'poster'},
    'source': {'src', 'type'},
    'td': {'colspan', 'rowspan'},
    'th': {'colspan', 'rowspan'},
    'ol': {'start'},
}
GLOBAL_ATTRS = {'class', 'style'}
URL_ATTRS = {'href', 'src', 'poster', 'url'}
SAFE_SCHEMES = {'http', 'https', 'mailto', 'tel'}
EMBED_HOSTS = {'youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com',
               'youtu.be', 'player.vimeo.com', 'vimeo.com'}
SAFE_STYLE_PROPERTIES = {'text-align', 'width', 'height', 'aspect-ratio'}
SCHEME_RE = re.compile(r'^([a-z][a-z0-9+.-]*):')
CLASS_RE = re.compile(r'[^\w -]')
STYLE_VALUE_RE = re.compile(r'^[\w .%/-]+$')


def safe_url(tag, value):
    cleaned = re.sub(r'[\x00-\x20]+', '', value).lower()
    match = SCHEME_RE.match(cleaned)
    scheme = match.group(1) if match else ''
    if tag in ('iframe', 'oembed'):
        parts = urlsplit(value.strip())
        return parts.scheme == 'https' and parts.hostname in EMBED_HOSTS
    return scheme == '' or scheme in SAFE_SCHEMES


def safe_style(value):
    kept = []
    for declaration in value.split(';'):
        name, _, setting = declaration.partition(':')
        name, setting = name.strip().lower(), setting.strip()
        if name in SAFE_STYLE_PROPERTIES and STYLE_VALUE_RE.match(setting):
            kept.append(f'{name}:{setting}')
    return ';'.join(kept)


class Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open_tags = []
        self.dropping = None

    def handle_starttag(self, tag, attrs):
        if self.dropping:
            return
        if tag in DROP_WITH_CONTENT:
            self.dropping = tag
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag in ('iframe', 'oembed') and not any(
                name in ('src', 'url') and value and safe_url(tag, value) for name, value in attrs):
            return
        rendered = []
        for name, value in attrs:
            name = name.lower()
            value = value or ''
            if name not in ALLOWED_ATTRS.get(tag, set()) | GLOBAL_ATTRS:
                continue
            if name in URL_ATTRS and not safe_url(tag, value):
                continue
            if name == 'class':
                value = CLASS_RE.sub('', value)
            elif name == 'style':
                value = safe_style(value)
                if not value:
                    continue
            rendered.append(f' {name}="{escape(value, quote=True)}"')
        self.out.append(f'<{tag}{"".join(rendered)}>')
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and tag in ALLOWED_TAGS and self.open_tags and self.open_tags[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.dropping:
            if tag == self.dropping:
                self.dropping = None
            return
        if tag in self.open_tags:
            while self.open_tags:
                top = self.open_tags.pop()
                self.out.append(f'</{top}>')
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(escape(data, quote=False))

    def result(self):
        self.close()
        while self.open_tags:
            self.out.append(f'</{self.open_tags.pop()}>')
        return ''.join(self.out)


def sanitize_html(value):
    parser = Sanitizer()
    parser.feed(value or '')
    return parser.result()
