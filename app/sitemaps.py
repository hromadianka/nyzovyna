from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils.timezone import now
from .models import AboutUsText, Article, Author

class AboutUsSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return AboutUsText.objects.all()

    def lastmod(self, obj):
        return getattr(obj, 'updated_at', now())

    def location(self, obj):
        return reverse('about_us_detail', args=[obj.pk])


class ArticleSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Article.objects.filter(is_published=True, publish_at__lte=now())

    def lastmod(self, obj):
        return obj.publish_at

    def location(self, obj):
        return reverse('article_detail', args=[obj.slug])


class AuthorSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.6

    def items(self):
        return Author.objects.all()

    def lastmod(self, obj):
        return getattr(obj, 'updated_at', now())

    def location(self, obj):
        return reverse('author_detail', args=[obj.pk])
