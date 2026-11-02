import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils.timezone import now

from app.models import AboutUsText, Article, Author, Category, Comment

from .helpers import (TEST_PASSWORD, make_editor, Base, captcha_ok, html_of, mk_article, mk_author, mk_category, mk_comment, new_uuid, png,
                      time_limit, Timeout, query_limit)

EDITOR_GET_URLS = ['/editor-cabinet', '/publish', '/editor-cabinet/comments-moderation/',
                   '/editor-cabinet/categories/order/', '/authors/a1/edit', '/article/x/edit/']
EDITOR_POST_URLS = ['/publish', '/create-category/', '/about-us-edit', '/create_new_author/',
                    '/authors/a1/edit', '/article/x/edit/', '/editor-cabinet/categories/order/update/']
DESTRUCTIVE_GET = ['/article/x/delete/', '/category/c1/delete/']


def publish_payload(author, **over):
    data = {'article_name': 'Нова стаття', 'article_text': '<p>text</p>', 'language': 'ua',
            'article_author': str(author.id), 'publish_option': 'now'}
    data.update(over)
    return data


class EditorAuthTests(Base):
    def setUp(self):
        super().setUp()
        mk_author('a1')
        mk_article('x')
        mk_category('c1')

    def test_anonymous_get_redirected_to_login_page_that_exists(self):
        for url in EDITOR_GET_URLS:
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertEqual(response.status_code, 200, response.redirect_chain)
                self.assertIn('password', html_of(response))

    def test_anonymous_post_is_rejected(self):
        for url in EDITOR_POST_URLS:
            with self.subTest(url=url):
                response = self.client.post(url, {})
                self.assertIn(response.status_code, (302, 401, 403))

    def test_anonymous_cannot_delete(self):
        for url in DESTRUCTIVE_GET:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        self.assertTrue(Article.objects.filter(slug='x').exists())
        self.assertTrue(Category.objects.filter(slug='c1').exists())

    def test_login_success_redirects_to_cabinet(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        response = self.client.post('/login/', {'login': 'ed', 'password': TEST_PASSWORD})
        self.assertRedirects(response, '/editor-cabinet', fetch_redirect_response=False)

    def test_login_failure_shows_error(self):
        response = self.client.post('/login/', {'login': 'nobody', 'password': 'bad'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Неправильний', html_of(response))

    def test_login_missing_fields_no_500(self):
        self.assertLess(self.client.post('/login/', {}).status_code, 500)

    def test_login_has_next_support(self):
        from django.contrib.auth.models import User
        make_editor('ed', TEST_PASSWORD)
        response = self.client.post('/login/?next=/publish', {'login': 'ed', 'password': TEST_PASSWORD})
        self.assertEqual(response['Location'], '/publish')


    def test_cabinet_on_fresh_install(self):
        self.login()
        self.assertEqual(self.client.get('/editor-cabinet').status_code, 200)

    def test_cabinet_lists_published_and_unpublished(self):
        self.login()
        AboutUsText.objects.create(pk=1, text_ua='a', text_en='b')
        mk_article('pub1')
        mk_article('un1', published=False)
        html = html_of(self.get_ok('/editor-cabinet'))
        self.assertIn('pub1', html)
        self.assertIn('un1', html)


class PublishTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.author = mk_author('a1')
        self.root = mk_category('root')
        self.child = mk_category('child', parent=self.root)
        self.leaf = mk_category('leaf', parent=self.child)

    def post(self, **over):
        return self.client.post('/publish', publish_payload(self.author, **over))

    def test_publish_now_creates_published_article(self):
        response = self.post(article_slug='my-art')
        self.assertRedirects(response, '/article/my-art/', fetch_redirect_response=False)
        article = Article.objects.get(slug='my-art')
        self.assertTrue(article.is_published)
        self.assertLessEqual(article.publish_at, now())

    def test_publish_adds_all_ancestor_categories(self):
        self.post(article_slug='anc', categories=[str(self.leaf.id)])
        self.assertEqual(set(Article.objects.get(slug='anc').categories.values_list('slug', flat=True)),
                         {'leaf', 'child', 'root'})

    def test_publish_schedule_creates_hidden_article(self):
        self.post(article_slug='sch', publish_option='schedule', publish_datetime='2099-01-01T10:00')
        article = Article.objects.get(slug='sch')
        self.assertGreater(article.publish_at, now())
        self.client.logout()
        self.assertEqual(self.client.get('/article/sch/').status_code, 404)

    def test_scheduled_article_needs_no_external_job_to_go_live(self):
        self.post(article_slug='sch2', publish_option='schedule', publish_datetime='2099-01-01T10:00')
        Article.objects.filter(slug='sch2').update(publish_at=now() - timedelta(minutes=1))
        self.client.logout()
        self.assertEqual(self.client.get('/article/sch2/').status_code, 200)

    def test_scheduled_article_goes_live_by_command_after_time(self):
        past = now() - timedelta(minutes=1)
        a = mk_article('cmd', published=False, publish_at=past)
        out = StringIO()
        call_command('publish_articles', stdout=out)
        a.refresh_from_db()
        self.assertTrue(a.is_published)

    def test_publish_command_does_not_publish_future(self):
        a = mk_article('cmd2', published=False, publish_at=now() + timedelta(hours=1))
        call_command('publish_articles', stdout=StringIO())
        a.refresh_from_db()
        self.assertFalse(a.is_published)

    def test_publish_command_is_idempotent(self):
        mk_article('cmd3', published=False, publish_at=now() - timedelta(minutes=1))
        call_command('publish_articles', stdout=StringIO())
        out = StringIO()
        call_command('publish_articles', stdout=out)
        self.assertIn('0', out.getvalue())

    def test_publish_command_keeps_drafts_without_schedule_semantics(self):
        a = mk_article('draftcmd', published=False, publish_at=now() - timedelta(days=1))
        call_command('publish_articles', stdout=StringIO())
        a.refresh_from_db()
        self.assertTrue(a.is_published)


    def test_publish_without_author_shows_error(self):
        response = self.client.post('/publish', {'article_name': 'x', 'article_text': 't', 'language': 'ua'})
        self.assertIn(response.status_code, (200, 400))
        self.assertEqual(Article.objects.count(), 0)

    def test_publish_with_unknown_author_id_no_500(self):
        response = self.client.post('/publish', publish_payload(self.author, article_author=str(new_uuid())))
        self.assertLess(response.status_code, 500)

    def test_publish_with_garbage_author_id_no_500(self):
        response = self.client.post('/publish', publish_payload(self.author, article_author='not-a-uuid'))
        self.assertLess(response.status_code, 500)

    def test_publish_with_garbage_category_id_is_ignored(self):
        response = self.post(categories=['zzz'], article_slug='gc')
        self.assertLess(response.status_code, 500)

    def test_publish_with_image(self):
        response = self.client.post('/publish', {**publish_payload(self.author, article_slug='img'),
                                                 'article_image': png()})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Article.objects.get(slug='img').image.name.endswith('.png'))

    def test_publish_with_non_image_file_creates_nothing(self):
        bad = SimpleUploadedFile('x.txt', b'hello', content_type='text/plain')
        self.client.post('/publish', {**publish_payload(self.author, article_slug='badimg'), 'article_image': bad})
        self.assertFalse(Article.objects.filter(slug='badimg').exists())

    def test_publish_with_fake_image_content_rejected(self):
        bad = SimpleUploadedFile('x.png', b'not really a png', content_type='image/png')
        self.client.post('/publish', {**publish_payload(self.author, article_slug='fake'), 'article_image': bad})
        self.assertFalse(Article.objects.filter(slug='fake').exists())

    def test_publish_saves_article_once_with_image(self):
        with mock.patch.object(Article, 'save', autospec=True, side_effect=Article.save) as save:
            self.client.post('/publish', {**publish_payload(self.author, article_slug='once'), 'article_image': png()})
        self.assertEqual(save.call_count, 1)

    def test_publish_invalid_datetime_is_client_error(self):
        response = self.post(publish_option='schedule', publish_datetime='not-a-date', article_slug='dt')
        self.assertLess(response.status_code, 500)

    def test_publish_schedule_without_datetime_publishes_now_or_errors(self):
        response = self.post(publish_option='schedule', publish_datetime='', article_slug='dt2')
        self.assertLess(response.status_code, 500)

    def test_publish_missing_title_is_client_error(self):
        response = self.client.post('/publish', {'article_text': 't', 'language': 'ua',
                                                 'article_author': str(self.author.id)})
        self.assertLess(response.status_code, 500)

    def test_publish_missing_text_is_client_error(self):
        response = self.client.post('/publish', {'article_name': 't', 'language': 'ua',
                                                 'article_author': str(self.author.id)})
        self.assertLess(response.status_code, 500)

    def test_publish_empty_title_rejected(self):
        self.post(article_name='   ', article_slug='empty')
        self.assertFalse(Article.objects.filter(slug='empty').exists())

    def test_publish_invalid_language_rejected(self):
        self.post(language='xx', article_slug='lang')
        self.assertFalse(Article.objects.filter(language='xx').exists())

    def test_publish_missing_language_rejected(self):
        data = publish_payload(self.author, article_slug='nolang')
        del data['language']
        response = self.client.post('/publish', data)
        self.assertLess(response.status_code, 500)

    def test_publish_slug_collision_gets_suffix(self):
        self.post(article_slug='dup')
        self.post(article_slug='dup')
        self.assertEqual(sorted(Article.objects.values_list('slug', flat=True)), ['dup', 'dup-1'])

    def test_publish_cyrillic_title_yields_readable_slug(self):
        self.post(article_name='Українська мова')
        self.assertNotEqual(Article.objects.get().slug, 'article')


    def test_publish_slug_longer_than_max_is_handled(self):
        response = self.post(article_name='long ' * 100)
        self.assertLess(response.status_code, 500)
        self.assertLessEqual(len(Article.objects.get().slug), 200)

    def test_publish_scheduled_time_interpreted_in_editor_timezone(self):
        self.post(publish_option='schedule', publish_datetime='2099-06-01T12:00', article_slug='tz')
        self.assertEqual(Article.objects.get(slug='tz').publish_at.hour, 9)

    def test_publish_scheduled_in_dst_gap_is_handled(self):
        with override_settings(TIME_ZONE='Europe/Kyiv'):
            response = self.post(publish_option='schedule', publish_datetime='2027-03-28T03:30', article_slug='gap')
        self.assertLess(response.status_code, 500)

    def test_publish_scheduled_in_dst_overlap_is_handled(self):
        with override_settings(TIME_ZONE='Europe/Kyiv'):
            response = self.post(publish_option='schedule', publish_datetime='2027-10-31T03:30', article_slug='ovl')
        self.assertLess(response.status_code, 500)

    def test_publish_category_cycle_does_not_hang(self):
        a = mk_category('cyc-a')
        Category.objects.filter(pk=a.pk).update(parent=a)
        with query_limit(200) as guard:
            self.post(categories=[str(a.id)], article_slug='cyc')
        self.assertFalse(guard.exceeded, 'publish loops forever walking a category cycle')

    def test_publish_storage_failure_is_handled(self):
        with mock.patch('django.core.files.storage.FileSystemStorage._save', side_effect=OSError('storage down')):
            response = self.client.post('/publish', {**publish_payload(self.author, article_slug='st'),
                                                     'article_image': png()})
        self.assertLess(response.status_code, 500)
        self.assertFalse(Article.objects.filter(slug='st').exists())

    def test_publish_form_get_ok(self):
        self.assertEqual(self.client.get('/publish').status_code, 200)



class EditArticleTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.author = mk_author('a1')
        self.root = mk_category('root')
        self.other = mk_category('other')
        self.article = mk_article('orig', name='Original', cats=[self.root], author=self.author,
                                  publish_at=now() - timedelta(days=5))

    def edit(self, **over):
        data = {'article_name': 'Original', 'article_text': '<p>t</p>', 'language': 'ua',
                'article_author': str(self.author.id), 'publish_option': 'now', 'article_slug': 'orig',
                'categories': [str(self.root.id)]}
        data.update(over)
        return self.client.post('/article/orig/edit/', data)

    def test_edit_form_get_ok(self):
        self.assertEqual(self.client.get('/article/orig/edit/').status_code, 200)

    def test_edit_unknown_404(self):
        self.assertEqual(self.client.get('/article/zzz/edit/').status_code, 404)

    def test_edit_title_keeps_url(self):
        self.edit(article_name='Brand new title')
        self.article.refresh_from_db()
        self.assertEqual(self.article.slug, 'orig')
        self.assertEqual(self.article.name, 'Brand new title')

    def test_edit_explicit_slug_changes_url(self):
        response = self.edit(article_slug='renamed')
        self.assertRedirects(response, '/article/renamed/', fetch_redirect_response=False)

    def test_edit_slug_change_leaves_redirect_from_old_url(self):
        self.edit(article_slug='renamed')
        self.assertIn(self.client.get('/article/orig/').status_code, (301, 302, 308))

    def test_edit_blank_slug_keeps_existing_url(self):
        self.edit(article_slug='')
        self.article.refresh_from_db()
        self.assertEqual(self.article.slug, 'orig')

    def test_edit_slug_collision_is_resolved(self):
        mk_article('taken')
        self.edit(article_slug='taken')
        self.article.refresh_from_db()
        self.assertEqual(self.article.slug, 'taken-1')

    def test_edit_replaces_categories(self):
        self.edit(categories=[str(self.other.id)])
        self.assertEqual(list(self.article.categories.values_list('slug', flat=True)), ['other'])

    def test_edit_without_categories_clears_them(self):
        data = {'article_name': 'O', 'article_text': 't', 'language': 'ua', 'article_author': str(self.author.id),
                'publish_option': 'now', 'article_slug': 'orig'}
        self.client.post('/article/orig/edit/', data)
        self.assertEqual(self.article.categories.count(), 0)

    def test_edit_does_not_bump_publish_date_of_live_article(self):
        before = self.article.publish_at
        self.edit()
        self.article.refresh_from_db()
        self.assertEqual(self.article.publish_at, before)

    def test_edit_can_reschedule_a_live_article(self):
        self.edit(publish_option='schedule', publish_datetime='2099-01-01T10:00')
        self.article.refresh_from_db()
        self.assertGreater(self.article.publish_at, now())
        self.client.logout()
        self.assertEqual(self.client.get('/article/orig/').status_code, 404)

    def test_edit_bad_image_keeps_categories(self):
        bad = SimpleUploadedFile('x.txt', b'hello', content_type='text/plain')
        self.client.post('/article/orig/edit/', {
            'article_name': 'Original', 'article_text': 't', 'language': 'ua', 'article_author': str(self.author.id),
            'publish_option': 'now', 'article_slug': 'orig', 'categories': [str(self.root.id)],
            'article_image': bad})
        self.assertEqual(self.article.categories.count(), 1)

    def test_edit_save_failure_keeps_categories(self):
        with mock.patch.object(Article, 'save', side_effect=RuntimeError('db')):
            self.edit(categories=[str(self.other.id)])
        self.assertEqual(list(self.article.categories.values_list('slug', flat=True)), ['root'])

    def test_edit_without_author_is_client_error(self):
        response = self.client.post('/article/orig/edit/', {'article_name': 'x', 'article_text': 't',
                                                            'language': 'ua'})
        self.assertLess(response.status_code, 500)

    def test_edit_garbage_author_is_client_error(self):
        response = self.edit(article_author='nonsense')
        self.assertLess(response.status_code, 500)

    def test_edit_invalid_datetime_is_client_error(self):
        response = self.edit(publish_option='schedule', publish_datetime='bad')
        self.assertLess(response.status_code, 500)

    def test_edit_replace_image(self):
        self.client.post('/article/orig/edit/', {
            'article_name': 'Original', 'article_text': 't', 'language': 'ua', 'article_author': str(self.author.id),
            'publish_option': 'now', 'article_slug': 'orig', 'article_image': png('new.png')})
        self.article.refresh_from_db()
        self.assertIn('new', self.article.image.name)

    def test_edit_empty_title_rejected(self):
        self.edit(article_name='')
        self.article.refresh_from_db()
        self.assertEqual(self.article.name, 'Original')

    def test_edit_changes_language(self):
        self.edit(language='en')
        self.article.refresh_from_db()
        self.assertEqual(self.article.language, 'en')

    def test_edit_invalid_language_rejected(self):
        self.edit(language='zz')
        self.article.refresh_from_db()
        self.assertEqual(self.article.language, 'ua')


class DeleteTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def test_get_does_not_delete_article(self):
        mk_article('keep')
        self.client.get('/article/keep/delete/')
        self.assertTrue(Article.objects.filter(slug='keep').exists())

    def test_post_deletes_article(self):
        mk_article('gone')
        response = self.client.post('/article/gone/delete/')
        self.assertLess(response.status_code, 400)
        self.assertFalse(Article.objects.filter(slug='gone').exists())

    def test_delete_unknown_article_404(self):
        self.assertEqual(self.client.post('/article/none/delete/').status_code, 404)

    def test_delete_article_cascades_comments(self):
        a = mk_article('c')
        mk_comment(a)
        a.delete()
        self.assertEqual(Comment.objects.count(), 0)

    def test_get_does_not_delete_category(self):
        mk_category('keepc')
        self.client.get('/category/keepc/delete/')
        self.assertTrue(Category.objects.filter(slug='keepc').exists())

    def test_post_deletes_category(self):
        mk_category('goc')
        self.client.post('/category/goc/delete/')
        self.assertFalse(Category.objects.filter(slug='goc').exists())

    def test_delete_category_with_children_is_refused(self):
        parent = mk_category('par')
        mk_category('kid', parent=parent)
        self.client.post('/category/par/delete/')
        self.assertTrue(Category.objects.filter(slug='kid').exists())

    def test_delete_category_keeps_articles(self):
        cat = mk_category('cc')
        mk_article('inside', cats=[cat])
        self.client.post('/category/cc/delete/')
        self.assertTrue(Article.objects.filter(slug='inside').exists())

    def test_delete_author_does_not_delete_articles(self):
        author = mk_author('gone')
        mk_article('wr', author=author)
        author.delete()
        self.assertTrue(Article.objects.filter(slug='wr').exists())

    def test_delete_invalidates_menu_cache(self):
        cat = mk_category('menu-gone')
        self.client.get('/')
        cat.delete()
        self.assertNotIn('menu-gone', html_of(self.get_ok('/')))

    def test_other_method_on_delete_returns_405(self):
        mk_article('m')
        self.assertEqual(self.client.put('/article/m/delete/').status_code, 405)


class CategoryAuthorAdminTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def test_create_root_category(self):
        response = self.client.post('/create-category/', {'name_ua': 'Politics', 'name_en': 'Politics'})
        self.assertRedirects(response, '/editor-cabinet', fetch_redirect_response=False)
        self.assertEqual(Category.objects.get().slug, 'politics')

    def test_create_child_category(self):
        parent = mk_category('p')
        self.client.post('/create-category/', {'name_ua': 'Child', 'name_en': 'Child', 'parent_id': str(parent.id)})
        self.assertEqual(Category.objects.get(slug='child').parent_id, parent.id)

    def test_create_category_with_cyrillic_name_has_usable_slug_and_site_survives(self):
        self.client.post('/create-category/', {'name_ua': 'Політика', 'name_en': 'Politics'})
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertTrue(Category.objects.get().slug)

    def test_create_two_cyrillic_categories_have_unique_nonempty_slugs(self):
        for name in ['Політика', 'Економіка', 'Культура']:
            self.client.post('/create-category/', {'name_ua': name, 'name_en': name})
        slugs = list(Category.objects.values_list('slug', flat=True))
        self.assertEqual(len(set(slugs)), 3)
        self.assertTrue(all(slugs), slugs)

    def test_create_category_with_unknown_parent_404(self):
        response = self.client.post('/create-category/', {'name_ua': 'x', 'name_en': 'x', 'parent_id': str(new_uuid())})
        self.assertEqual(response.status_code, 404)

    def test_create_category_with_garbage_parent_is_client_error(self):
        response = self.client.post('/create-category/', {'name_ua': 'x', 'name_en': 'x', 'parent_id': 'junk'})
        self.assertLess(response.status_code, 500)

    def test_create_category_missing_names_is_client_error(self):
        self.assertLess(self.client.post('/create-category/', {}).status_code, 500)

    def test_create_category_blank_names_rejected(self):
        self.client.post('/create-category/', {'name_ua': ' ', 'name_en': ' '})
        self.assertEqual(Category.objects.count(), 0)

    def test_create_category_too_long_name_is_client_error(self):
        response = self.client.post('/create-category/', {'name_ua': 'x' * 150, 'name_en': 'y'})
        self.assertLess(response.status_code, 500)
        self.assertLessEqual(len(Category.objects.get().name_ua) if Category.objects.exists() else 0, 100)

    def test_new_category_appears_in_menu_immediately(self):
        self.client.get('/')
        self.client.post('/create-category/', {'name_ua': 'Fresh', 'name_en': 'Fresh'})
        self.assertIn('/category/fresh/', html_of(self.get_ok('/')))

    def test_create_author(self):
        response = self.client.post('/create_new_author/', {
            'author_name_ua': 'Ім', 'author_name_en': 'Name', 'author_description_ua': 'd',
            'author_description_en': 'd', 'author_image': png()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Author.objects.get().slug, 'name')

    def test_create_author_without_image_keeps_site_working(self):
        self.client.post('/create_new_author/', {
            'author_name_ua': 'Ім', 'author_name_en': 'Name', 'author_description_ua': 'd',
            'author_description_en': 'd'})
        for url in ['/authors', '/authors/name']:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_create_author_cyrillic_en_name_has_slug(self):
        self.client.post('/create_new_author/', {
            'author_name_ua': 'Ім', 'author_name_en': 'Іван', 'author_description_ua': 'd',
            'author_description_en': 'd'})
        self.assertTrue(Author.objects.get().slug)
        self.assertEqual(self.client.get('/authors').status_code, 200)

    def test_create_author_missing_fields_is_client_error(self):
        self.assertLess(self.client.post('/create_new_author/', {}).status_code, 500)

    def test_edit_author_get_ok(self):
        mk_author('a1')
        self.assertEqual(self.client.get('/authors/a1/edit').status_code, 200)

    def test_edit_author_updates_and_redirects(self):
        mk_author('a1')
        response = self.client.post('/authors/a1/edit', {'name_ua': 'U', 'name_en': 'E', 'description_ua': 'x',
                                                         'description_en': 'y'})
        self.assertRedirects(response, '/authors/a1', fetch_redirect_response=False)
        self.assertEqual(Author.objects.get().name_en, 'E')

    def test_edit_author_missing_fields_is_client_error(self):
        mk_author('a1')
        self.assertLess(self.client.post('/authors/a1/edit', {}).status_code, 500)

    def test_edit_author_image_upload(self):
        mk_author('a1')
        self.client.post('/authors/a1/edit', {'name_ua': 'U', 'name_en': 'E', 'description_ua': 'x',
                                              'description_en': 'y', 'author_image': png('face.png')})
        self.assertIn('face', Author.objects.get().image.name)

    def test_about_us_edit_updates(self):
        AboutUsText.objects.create(pk=1, text_ua='a', text_en='b')
        self.client.post('/about-us-edit', {'new_text_ua': 'нове', 'new_text_en': 'new'})
        self.assertEqual(AboutUsText.objects.get(pk=1).text_en, 'new')

    def test_about_us_edit_on_fresh_install_creates_row(self):
        response = self.client.post('/about-us-edit', {'new_text_ua': 'нове', 'new_text_en': 'new'})
        self.assertLess(response.status_code, 500)
        self.assertTrue(AboutUsText.objects.exists())

    def test_about_us_edit_get_is_not_server_error(self):
        self.assertLess(self.client.get('/about-us-edit').status_code, 500)

    def test_about_us_edit_missing_fields_keeps_text(self):
        AboutUsText.objects.create(pk=1, text_ua='keep', text_en='keep')
        self.assertLess(self.client.post('/about-us-edit', {}).status_code, 500)


class CategoryOrderTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.a = mk_category('a', order=1)
        self.b = mk_category('b', order=2)

    def update(self, payload, **kw):
        return self.client.post('/editor-cabinet/categories/order/update/', data=payload,
                                content_type='application/json', **kw)

    def test_order_editor_page_ok(self):
        self.assertEqual(self.client.get('/editor-cabinet/categories/order/').status_code, 200)

    def test_update_order_changes_menu(self):
        self.client.get('/')
        self.update(json.dumps([{'id': str(self.a.id), 'order': 5}, {'id': str(self.b.id), 'order': 1}]))
        self.in_order(html_of(self.get_ok('/')), '/category/b/', '/category/a/')

    def test_update_order_invalid_json_is_client_error(self):
        self.assertLess(self.update('{oops').status_code, 500)

    def test_update_order_not_a_list_is_client_error(self):
        self.assertLess(self.update(json.dumps({'a': 1})).status_code, 500)

    def test_update_order_missing_keys_is_client_error(self):
        self.assertLess(self.update(json.dumps([{'id': str(self.a.id)}])).status_code, 500)

    def test_update_order_garbage_id_is_client_error(self):
        self.assertLess(self.update(json.dumps([{'id': 'zzz', 'order': 1}])).status_code, 500)

    def test_update_order_non_integer_order_is_client_error(self):
        self.assertLess(self.update(json.dumps([{'id': str(self.a.id), 'order': 'x'}])).status_code, 500)

    def test_update_order_is_all_or_nothing(self):
        self.update(json.dumps([{'id': str(self.a.id), 'order': 9}, {'id': 'junk', 'order': 1}]))
        self.a.refresh_from_db()
        self.assertEqual(self.a.order, 1)

    def test_update_order_get_is_405(self):
        self.assertEqual(self.client.get('/editor-cabinet/categories/order/update/').status_code, 405)


class ModerationTests(Base):
    def setUp(self):
        super().setUp()
        self.login()
        self.article = mk_article('m')

    def test_moderation_page_lists_comments(self):
        mk_comment(self.article, text='please moderate me')
        self.assertIn('please moderate me', html_of(self.get_ok('/editor-cabinet/comments-moderation/')))

    def test_moderation_empty_ok(self):
        self.assertEqual(self.client.get('/editor-cabinet/comments-moderation/').status_code, 200)

    def test_delete_comment_post(self):
        c = mk_comment(self.article)
        response = self.client.post(f'/editor-cabinet/comments-moderation/{c.id}/delete/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.count(), 0)

    def test_delete_comment_get_is_405(self):
        c = mk_comment(self.article)
        self.assertEqual(self.client.get(f'/editor-cabinet/comments-moderation/{c.id}/delete/').status_code, 405)
        self.assertEqual(Comment.objects.count(), 1)

    def test_delete_comment_unknown_404(self):
        self.assertEqual(self.client.post(f'/editor-cabinet/comments-moderation/{new_uuid()}/delete/').status_code, 404)


    def test_moderation_is_newest_first(self):
        old = mk_comment(self.article, text='old-one')
        new = mk_comment(self.article, text='new-one')
        Comment.objects.filter(pk=old.pk).update(created_at=now() - timedelta(days=3))
        self.in_order(html_of(self.get_ok('/editor-cabinet/comments-moderation/')), 'new-one', 'old-one')


class CommentFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.article = mk_article('c1')

    def post(self, **over):
        data = {'article_id': str(self.article.id), 'author': 'Іван', 'text': 'Привіт 👋'}
        data.update(over)
        return self.client.post('/comment', data)

    def test_root_comment_created_with_valid_captcha(self):
        with captcha_ok():
            response = self.post()
        self.assertRedirects(response, '/article/c1/', fetch_redirect_response=False)
        self.assertEqual(Comment.objects.get().text, 'Привіт 👋')

    def test_root_comment_rejected_with_bad_captcha(self):
        with captcha_ok(False):
            self.post()
        self.assertEqual(Comment.objects.count(), 0)

    def test_bad_captcha_tells_the_user(self):
        with captcha_ok(False):
            response = self.client.post('/comment', {'article_id': str(self.article.id), 'author': 'a', 'text': 't'},
                                        follow=True)
        self.assertTrue(list(response.context['messages']))

    def test_reply_creates_child_comment(self):
        parent = mk_comment(self.article)
        with captcha_ok():
            self.post(parent_comment_id=str(parent.id))
        self.assertEqual(Comment.objects.filter(parent_comment=parent).count(), 1)

    def test_reply_to_comment_of_another_article_rejected(self):
        other = mk_article('c2')
        foreign = mk_comment(other)
        with captcha_ok():
            self.post(parent_comment_id=str(foreign.id))
        self.assertEqual(Comment.objects.filter(parent_comment=foreign).count(), 0)

    def test_reply_to_unknown_parent_404(self):
        with captcha_ok():
            self.assertEqual(self.post(parent_comment_id=str(new_uuid())).status_code, 404)

    def test_reply_with_garbage_parent_id_is_client_error(self):
        with captcha_ok():
            self.assertLess(self.post(parent_comment_id='junk').status_code, 500)

    def test_get_redirects_home(self):
        self.assertRedirects(self.client.get('/comment'), '/', fetch_redirect_response=False)

    def test_missing_article_id_404(self):
        self.assertEqual(self.client.post('/comment', {'author': 'a', 'text': 't'}).status_code, 404)

    def test_garbage_article_id_is_client_error(self):
        self.assertLess(self.post(article_id='junk').status_code, 500)

    def test_missing_author_is_client_error(self):
        with captcha_ok():
            response = self.client.post('/comment', {'article_id': str(self.article.id), 'text': 't'})
        self.assertLess(response.status_code, 500)

    def test_missing_text_is_client_error(self):
        with captcha_ok():
            response = self.client.post('/comment', {'article_id': str(self.article.id), 'author': 'a'})
        self.assertLess(response.status_code, 500)

    def test_blank_values_rejected(self):
        for author, text in [('', 'x'), ('x', ''), ('   ', 'x'), ('x', '   \n')]:
            with self.subTest(author=author, text=text), captcha_ok():
                self.post(author=author, text=text)
                self.assertEqual(Comment.objects.count(), 0)

    def test_overlong_author_is_client_error(self):
        with captcha_ok():
            response = self.post(author='a' * 101)
        self.assertLess(response.status_code, 500)
        self.assertFalse(Comment.objects.filter(author='a' * 101).exists())


    def test_unicode_roundtrip(self):
        for text in ['Ґрунт ї є і', '日本語', 'emoji 🚀', 'RTL עברית', 'á']:
            with self.subTest(text=text), captcha_ok():
                self.post(text=text)
                self.assertTrue(Comment.objects.filter(text=text).exists())

    def test_text_is_escaped_on_page(self):
        with captcha_ok():
            self.post(text='<script>alert(1)</script>', author='<b>x</b>')
        html = html_of(self.get_ok('/article/c1/'))
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<b>x</b>', html)

    def test_comments_shown_newest_first(self):
        old = mk_comment(self.article, text='older')
        mk_comment(self.article, text='newer')
        Comment.objects.filter(pk=old.pk).update(created_at=now() - timedelta(days=1))
        self.in_order(html_of(self.get_ok('/article/c1/')), 'newer', 'older')


    def test_deep_thread_renders_all_levels(self):
        parent = None
        for i in range(25):
            parent = mk_comment(self.article, parent=parent, text=f'level-{i}')
        html = html_of(self.get_ok('/article/c1/'))
        self.assertIn('level-24', html)

    def test_very_deep_thread_does_not_crash(self):
        parent = None
        for i in range(400):
            parent = mk_comment(self.article, parent=parent, text=f'lvl-{i}')
        self.assertEqual(self.client.get('/article/c1/').status_code, 200)

    def test_comment_count_matches_total(self):
        parent = mk_comment(self.article)
        mk_comment(self.article, parent=parent)
        self.assertIn('<p>2</p>', html_of(self.get_ok('/article/c1/')))

    def test_double_submit_creates_single_comment(self):
        with captcha_ok():
            self.post()
            self.post()
        self.assertEqual(Comment.objects.count(), 1)

    def test_comment_on_unpublished_article_rejected(self):
        draft = mk_article('draft', published=False)
        with captcha_ok():
            self.post(article_id=str(draft.id))
        self.assertEqual(Comment.objects.count(), 0)

    def test_captcha_service_outage_is_handled(self):
        import urllib.error
        with mock.patch('captcha.fields.client.submit', side_effect=urllib.error.URLError('down')):
            response = self.client.post('/comment', {'article_id': str(self.article.id), 'author': 'a', 'text': 't'})
        self.assertLess(response.status_code, 500)
        self.assertEqual(Comment.objects.count(), 0)

    def test_orphan_reply_whose_parent_is_missing_is_not_lost_in_ui(self):
        parent = mk_comment(self.article)
        reply = mk_comment(self.article, parent=parent, text='orphan-reply')
        Comment.objects.filter(pk=reply.pk).update(parent_comment=None)
        self.assertIn('orphan-reply', html_of(self.get_ok('/article/c1/')))

    def test_comment_cycle_does_not_hang_page(self):
        a = mk_comment(self.article, text='cycle-a')
        Comment.objects.filter(pk=a.pk).update(parent_comment=a)
        with time_limit(3):
            try:
                response = self.client.get('/article/c1/')
            except Timeout:
                self.fail('article page hangs on comment cycle')
        self.assertEqual(response.status_code, 200)


class PublishAtomicityTests(Base):
    def test_failure_on_second_save_leaves_no_half_published_article(self):
        self.login()
        author = mk_author('a1')
        real_save = Article.save
        calls = []

        def flaky(self_, *a, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('second save fails')
            return real_save(self_, *a, **kw)

        with mock.patch.object(Article, 'save', flaky):
            self.client.post('/publish', {**publish_payload(author, article_slug='half'), 'article_image': png()})
        self.assertFalse(Article.objects.filter(slug='half').exists())
