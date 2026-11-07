import hashlib
import logging
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, logout as auth_logout, login as auth_login
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import make_aware, now
from django.utils.translation import get_language
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST, require_http_methods, require_safe

from .forms import CommentCaptchaForm
from .menu_cache import invalidate_menu_cache
from .models import AboutUsText, Article, ArticleSlugHistory, Author, Category, Comment, category_ancestors
from .permissions import editor_required, is_editor
from .ratelimit import client_id, hit
from .sanitize import sanitize_html
from .seo import absolute, page_meta, plain
from .uploads import validate_image

try:
    from cloudinary.exceptions import Error as CloudinaryError
except ImportError:  # pragma: no cover
    CloudinaryError = OSError

STORAGE_ERRORS = (OSError, CloudinaryError)
logger = logging.getLogger(__name__)
MAX_REPLY_DEPTH = 5
PAGE_SIZE = 24
COMMENTS_PER_PAGE = 20
MAX_COMMENTS_ON_PAGE = 300
MAX_COMMENT_LENGTH = 5000
MAX_SEARCH_LENGTH = 100
MAX_ORDER_ITEMS = 1000
INT32_MAX = 2 ** 31 - 1
BOT_MARKERS = ('bot', 'crawl', 'spider', 'slurp', 'curl', 'wget', 'python-requests', 'httpclient', 'headless')


def parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def clean_text(request, field, max_length):
    value = request.POST.get(field)
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > max_length:
        return None
    return value


def with_ancestors(categories):
    collected = {}
    for category in categories:
        collected[category.pk] = category
        for ancestor in category_ancestors(category):
            collected[ancestor.pk] = ancestor
    return list(collected.values())


def should_count_view(request, article):
    if request.method != 'GET':
        return False
    agent = request.META.get('HTTP_USER_AGENT', '').lower()
    if any(marker in agent for marker in BOT_MARKERS):
        return False
    if 'prefetch' in (request.headers.get('Purpose', '') + request.headers.get('Sec-Purpose', '')).lower():
        return False
    return cache.add(f'viewed:{article.pk}:{client_id(request)}', 1, 30 * 60)


def paginate(request, queryset):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get('page'))


@require_safe
def index(request):
    public = Article.objects.public().filter(language=get_language()).prefetch_related('categories')
    return render(request, 'index.html', {
        'latest_articles': public.order_by('-publish_at')[:5],
        'popular_articles': public.order_by('-views')[:10],
        'meta': page_meta(request),
    })


@require_safe
def about_us(request):
    return render(request, 'about-us.html', {
        'about_us_text': AboutUsText.objects.filter(pk=1).first(), 'meta': page_meta(request, _('Про нас')),
    })


@require_safe
def authors(request):
    return render(request, 'authors.html', {'authors': Author.objects.order_by('name_en'),
                                            'meta': page_meta(request, _('Автори'))})


@require_safe
def category_articles(request, slug):
    category = get_object_or_404(Category, slug=slug)
    if category.slug != slug:
        return redirect('category_articles', slug=category.slug, permanent=True)
    articles = Article.objects.public().filter(
        language=get_language(), categories__in=[category]).order_by('-publish_at', '-created_at')
    page = paginate(request, articles)
    title = category.name_en if get_language() == 'en' else category.name_ua
    return render(request, 'category.html', {'this_category': category, 'articles': page, 'page_obj': page,
                                             'meta': page_meta(request, title)})


@require_safe
def all_articles(request):
    articles = Article.objects.public().filter(language=get_language()).order_by('-publish_at', '-created_at')
    page = paginate(request, articles)
    return render(request, 'category.html', {'articles': page, 'page_obj': page,
                                             'meta': page_meta(request, _('Всі статті'))})


def load_comment_page(request, article):
    """One light query for the thread structure, one full query for the threads on the requested page."""
    rows = list(Comment.objects.filter(article=article).order_by('-created_at').values_list('id', 'parent_comment_id'))
    known = {row[0] for row in rows}
    children, roots = {}, []
    for comment_id, parent_id in rows:
        if parent_id is None or parent_id not in known:
            roots.append(comment_id)
        else:
            children.setdefault(parent_id, []).append(comment_id)
    page = Paginator(roots, COMMENTS_PER_PAGE).get_page(request.GET.get('cpage'))
    wanted, queue = [], list(page.object_list)
    while queue and len(wanted) < MAX_COMMENTS_ON_PAGE:
        comment_id = queue.pop(0)
        wanted.append(comment_id)
        queue.extend(children.get(comment_id, []))
    comments = list(Comment.objects.filter(pk__in=wanted).order_by('-created_at'))
    attach_replies(comments)
    return comments, page, len(rows)


