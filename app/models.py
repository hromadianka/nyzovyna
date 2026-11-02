from django.contrib.auth.models import User
from django.db import models
import uuid
from django.utils.timezone import now
from ckeditor.fields import RichTextField
from django.core.exceptions import ValidationError
from django.utils.text import slugify

MAX_CATEGORY_DEPTH = 5

_CYRILLIC = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ie', 'ж': 'zh', 'з': 'z',
    'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
    'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ь': '', 'ю': 'iu', 'я': 'ia', 'ё': 'e', 'ы': 'y', 'э': 'e', 'ъ': '',
}


def make_slug(text, fallback):
    """slugify() drops every non-Latin letter, which left Ukrainian names with an empty slug."""
    transliterated = ''.join(_CYRILLIC.get(ch, ch) for ch in (text or '').lower())
    return slugify(transliterated) or fallback


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
       if not self.slug:
           base_slug = make_slug(self.name_en or self.name_ua, 'author')
           slug = base_slug
           n = 1
           while Author.objects.filter(slug=slug).exists():
               slug = f'{base_slug}-{n}'
               n += 1
           self.slug = slug
       super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f'/authors/{self.slug}/'

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
        if not self.slug:
            base_slug = make_slug(self.name_ua or self.name_en, 'category')
            slug = base_slug
            n = 1
            while Category.objects.filter(slug=slug).exists():
                slug = f'{base_slug}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f'/category/{self.slug}/'

    def __str__(self):
        return self.name_ua

    def clean(self):
        if self.parent_id:
            chain = category_ancestors(self)
            if self.pk in {ancestor.pk for ancestor in chain} or self.parent_id == self.pk:
                raise ValidationError('A category cannot be its own ancestor.')
            if len(chain) >= MAX_CATEGORY_DEPTH:
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
    image = models.ImageField(upload_to='images/', default='card-example.png')
    categories = models.ManyToManyField(Category, related_name='categories')
    language = models.CharField(max_length=2, choices=(('ua', 'Українська'), ('en', 'Англійська')), default='ua')
    created_at = models.DateTimeField(auto_now_add=True)
    views = models.IntegerField(default=0)
    reactions = models.IntegerField(default=0)
    publish_at = models.DateTimeField(default=now, help_text="Час, коли стаття стане доступною")
    is_published = models.BooleanField(default=False)

    objects = ArticleQuerySet.as_manager()

    def save(self, *args, **kwargs):
        base_source = self.slug if self.slug else self.name
        base_slug = make_slug(base_source, 'article')

        slug = base_slug
        n = 1
        while Article.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f'{base_slug}-{n}'
            n += 1

        self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return f'/article/{self.slug}/'

    def __str__(self):
        return self.name

class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.CharField(max_length=100)
    text = models.TextField(default='')
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='comments')
    created_at = models.DateTimeField(auto_now_add=True)
    parent_comment = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

class AboutUsText(models.Model):
    text_ua = models.TextField(default='')
    text_en = models.TextField(default='')