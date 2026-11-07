from django.test import TestCase

from app.models import Book


class BookModelTests(TestCase):
    def test_slug_is_transliterated_from_title(self):
        book = Book.objects.create(title='Людська дія', summary='s', annotation='<p>a</p>')
        self.assertEqual(book.slug, 'liudska-diia')

    def test_same_title_gets_distinct_slugs(self):
        first = Book.objects.create(title='Назва', summary='s', annotation='a')
        second = Book.objects.create(title='Назва', summary='s', annotation='a')
        self.assertNotEqual(first.slug, second.slug)

    def test_book_is_unpublished_by_default(self):
        self.assertFalse(Book.objects.create(title='T', summary='s', annotation='a').is_published)

    def test_cover_falls_back_to_static_placeholder(self):
        book = Book.objects.create(title='T', summary='s', annotation='a')
        self.assertFalse(book.cover)
        self.assertIn('card-example', book.cover_url)
        self.assertTrue(book.cover_url.startswith('/static/'))


from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import SimpleTestCase, override_settings  # noqa: E402

from app.uploads import validate_pdf  # noqa: E402

PDF = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'


def pdf(name='book.pdf', content=PDF):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


class ValidatePdfTests(SimpleTestCase):
    def test_accepts_a_real_pdf(self):
        upload = pdf()
        self.assertIsNone(validate_pdf(upload))
        self.assertEqual(upload.read(5), b'%PDF-', 'the file pointer must be rewound for saving')

    def test_rejects_other_extension(self):
        self.assertIsNotNone(validate_pdf(pdf('book.exe')))

    def test_rejects_content_that_is_not_a_pdf(self):
        self.assertIsNotNone(validate_pdf(pdf(content=b'<html>not a pdf</html>')))

    def test_rejects_empty_file(self):
        self.assertIsNotNone(validate_pdf(pdf(content=b'')))

    @override_settings(BOOK_MAX_FILE_BYTES=len(PDF) - 1)
    def test_rejects_file_over_the_configured_limit(self):
        self.assertIsNotNone(validate_pdf(pdf()))

    @override_settings(BOOK_MAX_FILE_BYTES=len(PDF))
    def test_accepts_file_exactly_at_the_limit(self):
        self.assertIsNone(validate_pdf(pdf()))


import importlib  # noqa: E402
import re  # noqa: E402

from .helpers import Base  # noqa: E402


class BookFileModelTests(Base):
    def setUp(self):
        super().setUp()
        self.book = Book.objects.create(title='Людська дія', summary='s', annotation='a')

    def attach(self, name='scan.pdf', label='PDF'):
        from app.models import BookFile
        return BookFile.objects.create(book=self.book, label=label, file=pdf(name))

    def test_file_is_stored_under_the_book_slug_with_a_random_suffix(self):
        stored = self.attach('Original Name.pdf').file.name
        self.assertRegex(stored, r'^books/liudska-diia-[0-9a-f]{8}\.pdf$')

    def test_size_is_recorded_on_first_save(self):
        self.assertEqual(self.attach().size, len(PDF))

    def test_two_uploads_of_the_same_name_do_not_collide(self):
        self.assertNotEqual(self.attach().file.name, self.attach().file.name)

    def test_deleting_the_book_deletes_its_files(self):
        from app.models import BookFile
        self.attach()
        self.book.delete()
        self.assertEqual(BookFile.objects.count(), 0)

    def test_files_are_listed_by_order_then_creation(self):
        from app.models import BookFile
        late = BookFile.objects.create(book=self.book, label='b', file=pdf(), order=2)
        early = BookFile.objects.create(book=self.book, label='a', file=pdf(), order=1)
        self.assertEqual(list(self.book.files.all()), [early, late])


class ProductionBookStorageTests(SimpleTestCase):
    def test_book_files_use_cloudinary_raw_storage(self):
        storages = importlib.import_module('anarchia.settings').STORAGES
        self.assertEqual(storages['books']['BACKEND'], 'cloudinary_storage.storage.RawMediaCloudinaryStorage')


from django.urls import reverse  # noqa: E402

from .helpers import html_of  # noqa: E402


def mk_book(title='Книга', published=True, language='ua', files=1, **kw):
    from app.models import BookFile
    kw.setdefault('summary', 'Коротко про книгу')
    kw.setdefault('annotation', '<p>Аннотація</p>')
    book = Book.objects.create(title=title, is_published=published, language=language, **kw)
    for number in range(files):
        BookFile.objects.create(book=book, label=f'PDF {number + 1}', file=pdf(), order=number)
    return book