def attach_replies(comments):
    """Fill `reply_list`; threads deeper than MAX_REPLY_DEPTH are shown flat at the last level, so the
    recursive template (and the stack) stays bounded however long a chain is posted."""
    for comment in comments:
        comment.reply_list = []
    by_id = {comment.id: comment for comment in comments}
    depth, shown_parent = {}, {}
    for comment in sorted(comments, key=lambda c: c.created_at):
        parent = by_id.get(comment.parent_comment_id)
        if parent is None or parent.id not in depth:
            depth[comment.id], shown_parent[comment.id] = 0, None
        else:
            depth[comment.id] = depth[parent.id] + 1
            shown_parent[comment.id] = parent if depth[parent.id] < MAX_REPLY_DEPTH else shown_parent[parent.id]
    for comment in comments:
        if shown_parent[comment.id] is not None:
            shown_parent[comment.id].reply_list.append(comment)


@require_safe
def article_meta(request, article):
    return page_meta(request, plain(article.name, 70), plain(article.text, 160),
                     image_url=absolute(request, article.image_url), kind='article',
                     noindex=not (article.is_published and article.publish_at <= now()))


def article_by_id(request, id):
    article = get_object_or_404(Article, pk=id)
    return redirect('article', slug=article.slug, permanent=True)


@require_safe
def article_detail(request, slug):
    try:
        article = get_object_or_404(Article.objects.select_related('author'), slug=slug)
        if article.slug != slug:
            return redirect('article', slug=article.slug, permanent=True)
    except Http404:
        moved = ArticleSlugHistory.objects.filter(slug=slug).select_related('article').first()
        if moved is None:
            raise
        return redirect('article', slug=moved.article.slug, permanent=True)
    is_preview = not (article.is_published and article.publish_at <= now())
    if is_preview and not is_editor(request.user):
        raise Http404
    if not is_preview and should_count_view(request, article):
        Article.objects.filter(pk=article.pk).update(views=F('views') + 1)
        article.views += 1
    all_articles = Article.objects.public().exclude(pk=article.pk).order_by('-views')[:2]

    comments, comments_page, comments_total = load_comment_page(request, article)

    parent_category = None
    article_categories = list(article.categories.all())
    if article_categories:
        parent_of = dict(Category.objects.values_list('id', 'parent_id'))
        parent_category, seen = article_categories[0].id, set()
        while parent_of.get(parent_category) and parent_category not in seen:
            seen.add(parent_category)
            parent_category = parent_of[parent_category]
    recommended_articles = []
    if parent_category:
        recommended_articles = Article.objects.public().filter(
            categories=parent_category).exclude(pk=article.pk).order_by('-views')[:2]
    translate = {
        'reply': _('Відповісти'),
        'enter_name': _('Введіть ім\'я'),
        'enter_comment': _('Введіть коментар')
    }
    return render(request, 'article.html', {
        'article': article,
        'comments': comments,
        'comments_page': comments_page,
        'translate': translate,
        'comments_count': comments_total,
        'captcha_form': CommentCaptchaForm(),
        'recommended_articles': recommended_articles,
        'all_articles': all_articles,
        'meta': article_meta(request, article),
    })


