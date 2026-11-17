"""List pages must not pull whole articles from the database.

The database is billed by the volume of data it sends. A card shows a 160-700 character excerpt, so list pages
load only the start of the plain text (Article.card()); the full text is read only on the article page itself.
Run: DJANGO_SETTINGS_MODULE=anarchia.settings_test python manage.py test app.test_card_queries
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.template.defaultfilters import linebreaks_filter, striptags, truncatechars
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import Article, Author

BODY = '<p>' + ('слово ' * 400) + '</p>'  # far longer than any excerpt
TEXT_COLUMN = '"app_article"."text"'
SEARCH_COLUMN = '"app_article"."search_text"'


class ListPagesSkipFullText(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = Author.objects.create(name_ua='a', name_en='a', slug='a')
        for i in range(4):
            Article.objects.create(name=f'n{i}', slug=f'n{i}', text=BODY, is_published=True, author=cls.author)

    def setUp(self):
        cache.clear()

    def selects_of(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response, [q['sql'] for q in ctx.captured_queries if 'app_article' in q['sql']]

    def test_list_pages_do_not_select_the_full_text(self):
        for url in ('/', '/all', '/authors/a', '/search/?q=слово', '/sitemap.xml'):
            _, sqls = self.selects_of(url)
            self.assertFalse([s for s in sqls if TEXT_COLUMN in s], f'{url} selects the full article text')

    def test_list_pages_only_read_the_start_of_the_search_copy(self):
        for url in ('/', '/all', '/authors/a'):
            _, sqls = self.selects_of(url)
            bare = [s.replace('SUBSTR(' + SEARCH_COLUMN, '') for s in sqls]
            self.assertFalse([s for s in bare if SEARCH_COLUMN in s], f'{url} selects the whole search_text')

    def test_cards_still_show_the_excerpt_without_extra_queries(self):
        response, sqls = self.selects_of('/all')
        self.assertContains(response, 'слово слово')
        self.assertContains(response, '…')  # the 700 character cut
        self.assertLessEqual(len(sqls), 2)  # page + count, not one query per card

    def test_article_page_skips_the_search_copy_and_other_cards_skip_the_text(self):
        _, sqls = self.selects_of('/article/n0/')
        self.assertFalse([s for s in sqls if SEARCH_COLUMN in s.replace('SUBSTR(' + SEARCH_COLUMN, '')])
        others = [s for s in sqls if TEXT_COLUMN in s]
        self.assertEqual(len(others), 1, 'only the article itself needs its full text')


class ExcerptProperty(TestCase):
    def test_falls_back_to_the_full_text_when_not_loaded_as_a_card(self):
        Article.objects.create(name='x', slug='x', text='<p>hello</p>', is_published=True)
        self.assertEqual(Article.objects.get(slug='x').excerpt, '<p>hello</p>')
        self.assertEqual(Article.objects.card().get(slug='x').excerpt, 'hello')


class EditorCabinetSkipsText(TestCase):
    def test_cabinet_rows_do_not_load_the_text_or_query_per_row(self):
        for i in range(6):
            Article.objects.create(name=f'c{i}', slug=f'c{i}', text=BODY, is_published=i % 2 == 0)
        User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.login(username='boss', password='pw')
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('editor_cabinet'))
        self.assertEqual(response.status_code, 200)
        sqls = [q['sql'] for q in ctx.captured_queries if 'app_article' in q['sql']]
        self.assertFalse([q for q in sqls if TEXT_COLUMN in q or SEARCH_COLUMN in q], 'the cabinet only lists titles')
        self.assertContains(response, 'article-c0')
        self.assertContains(response, 'article-c1')  # a draft is listed too


class ExcerptMatchesTheOldRendering(TestCase):
    """The cards used to render the full text through linebreaks|striptags; the excerpt must read the same."""

    @staticmethod
    def render(limit, value):
        """What the card templates do inside {% autoescape off %}: value|linebreaks|striptags|truncatechars:limit."""
        return truncatechars(striptags(linebreaks_filter(value, autoescape=False)), limit)

    def test_same_words_for_html_with_entities_and_paragraphs(self):
        html = ('<p>Перший&nbsp;абзац &mdash; з <strong>виділенням</strong> і <a href="/x">посиланням</a>.</p>\n'
                '<p>Другий абзац.</p>' * 40)
        Article.objects.create(name='h', slug='h', text=html, is_published=True)
        card = Article.objects.card().get(slug='h')
        for limit in (160, 700):
            old, new = self.render(limit, card.text), self.render(limit, card.excerpt)
            self.assertEqual(' '.join(old.split())[:limit - 40], ' '.join(new.split())[:limit - 40])
            self.assertTrue(new.endswith('…'))
