import re
from datetime import timedelta

from django.urls import reverse
from django.utils.timezone import now

from .helpers import Base, html_of, mk_article, mk_author, mk_category


class CabinetTests(Base):
    def setUp(self):
        super().setUp()
        self.login()

    def cabinet(self):
        return html_of(self.get_ok('/editor-cabinet'))

    def test_every_author_has_an_edit_link_in_the_default_ukrainian_ui(self):
        author = mk_author('a1')
        self.assertIn(reverse('edit_author', args=[author.slug]), self.cabinet())

    def test_cabinet_links_to_comment_moderation(self):
        self.assertIn(reverse('comments_moderation'), self.cabinet())

    def test_every_article_row_carries_the_id_the_delete_script_removes(self):
        mk_article('live')
        mk_article('later', publish_at=now() + timedelta(days=2))
        html = self.cabinet()
        self.assertIn('id="article-live"', html)
        self.assertIn('id="article-later"', html)

    def test_subcategories_can_be_deleted_from_the_cabinet(self):
        child = mk_category('child', parent=mk_category('root'))
        html = self.cabinet()
        self.assertIn(f"confirmDeleteCategory(event, '{child.slug}')", html)
        self.assertIn(f'id="category-{child.slug}"', html)

    def test_published_articles_are_listed_newest_first(self):
        mk_article('old-one', publish_at=now() - timedelta(days=3))
        mk_article('new-one', publish_at=now() - timedelta(hours=1))
        html = self.cabinet()
        self.in_order(html, 'id="article-new-one"', 'id="article-old-one"')

    def test_scheduled_articles_are_listed_soonest_first(self):
        mk_article('far', publish_at=now() + timedelta(days=9))
        mk_article('soon', publish_at=now() + timedelta(days=1))
        self.in_order(self.cabinet(), 'id="article-soon"', 'id="article-far"')

    def test_empty_scheduled_list_says_so(self):
        self.assertIn('Відкладених статей немає', self.cabinet())

    def test_logout_is_still_a_post_form(self):
        html = self.cabinet()
        self.assertRegex(html, r'<form method="POST" action="%s"' % re.escape(reverse('logout')))
