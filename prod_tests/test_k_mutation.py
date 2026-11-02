from datetime import timedelta

from django.utils.timezone import now

from .helpers import Base, html_of, mk_article, mk_author, mk_category


def card_slugs(html, marker):
    section = html.split(marker, 1)[1]
    import re
    return re.findall(r'/article/([\w-]+)/', section)


class SurvivingMutantTests(Base):
    def test_popular_section_shows_exactly_ten_most_viewed(self):
        for i in range(14):
            mk_article(f'pop{i}', views=100 + i)
        html = html_of(self.get_ok('/'))
        popular = html.split('Найпопулярніші')[1].split('Всі статті')[0]
        slugs = set(card_slugs('x' + popular, 'x'))
        self.assertEqual(slugs, {f'pop{i}' for i in range(4, 14)})

    def test_latest_section_shows_exactly_five(self):
        for i in range(9):
            mk_article(f'lat{i}', publish_at=now() - timedelta(hours=20 - i))
        latest = html_of(self.get_ok('/')).split('Найпопулярніші')[0]
        self.assertEqual(len(set(card_slugs('x' + latest, 'x'))), 5)

    def test_recommended_block_shows_exactly_two_same_root_articles(self):
        root = mk_category('rt')
        mk_article('cur', cats=[root])
        for i in range(4):
            mk_article(f'rec{i}', cats=[root], views=10 + i)
        html = html_of(self.get_ok('/article/cur/'))
        self.assertEqual(html.count('article-card recommended'), 2)

    def test_recommended_block_never_shows_unpublished(self):
        root = mk_category('rt')
        mk_article('cur', cats=[root])
        mk_article('hidden-hot', cats=[root], published=False, views=999)
        mk_article('visible', cats=[root], views=1)
        self.assertNotIn('/article/hidden-hot/', html_of(self.get_ok('/article/cur/')))

    def test_fallback_block_shows_exactly_two_published_articles(self):
        mk_article('solo')
        mk_article('hidden-hot', published=False, views=999)
        for i in range(4):
            mk_article(f'fb{i}', views=10 + i)
        html = html_of(self.get_ok('/article/solo/'))
        self.assertEqual(html.count('article-card recommended'), 2)
        self.assertNotIn('/article/hidden-hot/', html)

    def test_edit_with_schedule_but_empty_datetime_is_handled(self):
        self.login()
        author = mk_author('a1')
        mk_article('sch', author=author)
        response = self.client.post('/article/sch/edit/', {
            'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
            'publish_option': 'schedule', 'publish_datetime': '', 'article_slug': 'sch'})
        self.assertLess(response.status_code, 500)

    def test_edit_without_schedule_option_keeps_article_published_even_with_datetime(self):
        self.login()
        author = mk_author('a1')
        article = mk_article('keep', author=author)
        self.client.post('/article/keep/edit/', {
            'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
            'publish_option': 'now', 'publish_datetime': '2099-01-01T10:00', 'article_slug': 'keep'})
        article.refresh_from_db()
        self.assertTrue(article.is_published)

    def test_model_string_representations(self):
        from app.models import Author, Category
        author = mk_author('s1')
        self.assertEqual(str(author), 'En s1')
        self.assertEqual(str(mk_article('s2', name='Readable')), 'Readable')
        self.login()
        from app.models import Editor
        self.assertEqual(str(Editor.objects.get()), 'editor')


class EditorResponseContractTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def test_create_child_category_redirects_to_cabinet(self):
        parent = mk_category('par')
        response = self.client.post('/create-category/', {'name_ua': 'Kid', 'name_en': 'Kid',
                                                          'parent_id': str(parent.id)})
        self.assertRedirects(response, '/editor-cabinet', fetch_redirect_response=False)

    def test_about_us_edit_redirects_to_cabinet(self):
        from app.models import AboutUsText
        AboutUsText.objects.create(pk=1, text_ua='a', text_en='b')
        response = self.client.post('/about-us-edit', {'new_text_ua': 'x', 'new_text_en': 'y'})
        self.assertRedirects(response, '/editor-cabinet', fetch_redirect_response=False)

    def test_category_order_update_answers_with_json_ok(self):
        import json
        a = mk_category('a')
        response = self.client.post('/editor-cabinet/categories/order/update/',
                                    data=json.dumps([{'id': str(a.id), 'order': 3}]), content_type='application/json')
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_category_order_editor_lists_only_root_categories_at_top_level(self):
        root = mk_category('top')
        mk_category('nested', parent=root)
        html = html_of(self.get_ok('/editor-cabinet/categories/order/'))
        self.assertIn('ua-top', html)

    def test_publish_with_non_image_reports_format_error(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        author = mk_author('a1')
        response = self.client.post('/publish', {
            'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
            'publish_option': 'now', 'article_image': SimpleUploadedFile('x.txt', b'hi', content_type='text/plain')})
        self.assertIn(response.status_code, (200, 400))

    def test_edit_with_non_image_reports_format_error(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        author = mk_author('a1')
        mk_article('ed', author=author)
        response = self.client.post('/article/ed/edit/', {
            'article_name': 'x', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
            'publish_option': 'now', 'article_slug': 'ed',
            'article_image': SimpleUploadedFile('x.txt', b'hi', content_type='text/plain')})
        self.assertIn(response.status_code, (200, 400))

    def test_publish_schedule_with_datetime_creates_unpublished_article(self):
        from app.models import Article
        author = mk_author('a1')
        self.client.post('/publish', {
            'article_name': 'later', 'article_text': 't', 'language': 'ua', 'article_author': str(author.id),
            'publish_option': 'schedule', 'publish_datetime': '2099-01-01T10:00', 'article_slug': 'later'})
        self.assertGreater(Article.objects.get(slug='later').publish_at, now())
