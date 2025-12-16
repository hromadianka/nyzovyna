from django.contrib import admin
from .models import AboutUsText, Category, Article, Comment, Author

# Register your models here.

admin.site.register(Category)
admin.site.register(Article)
admin.site.register(AboutUsText)
admin.site.register(Author)

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('author', 'short_text', 'article', 'created_at', 'parent_comment')
    list_select_related = ('article', 'parent_comment')

    @admin.display(description='Текст')
    def short_text(self, obj):
        return obj.text[:50] + '…' if len(obj.text) > 50 else obj.text