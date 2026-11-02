from django.urls import reverse_lazy, reverse
from django.contrib.syndication.views import Feed
from .models import Article
from .sanitize import sanitize_html
from django.utils.timezone import now
from django.utils.translation import get_language

class LatestPostsFeed(Feed):
    title = 'Nyzovyna'
    link = reverse_lazy('home')
    description = 'New articles on Nyzovyna.'

    def items(self):
        current_language = get_language()
        return Article.objects.filter(language=current_language, is_published=True, publish_at__lte=now()).order_by('-created_at')[:5]

    def item_title(self, item):
        return item.name

    def item_description(self, item):
        return sanitize_html(item.text)

    def item_pubdate(self, item):
        return item.created_at

    def item_link(self, item):
        return reverse('article', args=[item.slug])
