from django.contrib.auth.models import User
from django.db import models
import uuid
from django.utils.timezone import now


# Create your models here.


class Editor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.user.username

class Author(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    image = models.ImageField(upload_to='images/', default='card-example.png')
    name_en = models.CharField(max_length=100)
    description_en = models.TextField()
    name_ua = models.CharField(max_length=100)
    description_ua = models.TextField()

class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name_ua = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    order = models.IntegerField(default=0)

    def __str__(self):
        return self.name_ua

    class Meta:
        ordering = ['order']

class Article(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, null=True, blank=True, related_name='articles')
    name = models.TextField()
    text = models.TextField()
    image = models.ImageField(upload_to='images/', default='card-example.png')
    categories = models.ManyToManyField(Category, related_name='categories')
    language = models.CharField(max_length=2, choices=(('ua', 'Українська'), ('en', 'Англійська')), default='ua')
    created_at = models.DateTimeField(auto_now_add=True)
    publish_at = models.DateTimeField(default=now, blank=True, null=True)
    is_published = models.BooleanField(default=False)
    views = models.IntegerField(default=0)
    reactions = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    def should_be_published(self):
        return self.publish_at and self.publish_at <= now()

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