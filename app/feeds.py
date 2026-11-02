from django.contrib.syndication.views import Feed
from django.urls import reverse, reverse_lazy
from django.utils.feedgenerator import Rss201rev2Feed
from django.utils.translation import get_language

from .models import Article
from .sanitize import sanitize_html
from .seo import plain, html_lang


class LocalizedRssFeed(Rss201rev2Feed):
    """The site's internal language code 'ua' is not a valid RSS/BCP 47 language; publish 'uk'."""

    def __init__(self, *args, **kwargs):
        kwargs['language'] = html_lang(kwargs.get('language'))
        super().__init__(*args, **kwargs)


class LatestPostsFeed(Feed):
    feed_type = LocalizedRssFeed
    title = 'Nyzovyna'
    link = reverse_lazy('home')
    description = 'New articles on Nyzovyna.'

    def items(self):
        return Article.objects.public().filter(language=get_language()).order_by('-publish_at')[:5]

    def item_title(self, item):
        return item.name

    def item_description(self, item):
        return plain(sanitize_html(item.text), 500)

    def item_pubdate(self, item):
        return item.publish_at

    def item_link(self, item):
        return reverse('article', args=[item.slug])
