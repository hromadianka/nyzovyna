"""
URL configuration for anarchia project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from app import views
from django.conf.urls.static import static
from django.conf import settings
from django.views.i18n import set_language
from app.feeds import LatestPostsFeed


urlpatterns = [
    path('admin/', admin.site.urls),
    path('ckeditor/', include('ckeditor_uploader.urls')),
    path('set-language/', set_language, name='set_language'),
    path('', views.index, name='home'),
    path('about-us', views.about_us, name='about_us'),
    path('authors', views.authors, name='authors'),
    path('author/<uuid:author_uuid>', views.author_detail, name='author_detail'),
    path('all', views.all_articles, name='all_articles'),
    path('category/<uuid:category_id>/', views.category_articles, name='category_articles'),
    path('category/<uuid:category_id>/delete/', views.delete_category, name='delete_category'),
    path('article/<uuid:article_id>/', views.article_detail, name='article'),
    path('comment', views.comment, name='comment'),
    path('login/', views.user_login, name='login'),
    path('editor-cabinet', views.editor_cabinet, name='editor_cabinet'),
    path('publish', views.publish, name='publish'),
    path('article/<uuid:article_id>/delete/', views.delete_article, name='delete'),
    path('article/<uuid:article_id>/edit/', views.edit_article, name='edit'),
    path('create-category/', views.create_category, name='create_category'),
    path('about-us-edit', views.about_us_edit, name='about_us_edit'),
    path('feed/', LatestPostsFeed(), name='post_feed'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