class BookListTests(Base):
    def test_lists_published_books_of_the_current_language_only(self):
        mk_book('Українська книга')
        mk_book('Прихована', published=False)
        mk_book('English book', language='en')
        html = html_of(self.get_ok('/books'))
        self.assertIn('Українська книга', html)
        self.assertNotIn('Прихована', html)
        self.assertNotIn('English book', html)

    def test_english_cookie_switches_the_list(self):
        mk_book('Українська книга')
        mk_book('English book', language='en')
        self.client.cookies['django_language'] = 'en'
        html = html_of(self.get_ok('/books'))
        self.assertIn('English book', html)
        self.assertNotIn('Українська книга', html)

    def test_card_shows_summary_and_links_to_the_book(self):
        book = mk_book('Людська дія', summary='Трактат про економіку')
        html = html_of(self.get_ok('/books'))
        self.assertIn('Трактат про економіку', html)
        self.assertIn(reverse('book', args=[book.slug]), html)

    def test_list_is_paginated(self):
        for number in range(25):
            mk_book(f'Книга {number:02d}', files=0)
        self.assertEqual(len(self.get_ok('/books').context['books']), 24)
        self.assertEqual(len(self.get_ok('/books?page=2').context['books']), 1)

    def test_empty_library_still_renders(self):
        self.get_ok('/books')


class BookDetailTests(Base):
    def test_shows_title_author_and_annotation(self):
        book = mk_book('Людська дія', book_author='Людвіг фон Мізес', annotation='<p>Велика <b>аннотація</b></p>')
        html = html_of(self.get_ok(book.get_absolute_url()))
        for text in ('Людська дія', 'Людвіг фон Мізес', 'Велика <b>аннотація</b>'):
            self.assertIn(text, html)

    def test_annotation_is_sanitized(self):
        book = mk_book(annotation='<p>ok</p><script>alert(1)</script>')
        self.assertNotIn('alert(1)', html_of(self.get_ok(book.get_absolute_url())))

    def test_summary_is_the_meta_description(self):
        book = mk_book(summary='Достатньо довге коротке описання книги')
        self.assertIn('content="Достатньо довге коротке описання книги"', html_of(self.get_ok(book.get_absolute_url())))

    def test_each_file_gets_a_download_button_with_label_and_size(self):
        book = mk_book(files=2)
        html = html_of(self.get_ok(book.get_absolute_url()))
        for book_file in book.files.all():
            self.assertIn(reverse('book_download', args=[book.slug, book_file.pk]), html)
            self.assertIn(book_file.label, html)
        self.assertIn('bytes', html)

    def test_book_without_files_has_no_download_section(self):
        book = mk_book(files=0)
        self.assertNotIn('/download/', html_of(self.get_ok(book.get_absolute_url())))

    def test_unpublished_book_is_a_404_for_visitors(self):
        book = mk_book(published=False)
        self.assertEqual(self.client.get(book.get_absolute_url()).status_code, 404)

    def test_editor_sees_an_unpublished_book_as_noindex_preview(self):
        book = mk_book(published=False)
        self.login()
        self.assertIn('noindex', html_of(self.get_ok(book.get_absolute_url())))

    def test_unknown_slug_is_a_404(self):
        self.assertEqual(self.client.get('/books/nope/').status_code, 404)

    def test_book_in_the_other_language_is_still_reachable_by_link(self):
        book = mk_book(language='en')
        self.get_ok(book.get_absolute_url())


