import logging
import os
import re

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import get_language, gettext_lazy as _
from django.views.decorators.http import require_POST, require_http_methods, require_safe

from .models import Book, BookFile
from .permissions import editor_required, is_editor
from .sanitize import sanitize_html
from .seo import absolute, page_meta
from .uploads import validate_image, validate_pdf
from .views import STORAGE_ERRORS, clean_text, forget_repeat, is_repeat, paginate, parse_uuid, should_count_view

logger = logging.getLogger(__name__)
MAX_SUMMARY_LENGTH = 400
# A browser omits an empty file input but still posts its label, so rows are paired by number, not by position.
FILE_FIELD = re.compile(r'^book_file_(\d+)$')


@require_safe
def book_list(request):
    books = Book.objects.filter(is_published=True, language=get_language())
    page = paginate(request, books)
    return render(request, 'books.html', {'books': page, 'page_obj': page,
                                          'meta': page_meta(request, _('Бібліотека'))})


@require_safe
def book_detail(request, slug):
    book = get_object_or_404(Book.objects.prefetch_related('files'), slug=slug)
    # A draft is a preview for editors only; for everyone else it must look like a page that does not exist.
    if not book.is_published and not is_editor(request.user):
        raise Http404
    return render(request, 'book.html', {
        'book': book,
        'meta': page_meta(request, book.title, book.summary, image_url=absolute(request, book.cover_url),
                          kind='book', noindex=not book.is_published),
    })


@require_safe
def book_download(request, slug, file_id):
    # The slug in the URL must match the file's own book, so a file id cannot be fetched through another book's page.
    book_file = get_object_or_404(BookFile.objects.select_related('book'), pk=file_id, book__slug=slug)
    if book_file.book.is_published:
        # Same rules as article views: link previews, bots and HEAD requests are not readers.
        if should_count_view(request, book_file):
            BookFile.objects.filter(pk=book_file.pk).update(downloads=F('downloads') + 1)
    elif not is_editor(request.user):
        raise Http404
    return redirect(book_file.file.url)


# Editor views

def parse_book_form(request):
    """Validate the book form. Returns (values, error); nothing is written here."""
    title = clean_text(request, 'title', 300)
    summary = clean_text(request, 'summary', MAX_SUMMARY_LENGTH)
    annotation = request.POST.get('annotation')
    language = request.POST.get('language')
    if title is None or summary is None or not (annotation or '').strip():
        return None, 'Заповніть назву, короткий опис та анотацію (опис — до 400 символів).'
    if language not in ('ua', 'en'):
        return None, 'Невідома мова.'
    book_author = (request.POST.get('book_author') or '').strip()
    if len(book_author) > 200:
        return None, 'Імʼя автора завелике.'

    cover = request.FILES.get('cover')
    if cover is not None:
        error = validate_image(cover)
        if error:
            return None, error
    files = []
    for number in sorted(int(m.group(1)) for m in map(FILE_FIELD.match, request.FILES) if m):
        upload = request.FILES[f'book_file_{number}']
        error = validate_pdf(upload)
        if error:
            return None, f'{upload.name}: {error}'
        label = (request.POST.get(f'file_label_{number}') or '').strip()[:100]
        files.append((upload, label or os.path.splitext(upload.name)[0][:100]))
    return {
        'title': title, 'summary': summary, 'annotation': sanitize_html(annotation), 'language': language,
        'book_author': book_author, 'is_published': request.POST.get('is_published') == 'on', 'cover': cover,
        'files': files,
        'delete_file_ids': [uid for uid in map(parse_uuid, request.POST.getlist('delete_files')) if uid],
    }, None


def attach_files(book, files):
    # New files go after the existing ones so the buttons keep the order the editor chose.
    last = book.files.aggregate(last=Max('order'))['last']
    start = 0 if last is None else last + 1
    for offset, (upload, label) in enumerate(files):
        BookFile.objects.create(book=book, file=upload, label=label, order=start + offset)


def editor_context(**extra):
    return {'book_max_mb': settings.BOOK_MAX_FILE_BYTES // (1024 * 1024), **extra}


def remember_input(book, post):
    """Put what the editor typed onto an unsaved copy, so a rejected form is not shown blank."""
    book.title, book.book_author = post.get('title', ''), post.get('book_author', '')
    book.summary, book.annotation = post.get('summary', ''), post.get('annotation', '')
    book.language, book.is_published = post.get('language', 'ua'), post.get('is_published') == 'on'
    return book


def book_form_error(request, template, context, message, status=400):
    return render(request, template, {**context, 'error_message': message}, status=status)


def book_storage_error(request, template, context):
    # 503, not 400: the editor's input was fine, the storage is what failed, and a retry may succeed.
    logger.exception('book file storage failed for %s', request.path)
    return book_form_error(request, template, context, 'Не вдалося зберегти файли. Спробуйте ще раз.', status=503)


@editor_required
@require_http_methods(['GET', 'POST'])
def book_cabinet(request):
    context = editor_context(books=Book.objects.all())
    if request.method != 'POST':
        return render(request, 'books_cabinet.html', context)
    context['book'] = remember_input(Book(), request.POST)
    values, error = parse_book_form(request)
    if error:
        return book_form_error(request, 'books_cabinet.html', context, error)
    repeat_parts = ('book', values['title'], values['language'], values['summary'], values['annotation'])
    if is_repeat(request, *repeat_parts):
        return redirect('book_cabinet')
    book = Book(title=values['title'], summary=values['summary'], annotation=values['annotation'],
                language=values['language'], book_author=values['book_author'],
                is_published=values['is_published'])
    if values['cover']:
        book.cover = values['cover']
    try:
        # One transaction, so a failed upload does not leave a book without the files the editor attached.
        with transaction.atomic():
            book.save()
            attach_files(book, values['files'])
    except STORAGE_ERRORS:
        # Otherwise the retry within 30 s is swallowed as a double click and nothing is created.
        forget_repeat(request, *repeat_parts)
        return book_storage_error(request, 'books_cabinet.html', context)
    return redirect('book', slug=book.slug)


@editor_required
@require_http_methods(['GET', 'POST'])
def book_edit(request, slug):
    book = get_object_or_404(Book, slug=slug)
    context = editor_context(book=book)
    if request.method != 'POST':
        return render(request, 'book_edit.html', context)
    remember_input(book, request.POST)
    values, error = parse_book_form(request)
    if error:
        return book_form_error(request, 'book_edit.html', context, error)
    book.title, book.summary, book.annotation = values['title'], values['summary'], values['annotation']
    book.language, book.book_author, book.is_published = values['language'], values['book_author'], values['is_published']
    if values['cover']:
        book.cover = values['cover']
    try:
        with transaction.atomic():
            book.save()
            book.files.filter(pk__in=values['delete_file_ids']).delete()
            attach_files(book, values['files'])
    except STORAGE_ERRORS:
        return book_storage_error(request, 'book_edit.html', context)
    return redirect('book', slug=book.slug)


@editor_required
@require_POST
def book_delete(request, slug):
    get_object_or_404(Book, slug=slug).delete()
    return JsonResponse({'success': True})