@require_http_methods(['GET', 'POST'])
def comment(request):
    if request.method != 'POST':
        return redirect('/')
    if hit('comment', request, limit=10, window=600):
        return HttpResponse('Too many comments. Try again later.', status=429)

    article_id = parse_uuid(request.POST.get('article_id'))
    if article_id is None:
        raise Http404
    article = get_object_or_404(Article.objects.public(), pk=article_id)

    if not CommentCaptchaForm(request.POST).is_valid():
        messages.error(request, gettext('Підтвердіть, що ви не робот, і спробуйте ще раз.'))
        return redirect('article', slug=article.slug)

    author = clean_text(request, 'author', 100)
    text = clean_text(request, 'text', MAX_COMMENT_LENGTH)
    if author is None or text is None:
        return HttpResponse('Invalid comment.', status=400)

    parent_comment = None
    parent_id = request.POST.get('parent_comment_id')
    if parent_id:
        parent_uuid = parse_uuid(parent_id)
        if parent_uuid is None:
            raise Http404
        parent_comment = get_object_or_404(Comment, pk=parent_uuid, article=article)

    fingerprint = hashlib.sha256(f'{article.pk}|{parent_id}|{author}|{text}'.encode()).hexdigest()
    if not cache.add(f'comment-dup:{client_id(request)}:{fingerprint}', 1, 60):
        return redirect('article', slug=article.slug)

    Comment.objects.create(article=article, author=author, text=text, parent_comment=parent_comment)
    return redirect('article', slug=article.slug)


@require_safe
def author_detail(request, slug):
    author = get_object_or_404(Author, slug=slug)
    if author.slug != slug:
        return redirect('author_detail', slug=author.slug, permanent=True)
    articles = Article.objects.public().filter(author=author).order_by('-publish_at', '-created_at')
    page = paginate(request, articles)
    english = get_language() == 'en'
    return render(request, 'author_detail.html', {
        'author': author, 'author_articles': page, 'page_obj': page,
        'meta': page_meta(request, author.name_en if english else author.name_ua,
                          plain(author.description_en if english else author.description_ua, 160),
                          image_url=author.image_url),
    })


@require_safe
def article_search(request):
    if hit('search', request, limit=60, window=60):
        return HttpResponse('Too many searches. Try again later.', status=429)
    query = request.GET.get('q', '').strip()[:MAX_SEARCH_LENGTH]

    if query:
        matches = Article.objects.public().filter(language=get_language()).filter(
            Q(name__icontains=query) | Q(search_text__icontains=query)).order_by('-publish_at', '-created_at')
    else:
        matches = Article.objects.none()
    page = paginate(request, matches)
    return render(request, 'search.html', {'query': query, 'results': page, 'page_obj': page,
                                          'meta': page_meta(request, _('Результати пошуку'), noindex=True)})


def user_login(request):
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('login'), password=request.POST.get('password'))
        if user is not None:
            auth_login(request, user)
            target = request.POST.get('next') or request.GET.get('next') or ''
            if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
                return redirect(target)
            return redirect('editor_cabinet')
        messages.error(request, gettext('Неправильний логін або пароль'))
    return render(request, 'login.html', {'meta': page_meta(request, _('Вхід'), noindex=True)})


@require_POST
def user_logout(request):
    auth_logout(request)
    return redirect('home')


# Editor views

def repeat_key(request, scope, *parts):
    fingerprint = hashlib.sha256('|'.join(str(part) for part in parts).encode()).hexdigest()
    return f'repeat:{scope}:{client_id(request)}:{fingerprint}'


def is_repeat(request, scope, *parts):
    """True when this client already sent the same form a moment ago (double click, retry after a timeout)."""
    return not cache.add(repeat_key(request, scope, *parts), 1, 30)


def forget_repeat(request, scope, *parts):
    """A submission that failed must not make the editor's retry look like a double click."""
    cache.delete(repeat_key(request, scope, *parts))


def form_error(request, template, context, message):
    return render(request, template, {**context, 'error_message': message}, status=400)


def storage_error(request, template, context):
    logger.exception('image storage failed for %s', request.path)
    return render(request, template, {**context, 'error_message': 'Не вдалося зберегти зображення. Спробуйте ще раз.'},
                  status=503)


