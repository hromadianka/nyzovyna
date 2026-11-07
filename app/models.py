from django.contrib.auth.models import User
from django.db import models
import uuid
import logging

from django.conf import settings
from django.core.files.storage import storages
from django.templatetags.static import static
from django.utils.html import strip_tags
from django.utils.timezone import now
from ckeditor.fields import RichTextField
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.db import IntegrityError, transaction
from .slugs import make_slug, unique_slug

MAX_CATEGORY_DEPTH = 5
PLACEHOLDER_IMAGE = 'img/card-example.png'
logger = logging.getLogger(__name__)


def safe_image_url(image):
    """URL of an ImageField file; a missing file or a storage hiccup must not break the whole page."""
    try:
        return image.url if image else static(PLACEHOLDER_IMAGE)
    except Exception:
        logger.exception('image url failed for %r', getattr(image, 'name', image))
        return f'{settings.STATIC_URL}{PLACEHOLDER_IMAGE}'



def save_with_unique_slug(instance, build_base, max_length, save, attempts=5):
    """Two writers can pick the same free slug; the unique index rejects the loser, which simply retries."""
    for attempt in range(attempts):
        base = build_base()
        if attempt < 2:
            instance.slug = unique_slug(type(instance), base, max_length, pk=instance.pk)
        else:
            tag = f'-{uuid.uuid4().hex[:8]}'
            instance.slug = f'{base[:max_length - len(tag)].rstrip("-")}{tag}'
        try:
            with transaction.atomic():
                return save()
        except IntegrityError:
            if attempt == attempts - 1:
                raise


def category_ancestors(category):
    """Parents from nearest to root, stopping if the chain loops back on itself."""
    chain, seen = [], {category.pk}
    parent = category.parent
    while parent is not None and parent.pk not in seen:
        chain.append(parent)
        seen.add(parent.pk)
        parent = parent.parent
    return chain

# Create your models here.


class Editor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.user.username

class Author(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    image = models.ImageField(upload_to='images/', default='card-example.png')
    name_en = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True)
    #slug = models.SlugField(max_length=200, blank=True, null=True)
    description_en = models.TextField()
    name_ua = models.CharField(max_length=100)
    description_ua = models.TextField()

    def save(self, *args, **kwargs):
        if self.slug:
            return super().save(*args, **kwargs)
        save_with_unique_slug(self, lambda: make_slug(self.name_en or self.name_ua, 'author'), 100,
                              lambda: super(Author, self).save(*args, **kwargs))

    @property
    def image_url(self):
        return safe_image_url(self.image)

    def get_absolute_url(self):
        return reverse('author_detail', args=[self.slug])

    def __str__(self):
        return self.name_en

class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name_ua = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    #slug = models.SlugField(max_length=200, blank=True, null=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    order = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        if self.slug:
            return super().save(*args, **kwargs)
        save_with_unique_slug(self, lambda: make_slug(self.name_ua or self.name_en, 'category'), 100,
                              lambda: super(Category, self).save(*args, **kwargs))

    def get_absolute_url(self):
        return reverse('category_articles', args=[self.slug])

    def __str__(self):
        return self.name_ua

    def clean(self):
        if not self.parent_id:
            return
        if self.parent_id == self.pk:
            raise ValidationError('A category cannot be its own ancestor.')
        depth, seen, parent = 0, set(), self.parent
        while parent is not None and parent.pk not in seen:
            if parent.pk == self.pk:
                raise ValidationError('A category cannot be its own ancestor.')
            seen.add(parent.pk)
            depth += 1
            parent = parent.parent
        if depth > MAX_CATEGORY_DEPTH:
            raise ValidationError(f'Categories can be nested at most {MAX_CATEGORY_DEPTH} levels deep.')

    class Meta:
        ordering = ['order']

class ArticleQuerySet(models.QuerySet):
    def public(self):
        return self.filter(is_published=True, publish_at__lte=now())


