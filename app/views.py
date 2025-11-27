from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate, login as auth_login
from django.utils.timezone import now
from django.utils.timezone import make_aware
from datetime import datetime
from django.utils.text import slugify


from .models import AboutUsText, Editor, Author, Category, Article, Comment, AboutUsText

# Create your views here.

def index(request):
    current_language = get_language()
    latest_articles = Article.objects.filter(
        language = current_language, 
        is_published = True, 
    ).order_by('-publish_at')[:5]
    popular_articles = Article.objects.filter(
        language = current_language, 
        is_published = True, 
    ).order_by('-views')[:10]

    return render(request, 'index.html', {'latest_articles': latest_articles, 'popular_articles': popular_articles})

def about_us(request):
    about_us_text = AboutUsText.objects.get(pk=1)
    return render(request, 'about-us.html', {'about_us_text': about_us_text})

def authors(request):
    authors = Author.objects.all()
    return render(request, 'authors.html', {'authors': authors})

def category_articles(request, slug):
    current_language = get_language()
    category = get_object_or_404(Category, slug=slug)
    articles = Article.objects.filter(
        language = current_language, 
        categories__in = [category],
        is_published = True, 
    )
    return render(request, 'category.html', {'this_category': category, 'articles': articles})

def all_articles(request):
    language = get_language()
    articles = Article.objects.filter(
        language=language,
        is_published=True,
    )
    return render(request, 'category.html', {'articles': articles})

def article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug)
    article.views += 1
    article.save()
    all_articles = Article.objects.filter(is_published=True).exclude(pk=article.pk).order_by('-views')[:2]
    comments = Comment.objects.filter(article=article).order_by('-created_at')
    comments_count = article.comments.count()
    parent_category = None
    if article.categories.exists():
        parent_category = article.categories.first()
        while parent_category.parent:
            parent_category = parent_category.parent
    recommended_articles = []
    if parent_category:
        recommended_articles = Article.objects.filter(
            categories=parent_category,
            is_published=True
        ).exclude(pk=article.pk).order_by('-views')[:2]
    translate = {
        'reply': _('Відповісти'),
        'enter_name': _('Введіть ім\'я'),
        'enter_comment': _('Введіть коментар')
    }
    return render(request, 'article.html', {
        'article': article,
        'comments': comments,
        'translate': translate,
        'comments_count': comments_count,
        'recommended_articles': recommended_articles,
        'all_articles': all_articles
    })

def comment(request):

    if request.method == 'POST':
        article_id = request.POST.get('article_id')
        author = request.POST.get('author')
        text = request.POST.get('text')
        parent_comment_id = request.POST.get('parent_comment_id')

        article = get_object_or_404(Article, pk=article_id)

        if parent_comment_id:
            parent_comment = get_object_or_404(Comment, pk=parent_comment_id)
            comment = Comment.objects.create(
                article=article,
                author=author,
                text=text,
                parent_comment=parent_comment
            )
        else:
            comment = Comment.objects.create(
                article=article,
                author=author,
                text=text
            )

        depth = 0
        while comment.parent_comment:
            depth += 1
            comment = comment.parent_comment

        return redirect('article', article_id=article_id)

def author_detail(request, slug):
       author = get_object_or_404(Author, slug=slug)
       author_articles = Article.objects.filter(
        author=author,
        is_published=True,
       )
       return render(request, 'author_detail.html', {'author': author, 'author_articles': author_articles})

#Виды редактора

def user_login(request):
    if request.method == 'POST':
        login_username = request.POST.get('login')
        password = request.POST.get('password')
        user = authenticate(request, username=login_username, password=password)
        if user is not None:
            auth_login(request, user)
            return redirect('editor_cabinet')
        else:
            messages.error(request, 'Неправильний логін або пароль')
    return render(request, 'login.html')

@login_required(login_url='/login')
def editor_cabinet(request):
    articles = Article.objects.filter(is_published = True)
    unpublished_articles = Article.objects.filter(is_published = False)
    about_us_text = AboutUsText.objects.get(pk=1)
    authors = Author.objects.all()
    
    context = {
        'articles': articles,
        'unpublished_articles': unpublished_articles,
        'about_us_text': about_us_text,
        'authors': authors
    }
    return render(request, 'editor-cabinet.html', context)

@login_required(login_url='/login')
def publish(request):
    authors = Author.objects.all()
    categories = Category.objects.all()

    if request.method == 'POST':
        article_name = request.POST.get('article_name')
        article_text = request.POST.get('article_text')
        article_image = request.FILES.get('article_image')
        language = request.POST.get('language')
        category_ids = request.POST.getlist('categories')
        author_id = request.POST.get('article_author')
        publish_option = request.POST.get('publish_option')
        publish_datetime = request.POST.get('publish_datetime')
        article_slug_raw = request.POST.get('article_slug')

        if not author_id:
            return render(request, 'editor-cabinet.html', {
                'error_message': 'Автор не знайдений.',
                'authors': authors,
                'categories': categories,
            })

        try:
            author = Author.objects.get(id=author_id)
        except Author.DoesNotExist:
            return render(request, 'editor-cabinet.html', {
                'error_message': 'Автор не знайдений.',
                'authors': authors,
                'categories': categories,
            })

        all_categories = []
        for category_id in category_ids:
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                continue

            all_categories.append(category)
            parent = category.parent
            while parent:
                all_categories.append(parent)
                parent = parent.parent

        all_categories = list(set(all_categories))

        if publish_option == "schedule" and publish_datetime:
            is_published = False
            publish_date = make_aware(
                datetime.strptime(publish_datetime, "%Y-%m-%dT%H:%M")
            )
        else:
            publish_date = now()
            is_published = True

        article = Article(
            name=article_name,
            text=article_text,
            language=language,
            author=author,
            publish_at=publish_date,
            is_published=is_published,
        )

        if article_slug_raw:
            article.slug = article_slug_raw

        article.save()

        if all_categories:
            article.categories.add(*all_categories)

        if article_image:
            if article_image.content_type.startswith('image'):
                article.image = article_image
                article.save()
            else:
                return render(request, 'editor-cabinet.html', {
                    'error_message': 'Неправильний формат файлу.',
                    'authors': authors,
                    'categories': categories,
                })

        return redirect('article', slug=article.slug)

    return render(request, 'editor-cabinet.html', {
        'authors': authors,
        'categories': categories,
    })