def parse_article_form(request):
    """Validate the publish/edit form. Returns (values, error); nothing is written here."""
    name = clean_text(request, 'article_name', 1000)
    text = request.POST.get('article_text')
    language = request.POST.get('language')
    author_id = parse_uuid(request.POST.get('article_author'))
    if name is None or not (text or '').strip():
        return None, 'Заповніть назву і текст статті.'
    if language not in ('ua', 'en'):
        return None, 'Невідома мова.'
    author = Author.objects.filter(pk=author_id).first() if author_id else None
    if author is None:
        return None, 'Автор не знайдений.'

    category_ids = [parse_uuid(value) for value in request.POST.getlist('categories')]
    if None in category_ids:
        return None, 'Невірна категорія.'
    categories = with_ancestors(Category.objects.filter(pk__in=category_ids).select_related('parent'))

    is_published, publish_at, scheduled = True, now(), False
    publish_datetime = request.POST.get('publish_datetime')
    if request.POST.get('publish_option') == 'schedule' and publish_datetime:
        scheduled = True
        try:
            publish_at = make_aware(datetime.strptime(publish_datetime, '%Y-%m-%dT%H:%M'), ZoneInfo(settings.EDITOR_TIME_ZONE))
        except (ValueError, OverflowError):
            return None, 'Невірна дата публікації.'

    image = request.FILES.get('article_image')
    if image is not None:
        error = validate_image(image)
        if error:
            return None, error

    return {
        'name': name, 'text': sanitize_html(text), 'language': language, 'author': author,
        'categories': categories, 'is_published': is_published, 'publish_at': publish_at, 'image': image,
        'publish_now': not scheduled,
        'slug': (request.POST.get('article_slug') or '').strip(),
    }, None


@editor_required
def editor_cabinet(request):
    return render(request, 'editor-cabinet.html', {
        'articles': Article.objects.public().order_by('-publish_at', '-created_at').prefetch_related('categories'),
        'unpublished_articles': Article.objects.exclude(is_published=True, publish_at__lte=now())
                                               .order_by('publish_at', 'created_at').prefetch_related('categories'),
        'about_us_text': AboutUsText.objects.filter(pk=1).first(),
        'authors': Author.objects.all(),
    })


@editor_required
def publish(request):
    context = {'authors': Author.objects.all(), 'categories': Category.objects.all()}
    if request.method != 'POST':
        return render(request, 'editor-cabinet.html', context)

    values, error = parse_article_form(request)
    if error:
        return form_error(request, 'editor-cabinet.html', context, error)

    if is_repeat(request, 'article', values['name'], values['language'], values['author'].pk, values['text']):
        return redirect('editor_cabinet')

    article = Article(
        name=values['name'], text=values['text'], language=values['language'], author=values['author'],
        publish_at=values['publish_at'], is_published=values['is_published'],
    )
    if values['slug']:
        article.slug = values['slug']
    if values['image']:
        article.image = values['image']
    try:
        with transaction.atomic():
            article.save()
            article.categories.add(*values['categories'])
    except STORAGE_ERRORS:
        return storage_error(request, 'editor-cabinet.html', context)
    return redirect('article', slug=article.slug)


@editor_required
@require_POST
def delete_article(request, slug):
    get_object_or_404(Article, slug=slug).delete()
    return JsonResponse({'success': True})


@editor_required
@require_http_methods(['GET', 'POST'])
def create_category(request):
    if request.method != 'POST':
        return render(request, 'editor-cabinet.html')
    name_ua = clean_text(request, 'name_ua', 100)
    name_en = clean_text(request, 'name_en', 100)
    if name_ua is None or name_en is None:
        return HttpResponse('Invalid category name.', status=400)
    parent = None
    parent_id = request.POST.get('parent_id')
    if parent_id:
        parent_uuid = parse_uuid(parent_id)
        if parent_uuid is None:
            raise Http404
        parent = get_object_or_404(Category, pk=parent_uuid)
    if is_repeat(request, 'category', name_ua, name_en, parent_id):
        return redirect('editor_cabinet')
    category = Category(name_ua=name_ua, name_en=name_en, parent=parent)
    try:
        category.clean()
    except ValidationError:
        return HttpResponse('Categories are nested too deeply.', status=400)
    category.save()
    return redirect('editor_cabinet')


@editor_required
@require_POST
def delete_category(request, slug):
    get_object_or_404(Category, slug=slug).delete()
    return JsonResponse({'success': True})


@editor_required
def edit_article(request, slug):
    article = get_object_or_404(Article, slug=slug)
    context = {
        'article': article, 'authors': Author.objects.all(), 'categories': Category.objects.all(),
        'selected_category_ids': set(article.categories.values_list('id', flat=True)),
    }
    if request.method != 'POST':
        return render(request, 'edit_article.html', context)

    values, error = parse_article_form(request)
    if error:
        return form_error(request, 'edit_article.html', context, error)

    article.name, article.text, article.language = values['name'], values['text'], values['language']
    article.author = values['author']
    still_live = article.is_published and article.publish_at <= now()
    if not (values['publish_now'] and still_live):
        article.is_published, article.publish_at = values['is_published'], values['publish_at']
    fields = ['name', 'text', 'language', 'author', 'is_published', 'publish_at', 'slug']
    if values['image']:
        article.image = values['image']
        fields.append('image')
    article.slug = values['slug'] or article.slug
    try:
        with transaction.atomic():
            article.save(update_fields=fields)
            article.categories.set(values['categories'])
    except STORAGE_ERRORS:
        return storage_error(request, 'edit_article.html', context)
    return redirect('article', slug=article.slug)


