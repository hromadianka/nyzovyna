from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Article, Author, Book, Category


class HttpsSitemap(Sitemap):
    protocol = 'https'


class StaticPagesSitemap(HttpsSitemap):
    changefreq = 'daily'
    priority = 0.7

    def items(self):
        return ['home', 'all_articles', 'books', 'authors', 'about_us']

    def location(self, name):
        return reverse(name)


class CategorySitemap(HttpsSitemap):
    changefreq = 'daily'
    priority = 0.6

    def items(self):
        return Category.objects.filter(slug__isnull=False).order_by('pk')

    def location(self, obj):
        return reverse('category_articles', args=[obj.slug])


class ArticleSitemap(HttpsSitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Article.objects.public().order_by('pk')

    def lastmod(self, obj):
        return obj.publish_at

    def location(self, obj):
        return reverse('article', args=[obj.slug])


class AuthorSitemap(HttpsSitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return Author.objects.filter(slug__isnull=False).order_by('pk')

    def location(self, obj):
        return reverse('author_detail', args=[obj.slug])


# Drafts are excluded: a sitemap entry for a page that answers 404 would be reported as an error.
class BookSitemap(HttpsSitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return Book.objects.filter(is_published=True, slug__isnull=False).order_by('pk')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('book', args=[obj.slug])