@login_required(login_url='/login')
def delete_article(request, slug):
    article = get_object_or_404(Article, slug=slug)
    if request.method == 'GET':
        article.delete()
        return JsonResponse({'success': True})

@login_required(login_url='/login')
def create_category(request):
    if request.method == 'POST':
        name_ua = request.POST.get('name_ua')
        name_en = request.POST.get('name_en')
        parent_id =  request.POST.get('parent_id')
        if parent_id:
            parent = get_object_or_404(Category, pk=parent_id)
            new_category = Category.objects.create(name_ua=name_ua, name_en=name_en, parent=parent)
            return redirect('editor_cabinet')
        else:
            new_category = Category.objects.create(name_ua=name_ua, name_en=name_en)
            return redirect('editor_cabinet')
    return render(request, 'editor-cabinet.html')

@login_required(login_url='/login')
def delete_category(request, slug):
    category = get_object_or_404(Category, slug)
    if request.method == 'GET':
        category.delete()
        return JsonResponse({'success': True})

@login_required(login_url='/login')
def edit_article(request, slug):
    article = get_object_or_404(Article, slug=slug)
    authors = Author.objects.all()
    categories = Category.objects.all()

    if request.method == 'POST':
        article_name = request.POST.get('article_name')
        article_text = request.POST.get('article_text')
        article_image = request.FILES.get('article_image')
        author_id = request.POST.get('article_author')
        language = request.POST.get('language')
        category_ids = request.POST.getlist('categories')
        publish_option = request.POST.get('publish_option')
        publish_datetime = request.POST.get('publish_datetime')
        article_slug_raw = request.POST.get('article_slug')  # новое поле

        try:
            author = Author.objects.get(id=author_id)
        except Author.DoesNotExist:
            return render(request, 'edit_article.html', {
                'article': article,
                'authors': authors,
                'categories': categories,
                'error_message': 'Автор не знайдений.'
            })

        all_categories = []

        for category_id in category_ids:
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                continue

            all_categories.append(category)
            parent = category.parent
            while parent:
                all_categories.append(parent)
                parent = parent.parent

        all_categories = list(set(all_categories))

        if publish_option == "schedule" and publish_datetime:
            article.is_published = False
            article.publish_at = make_aware(
                datetime.strptime(publish_datetime, "%Y-%m-%dT%H:%M")
            )
        else:
            article.is_published = True
            article.publish_at = now()

        article.name = article_name
        article.text = article_text
        article.language = language
        article.author = author

        article.categories.clear()
        if all_categories:
            article.categories.add(*all_categories)

        if article_image:
            if article_image.content_type.startswith('image'):
                article.image = article_image
            else:
                return render(request, 'edit_article.html', {
                    'article': article,
                    'authors': authors,
                    'categories': categories,
                    'error_message': 'Неправильний формат файлу.'
                })

        if article_slug_raw is not None:
            article.slug = article_slug_raw.strip() or None

        article.save()

        return redirect('article', slug=article.slug)

    return render(request, 'edit_article.html', {
        'article': article,
        'authors': authors,
        'categories': categories,
    })



@login_required(login_url='/login')
def about_us_edit(request):
    if request.method == 'POST':
        new_text_ua = request.POST.get('new_text_ua')
        new_text_en = request.POST.get('new_text_en')
        about_us_text = AboutUsText.objects.get(pk=1)
        about_us_text.text_ua = new_text_ua
        about_us_text.text_en = new_text_en
        about_us_text.save()

        return redirect('editor_cabinet')

@login_required(login_url='/login')
def create_new_author(request):
    if request.method == 'POST':
        name_ua = request.POST.get('author_name_ua')
        name_en = request.POST.get('author_name_en')
        description_ua = request.POST.get('author_description_ua')
        description_en = request.POST.get('author_description_en')
        author_image = request.FILES.get('author_image') 

        new_author = Author.objects.create(
            name_ua=name_ua,
            name_en=name_en,
            description_ua=description_ua,
            description_en=description_en,
            image=author_image
        )

        return redirect('editor_cabinet')
    return render(request, 'editor-cabinet.html')

@login_required(login_url='/login')
def edit_author(request, slug):
       author = get_object_or_404(Author, slug=slug)
       if request.method == 'POST':
           name_ua = request.POST.get('name_ua')
           name_en = request.POST.get('name_en')
           description_ua = request.POST.get('description_ua')
           description_en = request.POST.get('description_en')
           author_image = request.FILES.get('author_image')

           author.name_ua = name_ua
           author.name_en = name_en
           author.description_en = description_en
           author.description_ua = description_ua
           if author_image:
               author.image = author_image
           author.save()
           return redirect('author_detail', author_id = author.id)
       return render(request, 'edit_author.html', {'author': author})

#@login_required(login_url='/login')
#def comments_moderation(request):
#    comments = Comment.objects.all()
    
#    return render(request, 'comments_moderation.html', {'comments': comments})

#@login_required(login_url='/login')
#def delete_comment(request, id):
#    comment = get_object_or_404(Comment, id=id)
#    if request.method == 'POST':
#        comment.delete()
#        return