class BookDownloadTests(Base):
    def setUp(self):
        super().setUp()
        self.book = mk_book()
        self.book_file = self.book.files.get()
        self.url = reverse('book_download', args=[self.book.slug, self.book_file.pk])

    def test_redirects_to_the_stored_file(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.book_file.file.url)

    def downloads(self):
        self.book_file.refresh_from_db()
        return self.book_file.downloads

    def test_counts_one_download_per_reader_per_half_hour(self):
        self.client.get(self.url, REMOTE_ADDR='10.0.0.1')
        self.client.get(self.url, REMOTE_ADDR='10.0.0.1')
        self.client.get(self.url, REMOTE_ADDR='10.0.0.2')
        self.assertEqual(self.downloads(), 2)

    def test_bots_and_head_requests_do_not_count(self):
        self.client.get(self.url, HTTP_USER_AGENT='Slackbot-LinkExpanding 1.0', REMOTE_ADDR='10.0.0.3')
        self.client.head(self.url, REMOTE_ADDR='10.0.0.4')
        self.assertEqual(self.downloads(), 0)
        self.assertEqual(self.client.head(self.url).status_code, 302, 'HEAD must still redirect')

    def test_unpublished_book_cannot_be_downloaded_by_visitors(self):
        Book.objects.filter(pk=self.book.pk).update(is_published=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_editor_can_download_from_an_unpublished_book_without_counting(self):
        Book.objects.filter(pk=self.book.pk).update(is_published=False)
        self.login()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.book_file.refresh_from_db()
        self.assertEqual(self.book_file.downloads, 0)

    def test_file_of_another_book_is_a_404(self):
        other = mk_book('Інша')
        url = reverse('book_download', args=[other.slug, self.book_file.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)


from unittest import mock  # noqa: E402

from app.models import BookFile  # noqa: E402

from .helpers import png  # noqa: E402

CABINET = '/editor-cabinet/books/'


def book_payload(**over):
    data = {'title': 'Людська дія', 'book_author': 'Людвіг фон Мізес', 'summary': 'Коротко',
            'annotation': '<p>Аннотація</p>', 'language': 'ua', 'is_published': 'on'}
    data.update(over)
    return {key: value for key, value in data.items() if value is not None}


class BookCabinetAccessTests(Base):
    def setUp(self):
        super().setUp()
        self.book = mk_book()

    def test_anonymous_is_sent_to_login(self):
        for method, url in (('get', CABINET), ('post', CABINET), ('get', f'{CABINET}{self.book.slug}/edit/'),
                            ('post', f'{CABINET}{self.book.slug}/edit/'), ('post', f'{CABINET}{self.book.slug}/delete/')):
            with self.subTest(method=method, url=url):
                response = getattr(self.client, method)(url, {})
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login/', response['Location'])
        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())

    def test_cabinet_links_to_the_books_section(self):
        self.login()
        self.assertIn(CABINET, html_of(self.get_ok('/editor-cabinet')))

    def test_editor_sees_all_books_including_unpublished(self):
        mk_book('Прихована', published=False)
        self.login()
        html = html_of(self.get_ok(CABINET))
        self.assertIn('Прихована', html)
        self.assertIn('Книга', html)


class BookCreateTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def create(self, files=(), labels=(), cover=None, **over):
        data = book_payload(**over)
        for number, upload in enumerate(files):
            data[f'book_file_{number}'] = upload
        for number, label in enumerate(labels):
            data[f'file_label_{number}'] = label
        if cover is not None:
            data['cover'] = cover
        return self.client.post(CABINET, data)

    def test_creates_a_book_with_cover_and_files_and_opens_it(self):
        response = self.create(files=[pdf('a.pdf'), pdf('b.pdf')], labels=['Том 1', 'Том 2'], cover=png())
        book = Book.objects.get()
        self.assertRedirects(response, book.get_absolute_url(), fetch_redirect_response=False)
        self.assertEqual((book.title, book.book_author, book.language, book.is_published),
                         ('Людська дія', 'Людвіг фон Мізес', 'ua', True))
        self.assertTrue(book.cover.name.startswith('covers/'))
        self.assertEqual([f.label for f in book.files.all()], ['Том 1', 'Том 2'])
        self.assertEqual([f.order for f in book.files.all()], [0, 1])

    def test_file_label_defaults_to_the_file_name(self):
        self.create(files=[pdf('Human Action.pdf')])
        self.assertEqual(Book.objects.get().files.get().label, 'Human Action')

    def test_book_is_a_draft_unless_publish_is_ticked(self):
        self.create(is_published=None)
        self.assertFalse(Book.objects.get().is_published)

    def test_annotation_is_sanitized_before_it_is_stored(self):
        self.create(annotation='<p>ok</p><script>alert(1)</script>')
        self.assertNotIn('script', Book.objects.get().annotation)

    def test_invalid_input_is_a_400_and_stores_nothing(self):
        cases = {
            'empty title': {'title': ' '},
            'summary too long': {'summary': 'x' * 401},
            'no summary': {'summary': ''},
            'no annotation': {'annotation': ''},
            'unknown language': {'language': 'de'},
        }
        for name, over in cases.items():
            with self.subTest(name):
                self.assertEqual(self.create(**over).status_code, 400)
        self.assertEqual(Book.objects.count(), 0)

    def test_a_bad_cover_or_bad_pdf_stores_nothing(self):
        bad_cover = SimpleUploadedFile('c.png', b'not an image', content_type='image/png')
        self.assertEqual(self.create(cover=bad_cover).status_code, 400)
        self.assertEqual(self.create(files=[pdf('x.exe')]).status_code, 400)
        self.assertEqual(self.create(files=[pdf('a.pdf'), pdf('b.pdf', content=b'junk')]).status_code, 400)
        self.assertEqual((Book.objects.count(), BookFile.objects.count()), (0, 0))

    def test_double_submit_creates_one_book(self):
        self.create()
        self.create()
        self.assertEqual(Book.objects.count(), 1)

    def test_storage_outage_is_a_503_and_stores_nothing(self):
        with mock.patch.object(BookFile, 'save', side_effect=OSError('cloudinary down')):
            response = self.create(files=[pdf()])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Book.objects.count(), 0)


class BookEditTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.book = mk_book('Стара назва', files=2)
        self.url = f'{CABINET}{self.book.slug}/edit/'

    def test_form_is_prefilled(self):
        html = html_of(self.get_ok(self.url))
        self.assertIn('Стара назва', html)
        for book_file in self.book.files.all():
            self.assertIn(book_file.label, html)

    def test_updates_fields_but_keeps_the_slug(self):
        slug = self.book.slug
        response = self.client.post(self.url, book_payload(title='Нова назва', summary='Нове'))
        self.assertRedirects(response, f'/books/{slug}/', fetch_redirect_response=False)
        self.book.refresh_from_db()
        self.assertEqual((self.book.title, self.book.summary, self.book.slug), ('Нова назва', 'Нове', slug))

    def test_unticking_publish_hides_the_book(self):
        self.client.post(self.url, book_payload(is_published=None))
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_published)

    def test_cover_is_kept_unless_a_new_one_is_uploaded(self):
        self.client.post(self.url, {**book_payload(), 'cover': png()})
        first = Book.objects.get(pk=self.book.pk).cover.name
        self.assertTrue(first)
        self.client.post(self.url, book_payload())
        self.assertEqual(Book.objects.get(pk=self.book.pk).cover.name, first)

    def test_adds_new_files_after_the_existing_ones(self):
        self.client.post(self.url, {**book_payload(), 'book_file_0': pdf('c.pdf'), 'file_label_0': 'Додаток'})
        labels = [f.label for f in self.book.files.all()]
        self.assertEqual(labels[-1], 'Додаток')
        self.assertEqual(len(labels), 3)
        self.assertEqual(self.book.files.last().order, 2)

    def test_removes_only_the_ticked_files_of_this_book(self):
        other = mk_book('Інша')
        keep, drop = list(self.book.files.all())
        foreign = other.files.get()
        self.client.post(self.url, {**book_payload(), 'delete_files': [str(drop.pk), str(foreign.pk), 'junk']})
        self.assertEqual(list(self.book.files.all()), [keep])
        self.assertTrue(BookFile.objects.filter(pk=foreign.pk).exists())

    def test_invalid_edit_is_a_400_and_changes_nothing(self):
        self.assertEqual(self.client.post(self.url, book_payload(title='')).status_code, 400)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, 'Стара назва')

    def test_unknown_book_is_a_404(self):
        self.assertEqual(self.client.get(f'{CABINET}nope/edit/').status_code, 404)


class BookDeleteTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.book = mk_book()

    def test_post_deletes_the_book(self):
        self.assertEqual(self.client.post(f'{CABINET}{self.book.slug}/delete/').status_code, 200)
        self.assertFalse(Book.objects.exists())

    def test_get_does_not_delete(self):
        self.assertEqual(self.client.get(f'{CABINET}{self.book.slug}/delete/').status_code, 405)
        self.assertTrue(Book.objects.exists())


class BookDiscoveryTests(Base):
    def test_menu_links_to_the_library(self):
        self.assertIn('href="/books"', html_of(self.get_ok('/')))

    def test_sitemap_lists_published_books_only(self):
        shown, hidden = mk_book('Видима'), mk_book('Прихована', published=False)
        xml = html_of(self.get_ok('/sitemap.xml'))
        self.assertIn(shown.get_absolute_url(), xml)
        self.assertNotIn(hidden.get_absolute_url(), xml)

    def test_sitemap_lists_the_library_page(self):
        self.assertIn('/books<', html_of(self.get_ok('/sitemap.xml')))

    def test_books_never_leak_into_article_surfaces(self):
        mk_book('Таємна книга')
        for url in ('/', '/all', '/feed/', '/search/?q=Таємна'):
            with self.subTest(url=url):
                self.assertNotIn('Таємна книга', html_of(self.get_ok(url)))


class BookFormRobustnessTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def test_label_stays_with_its_own_file_when_an_earlier_row_is_empty(self):
        data = {**book_payload(), 'book_file_1': pdf('b.pdf'), 'file_label_0': 'Пропущений', 'file_label_1': 'Том 2'}
        self.client.post(CABINET, data)
        self.assertEqual([f.label for f in Book.objects.get().files.all()], ['Том 2'])

    def test_files_keep_the_order_of_their_rows(self):
        data = {**book_payload(), 'book_file_10': pdf('c.pdf'), 'book_file_2': pdf('b.pdf'),
                'file_label_10': 'Третій', 'file_label_2': 'Другий'}
        self.client.post(CABINET, data)
        self.assertEqual([f.label for f in Book.objects.get().files.all()], ['Другий', 'Третій'])

    def test_retry_after_a_storage_failure_is_not_swallowed_as_a_double_click(self):
        data = {**book_payload(), 'book_file_0': pdf()}
        with mock.patch.object(BookFile, 'save', side_effect=OSError('down')):
            self.assertEqual(self.client.post(CABINET, data).status_code, 503)
        data['book_file_0'] = pdf()
        self.client.post(CABINET, data)
        self.assertEqual(Book.objects.count(), 1)

    def test_rejected_create_keeps_what_the_editor_typed(self):
        response = self.client.post(CABINET, book_payload(title='Моя назва', summary='x' * 401, book_author='Автор Х'))
        self.assertEqual(response.status_code, 400)
        html = html_of(response)
        self.assertIn('value="Моя назва"', html)
        self.assertIn('value="Автор Х"', html)
        self.assertNotIn('Файлів ще немає', html, 'the create form has no existing files to list')

    def test_rejected_edit_keeps_the_edits_not_the_stored_values(self):
        book = mk_book('Стара назва')
        response = self.client.post(f'{CABINET}{book.slug}/edit/', book_payload(title='Нова назва', summary=''))
        self.assertEqual(response.status_code, 400)
        self.assertIn('value="Нова назва"', html_of(response))
        book.refresh_from_db()
        self.assertEqual(book.title, 'Стара назва')


class BookSitemapFreshnessTests(Base):
    def test_lastmod_follows_the_last_edit(self):
        from datetime import datetime, timezone
        book = mk_book()
        Book.objects.filter(pk=book.pk).update(updated_at=datetime(2031, 5, 4, tzinfo=timezone.utc))
        self.assertIn('2031-05-04', html_of(self.get_ok('/sitemap.xml')))

    def test_saving_a_book_bumps_updated_at(self):
        book = mk_book()
        first = book.updated_at
        book.title = 'Інша'
        book.save()
        self.assertGreater(book.updated_at, first)


class BookFileNameLengthTests(SimpleTestCase):
    def test_longest_possible_name_keeps_its_pdf_extension_in_cloudinary(self):
        """Cloudinary's raw storage cuts a name to the field's max_length; raw public ids need the extension."""
        from cloudinary_storage.storage import RawMediaCloudinaryStorage

        from app.models import Book as BookModel, book_file_path

        slug = 'a' * BookModel._meta.get_field('slug').max_length
        name = book_file_path(mock.Mock(book=mock.Mock(slug=slug)), 'x.pdf')
        limit = BookFile._meta.get_field('file').max_length
        self.assertTrue(RawMediaCloudinaryStorage().get_available_name(name, max_length=limit).endswith('.pdf'))


class BookFileCleanupTests(Base):
    def setUp(self):
        super().setUp()
        self.book = mk_book(files=2)
        self.files = list(self.book.files.all())
        self.paths = [f.file.path for f in self.files]

    def exists(self, path):
        import os
        return os.path.exists(path)

    def test_deleting_a_file_row_removes_the_stored_file(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.files[0].delete()
        self.assertFalse(self.exists(self.paths[0]))
        self.assertTrue(self.exists(self.paths[1]))

    def test_deleting_a_book_removes_all_of_its_stored_files(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.book.delete()
        self.assertFalse(any(self.exists(p) for p in self.paths))

    def test_ticking_delete_in_the_edit_form_removes_the_stored_file(self):
        self.login()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(f'{CABINET}{self.book.slug}/edit/',
                             {**book_payload(), 'delete_files': [str(self.files[1].pk)]})
        self.assertFalse(self.exists(self.paths[1]))
        self.assertTrue(self.exists(self.paths[0]))

    def test_a_rolled_back_delete_keeps_the_stored_file(self):
        from django.db import transaction
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.files[0].delete()
                    raise RuntimeError('roll back')
            except RuntimeError:
                pass
        self.assertTrue(self.exists(self.paths[0]))

    def test_a_storage_failure_during_cleanup_does_not_break_the_delete(self):
        with mock.patch('django.core.files.storage.FileSystemStorage.delete', side_effect=OSError('down')):
            with self.captureOnCommitCallbacks(execute=True):
                self.files[0].delete()
        self.assertFalse(BookFile.objects.filter(pk=self.files[0].pk).exists())