class Article(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(Author, on_delete=models.SET_NULL, null=True, blank=True, related_name='articles')
    name = models.TextField()
    #slug = models.SlugField(max_length=200, blank=True, null=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True, null=True)
    text = RichTextField()
    search_text = models.TextField(blank=True, default='', editable=False)
    image = models.ImageField(upload_to='images/', default='card-example.png')
    categories = models.ManyToManyField(Category, related_name='categories')
    language = models.CharField(max_length=2, choices=(('ua', 'Українська'), ('en', 'Англійська')), default='ua')
    created_at = models.DateTimeField(auto_now_add=True)
    views = models.IntegerField(default=0)
    reactions = models.IntegerField(default=0)
    publish_at = models.DateTimeField(default=now, help_text="Час, коли стаття стане доступною")
    is_published = models.BooleanField(default=False)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['language', 'is_published', '-publish_at'], name='art_lang_pub_date'),
            models.Index(fields=['language', 'is_published', '-views'], name='art_lang_pub_views'),
            models.Index(fields=['is_published', '-views'], name='art_pub_views'),
        ]

    def save(self, *args, **kwargs):
        self.search_text = strip_tags(self.text or '')
        if kwargs.get('update_fields') is not None and 'text' in kwargs['update_fields']:
            kwargs['update_fields'] = {*kwargs['update_fields'], 'search_text'}
        source = self.slug or self.name
        previous = None if self._state.adding else Article.objects.filter(pk=self.pk).values_list('slug', flat=True).first()
        save_with_unique_slug(self, lambda: make_slug(source, 'article'), 200,
                              lambda: super(Article, self).save(*args, **kwargs))
        ArticleSlugHistory.objects.filter(slug=self.slug).delete()
        if previous and previous != self.slug:
            ArticleSlugHistory.objects.update_or_create(slug=previous, defaults={'article': self})

    @property
    def image_url(self):
        return safe_image_url(self.image)

    def get_absolute_url(self):
        return reverse('article', args=[self.slug])

    def __str__(self):
        return self.name

class ArticleSlugHistory(models.Model):
    """Former slugs of an article, so links to the old URL keep working after the slug is edited."""
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='old_slugs')
    slug = models.SlugField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.CharField(max_length=100)
    text = models.TextField(default='')
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    created_at = models.DateTimeField(auto_now_add=True)
    parent_comment = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

    def clean(self):
        if self.parent_comment_id:
            if self.parent_comment_id == self.pk:
                raise ValidationError('A comment cannot reply to itself.')
            if self.parent_comment.article_id != self.article_id:
                raise ValidationError('A reply must belong to the same article as its parent.')

class AboutUsText(models.Model):
    text_ua = models.TextField(default='')
    text_en = models.TextField(default='')

def book_storage():
    """Django calls this when the model classes load; tests and local runs point the 'books' alias at the file system."""
    return storages['books']


def book_file_path(instance, filename):
    return f'books/{instance.book.slug}-{uuid.uuid4().hex[:8]}.pdf'


class Book(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200, unique=True, blank=True, null=True)
    book_author = models.CharField(max_length=200, blank=True)
    summary = models.TextField(max_length=400)
    annotation = RichTextField()
    # No default file, unlike articles: a name that points to nothing in the storage gives a broken image.
    cover = models.ImageField(upload_to='covers/', blank=True)
    language = models.CharField(max_length=2, choices=(('ua', 'Українська'), ('en', 'Англійська')), default='ua')
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # The sitemap's lastmod: crawlers revisit a book only when this changes, not on its creation date.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.slug:
            return super().save(*args, **kwargs)
        save_with_unique_slug(self, lambda: make_slug(self.title, 'book'), 200,
                              lambda: super(Book, self).save(*args, **kwargs))

    @property
    def cover_url(self):
        return safe_image_url(self.cover)

    def get_absolute_url(self):
        return reverse('book', args=[self.slug])

    def __str__(self):
        return self.title


class BookFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='files')
    # 255, not Django's default 100: Cloudinary cuts the name to max_length and a raw file needs its extension
    file = models.FileField(upload_to=book_file_path, storage=book_storage, max_length=255)
    label = models.CharField(max_length=100)
    # Stored at upload: asking Cloudinary for the size of every file would be a network call per page view.
    size = models.PositiveIntegerField(default=0, editable=False)
    downloads = models.PositiveIntegerField(default=0, editable=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'pk']

    def save(self, *args, **kwargs):
        if self._state.adding and self.file:
            self.size = self.file.size
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label
