from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import authenticate, login as auth_login


from .models import AboutUsText, Editor, Author, Category, Article, Comment, AboutUsText

# Create your views here.

def index(request):
    current_language = get_language()
    latest_articles = Article.objects.filter(language=current_language).order_by('-created_at')[:5]
    return render(request, 'index.html', {'latest_articles': latest_articles})

def about_us(request):
    about_us_text = AboutUsText.objects.get(pk=1)
    return render(request, 'about-us.html', {'about_us_text': about_us_text})

def category_articles(request, category_id):
    current_language = get_language()
    category = get_object_or_404(Category, pk=category_id)
    articles = Article.objects.filter(categories=category, language=current_language)
    return render(request, 'category.html', {'this_category': category, 'articles': articles})

def all_articles(request):
    language = get_language()
    articles = Article.objects.filter(language=language)
    return render(request, 'category.html', {'articles': articles})

def article_detail(request, article_id):
    article = get_object_or_404(Article, pk=article_id)
    article.views += 1
    article.save()
    comments = Comment.objects.filter(article=article).order_by('-created_at')
    comments_count = article.comments.count()
    translate = {
        'reply': _('Відповісти'),
        'enter_name': _('Введіть ім\'я'),
        'enter_comment': _('Введіть коментар')
    }
    return render(request, 'article.html', {'article': article, 'comments': comments, 'translate': translate, 'comments_count': comments_count})

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
    articles = Article.objects.all()
    about_us_text = AboutUsText.objects.get(pk=1)
    
    context = {
        'articles': articles,
        'about_us_text': about_us_text,
    }
    return render(request, 'editor-cabinet.html', context)

@login_required(login_url='/login')
def publish(request):

    if request.method == 'POST':
        article_name = request.POST.get('article_name')
        article_text = request.POST.get('article_text')
        article_image = request.FILES.get('article_image')
        language = request.POST.get('language')
        categories = request.POST.getlist('categories')

        all_categories = []

        for category_id in categories:
            category = Category.objects.get(id=category_id)
            all_categories.append(category)

            while category.parent:
                category = category.parent
                all_categories.append(category)

        if article_image:
            if article_image.content_type.startswith('image'):
                article = Article.objects.create(
                    name=article_name,
                    text=article_text,
                    image=article_image,
                    language=language
                )
                article.categories.add(*all_categories)
                return redirect('article', article_id=article.pk)
            else:
                return render(request, 'error.html', {'message': 'Неправильний файл.'})
        else:
            article = Article.objects.create(
                name=article_name,
                text=article_text,
                language=language
            )
            article.categories.add(*all_categories)
            return redirect('editor_cabinet')

    return render(request, 'editor-cabinet.html')

@login_required(login_url='/login')
def delete_article(request, article_id):
    article = get_object_or_404(Article, id=article_id)
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
def delete_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    if request.method == 'GET':
        category.delete()
        return JsonResponse({'success': True})

@login_required(login_url='/login')
def edit_article(request, article_id):
    article = get_object_or_404(Article, id=article_id)

    if request.method == 'POST':
        article_name = request.POST.get('article_name')
        article_text = request.POST.get('article_text')
        article_image = request.FILES.get('article_image')
        language = request.POST.get('language')
        categories = request.POST.getlist('categories')

        all_categories = []

        for category_id in categories:
            category = Category.objects.get(id=category_id)
            all_categories.append(category)

            while category.parent:
                category = category.parent
                all_categories.append(category)

        if article_image:
            if article_image.content_type.startswith('image'):
                article.name = article_name
                article.text = article_text
                article.image = article_image
                article.language = language
                article.categories.clear()
                article.categories.add(*all_categories)
                article.save()
                return redirect('article', article_id=article.pk)
            else:
                return render(request, 'error.html', {'message': 'Неправильний файл.'})
        else:
            article.name = article_name
            article.text = article_text
            article.language = language
            article.categories.clear()
            article.categories.add(*all_categories)
            article.save()
            return redirect('editor_cabinet')

    return render(request, 'edit_article.html', {'article': article})

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