@editor_required
@require_http_methods(['POST'])
def about_us_edit(request):
    text_ua, text_en = request.POST.get('new_text_ua'), request.POST.get('new_text_en')
    if text_ua is None or text_en is None:
        return HttpResponse('Invalid text.', status=400)
    about_us_text, _created = AboutUsText.objects.get_or_create(pk=1)
    about_us_text.text_ua, about_us_text.text_en = sanitize_html(text_ua), sanitize_html(text_en)
    about_us_text.save()
    return redirect('editor_cabinet')


def author_fields(request, prefix):
    names = [clean_text(request, f'{prefix}name_ua', 100), clean_text(request, f'{prefix}name_en', 100)]
    descriptions = [request.POST.get(f'{prefix}description_ua'), request.POST.get(f'{prefix}description_en')]
    if None in names or None in descriptions:
        return None
    return names + descriptions


@editor_required
@require_http_methods(['GET', 'POST'])
def create_new_author(request):
    if request.method != 'POST':
        return render(request, 'editor-cabinet.html')
    fields = author_fields(request, 'author_')
    image = request.FILES.get('author_image')
    if fields is None or (image is not None and validate_image(image)):
        return HttpResponse('Invalid author data.', status=400)
    name_ua, name_en, description_ua, description_en = fields
    if is_repeat(request, 'author', name_ua, name_en, description_ua, description_en):
        return redirect('editor_cabinet')
    author = Author(name_ua=name_ua, name_en=name_en, description_ua=description_ua, description_en=description_en)
    if image:
        author.image = image
    try:
        author.save()
    except STORAGE_ERRORS:
        return storage_error(request, 'editor-cabinet.html', {})
    return redirect('editor_cabinet')


@editor_required
def edit_author(request, slug):
    author = get_object_or_404(Author, slug=slug)
    if request.method != 'POST':
        return render(request, 'edit_author.html', {'author': author})
    fields = author_fields(request, '')
    image = request.FILES.get('author_image')
    if fields is None or (image is not None and validate_image(image)):
        return form_error(request, 'edit_author.html', {'author': author}, 'Невірні дані автора.')
    author.name_ua, author.name_en, author.description_ua, author.description_en = fields
    if image:
        author.image = image
    try:
        author.save()
    except STORAGE_ERRORS:
        return storage_error(request, 'edit_author.html', {'author': author})
    return redirect('author_detail', slug=author.slug)


@editor_required
def comments_moderation(request):
    comments = Comment.objects.select_related('article', 'parent_comment').order_by('-created_at')
    return render(request, 'comments_moderation.html', {'comments': comments})


@editor_required
@require_POST
def delete_comment(request, id):
    get_object_or_404(Comment, id=id).delete()
    return redirect('comments_moderation')


@editor_required
def category_order_editor(request):
    categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')
    return render(request, 'category_order.html', {'categories': categories})


def parse_order_payload(body):
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, list) or len(data) > MAX_ORDER_ITEMS:
        return None
    parsed = {}
    for item in data:
        if not isinstance(item, dict):
            return None
        category_id, order = parse_uuid(item.get('id')), item.get('order')
        if category_id is None or type(order) is not int or not -INT32_MAX <= order <= INT32_MAX:
            return None
        parsed[category_id] = order
    return parsed


@editor_required
@require_POST
def update_category_order(request):
    orders = parse_order_payload(request.body)
    if orders is None:
        return JsonResponse({'status': 'invalid payload'}, status=400)
    categories = list(Category.objects.filter(pk__in=orders))
    for category in categories:
        category.order = orders[category.pk]
    Category.objects.bulk_update(categories, ['order'])
    invalidate_menu_cache()  # bulk_update sends no signals
    return JsonResponse({'status': 'ok'})
