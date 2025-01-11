from django.contrib import admin
from .models import AboutUsText, Category, Article, Comment, Author

# Register your models here.

admin.site.register(Category)
admin.site.register(Article)
admin.site.register(Comment)
admin.site.register(AboutUsText)
admin.site.register(Author)