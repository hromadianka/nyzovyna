from datetime import timedelta

from django.urls import reverse
from django.utils.timezone import now

from app.models import AboutUsText, Article, Category

from .helpers import (Base, captcha_ok, html_of, mk_article, mk_author, mk_category, mk_comment, seed_site,
                      visible_text)

PUBLIC_LIST_URLS = ['/', '/all', '/category/root/', '/category/child/', '/authors/author-1', '/search/?q=Title']


class HomeTests(Base):
    def test_empty_db_home_ok(self):
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_empty_db_public_pages_ok(self):
        for url in ['/', '/all', '/authors', '/search/', '/search/?q=x', '/feed/', '/sitemap.xml']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_latest_limited_to_five_newest_first(self):
        for i in range(8):
            mk_article(f'n{i}', publish_at=now() - timedelta(hours=8 - i))
        html = html_of(self.get_ok('/'))
        latest = html.split('Найпопулярніші')[0]
        for i in (3, 4, 5, 6, 7):
            self.assertIn(f'/article/n{i}/', latest)
        for i in (0, 1, 2):
            self.assertNotIn(f'/article/n{i}/', latest)

    def test_latest_section_is_newest_first(self):
        for i in range(3):
            mk_article(f'o{i}', publish_at=now() - timedelta(hours=10 - i))
        latest = html_of(self.get_ok('/')).split('Найпопулярніші')[0]
        self.in_order(latest, '/article/o2/', '/article/o1/', '/article/o0/')

    def test_popular_section_most_viewed_first(self):
        for i, v in enumerate([5, 50, 20]):
            mk_article(f'p{i}', views=v)
        popular = html_of(self.get_ok('/')).split('Найпопулярніші')[1]
        self.in_order(popular, '/article/p1/', '/article/p2/', '/article/p0/')

    def test_unpublished_hidden_on_home(self):
        mk_article('draft', published=False)
        self.assertNotIn('/article/draft/', html_of(self.get_ok('/')))

    def test_language_filter_ua_default(self):
        mk_article('ua-one', language='ua')
        mk_article('en-one', language='en')
        html = html_of(self.get_ok('/'))
        self.assertIn('/article/ua-one/', html)
        self.assertNotIn('/article/en-one/', html)

    def test_language_filter_en_cookie(self):
        mk_article('ua-one', language='ua')
        mk_article('en-one', language='en')
        self.client.cookies['django_language'] = 'en'
        html = html_of(self.get_ok('/'))
        self.assertIn('/article/en-one/', html)
        self.assertNotIn('/article/ua-one/', html)

    def test_future_dated_published_flag_hidden_on_home(self):
        mk_article('future', publish_at=now() + timedelta(days=3))
        self.assertNotIn('/article/future/', html_of(self.get_ok('/')))

    def test_scheduled_article_appears_after_its_time_without_external_job(self):
        article = mk_article('sched', publish_at=now() + timedelta(hours=2))
        self.assertNotIn('/article/sched/', html_of(self.get_ok('/')))
        type(article).objects.filter(pk=article.pk).update(publish_at=now() - timedelta(minutes=1))
        self.assertIn('/article/sched/', html_of(self.get_ok('/')))

    def test_article_without_image_renders_home(self):
        a = mk_article('noimg')
        Article.objects.filter(pk=a.pk).update(image='')
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_article_without_category_renders_home(self):
        mk_article('nocat')
        self.assertIn('/article/nocat/', html_of(self.get_ok('/')))

    def test_html_in_text_stripped_in_card(self):
        mk_article('tags', text='<p>visible <b>bold</b></p><script>alert(1)</script>')
        html = html_of(self.get_ok('/'))
        self.assertNotIn('<script>alert(1)', html)

    def test_title_with_markup_is_not_rendered_as_markup(self):
        mk_article('mk', name='<i>Hi</i> there')
        self.assertNotIn('<i>Hi</i>', html_of(self.get_ok('/')))

    def test_home_has_all_articles_link(self):
        self.assertIn(reverse('all_articles'), html_of(self.get_ok('/')))


class CategoryTests(Base):
    def setUp(self):
        super().setUp()
        self.root, self.child, self.author, self.arts = seed_site(4)

    def test_category_ok_and_lists_articles(self):
        html = html_of(self.get_ok('/category/root/'))
        for a in self.arts:
            self.assertIn(f'/article/{a.slug}/', html)

    def test_nested_category_ok(self):
        self.assertIn('/article/seed-0/', html_of(self.get_ok('/category/child/')))

    def test_category_title_shown_in_ua(self):
        self.assertIn('ua-root', html_of(self.get_ok('/category/root/')))

    def test_category_title_shown_in_en(self):
        self.client.cookies['django_language'] = 'en'
        self.assertIn('en-root', html_of(self.get_ok('/category/root/')))

    def test_category_without_articles_ok(self):
        mk_category('empty')
        self.assertEqual(self.client.get('/category/empty/').status_code, 200)

    def test_unknown_category_404(self):
        self.assertEqual(self.client.get('/category/nope/').status_code, 404)

    def test_category_hides_unpublished(self):
        mk_article('hid', cats=[self.root], published=False)
        self.assertNotIn('/article/hid/', html_of(self.get_ok('/category/root/')))

    def test_category_hides_other_language(self):
        mk_article('enx', cats=[self.root], language='en')
        self.assertNotIn('/article/enx/', html_of(self.get_ok('/category/root/')))

    def test_category_hides_future_dated(self):
        mk_article('fut', cats=[self.root], publish_at=now() + timedelta(days=2))
        self.assertNotIn('/article/fut/', html_of(self.get_ok('/category/root/')))


    def test_category_order_newest_first_regardless_of_insert_order(self):
        for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2]):
            with self.subTest(order=order):
                Article.objects.all().delete()
                for i in order:
                    mk_article(f'ord{i}', cats=[self.root], publish_at=now() - timedelta(days=10 - i))
                html = html_of(self.get_ok('/category/root/'))
                self.in_order(html, '/article/ord2/', '/article/ord1/', '/article/ord0/')

    def test_all_articles_order_newest_first_regardless_of_insert_order(self):
        for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2]):
            with self.subTest(order=order):
                Article.objects.all().delete()
                for i in order:
                    mk_article(f'all{i}', publish_at=now() - timedelta(days=10 - i))
                html = html_of(self.get_ok('/all'))
                self.in_order(html, '/article/all2/', '/article/all1/', '/article/all0/')

    def test_author_page_order_newest_first_regardless_of_insert_order(self):
        for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2]):
            with self.subTest(order=order):
                Article.objects.all().delete()
                for i in order:
                    mk_article(f'au{i}', author=self.author, publish_at=now() - timedelta(days=10 - i))
                html = html_of(self.get_ok('/authors/author-1'))
                self.in_order(html, '/article/au2/', '/article/au1/', '/article/au0/')

    def test_search_order_newest_first_regardless_of_insert_order(self):
        for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2]):
            with self.subTest(order=order):
                Article.objects.all().delete()
                for i in order:
                    mk_article(f'se{i}', name=f'needle {i}', publish_at=now() - timedelta(days=10 - i))
                html = html_of(self.get_ok('/search/?q=needle'))
                self.in_order(html, '/article/se2/', '/article/se1/', '/article/se0/')

    def test_all_articles_page_title(self):
        self.assertIn('Всі статті', html_of(self.get_ok('/all')))

    def test_all_articles_hides_unpublished(self):
        mk_article('hid2', published=False)
        self.assertNotIn('/article/hid2/', html_of(self.get_ok('/all')))

    def test_category_is_bounded_in_size_with_many_articles(self):
        for i in range(300):
            mk_article(f'big{i}', cats=[self.root], text='<p>' + 'word ' * 400 + '</p>')
        self.assertLess(len(self.get_ok('/category/root/').content), 400_000)

    def test_all_articles_bounded_in_size_with_many_articles(self):
        for i in range(300):
            mk_article(f'big{i}', text='<p>' + 'word ' * 400 + '</p>')
        self.assertLess(len(self.get_ok('/all').content), 400_000)


class ArticlePageTests(Base):
    def setUp(self):
        super().setUp()
        self.root, self.child, self.author, self.arts = seed_site(3)
        self.article = self.arts[0]

    def test_article_ok_and_content(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn(self.article.name, html)
        self.assertIn('<p>body</p>', html)

    def test_article_shows_author_and_categories(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn('Ua author-1', html)
        self.assertIn('ua-root', html)

    def test_article_en_interface_shows_en_names(self):
        self.client.cookies['django_language'] = 'en'
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn('En author-1', html)
        self.assertIn('en-root', html)

    def test_view_counter_increments_once_per_get(self):
        before = Article.objects.get(pk=self.article.pk).views
        self.client.get('/article/seed-0/')
        self.assertEqual(Article.objects.get(pk=self.article.pk).views, before + 1)

    def test_unknown_article_404(self):
        self.assertEqual(self.client.get('/article/nope/').status_code, 404)

    def test_unpublished_article_is_not_public(self):
        mk_article('secret', published=False)
        self.assertEqual(self.client.get('/article/secret/').status_code, 404)

    def test_scheduled_article_is_not_public(self):
        mk_article('later', published=False, publish_at=now() + timedelta(days=1))
        self.assertEqual(self.client.get('/article/later/').status_code, 404)

    def test_unpublished_article_view_does_not_count(self):
        a = mk_article('secret2', published=False)
        self.client.get('/article/secret2/')
        a.refresh_from_db()
        self.assertEqual(a.views, 0)

    def test_unpublished_visible_to_logged_in_editor(self):
        mk_article('secret3', published=False)
        self.login()
        self.assertEqual(self.client.get('/article/secret3/').status_code, 200)

    def test_article_without_author_ok(self):
        mk_article('noauth')
        self.assertEqual(self.client.get('/article/noauth/').status_code, 200)

    def test_article_without_category_ok(self):
        mk_article('nocat2')
        self.assertEqual(self.client.get('/article/nocat2/').status_code, 200)

    def test_article_without_image_ok(self):
        a = mk_article('noimg2')
        Article.objects.filter(pk=a.pk).update(image='')
        self.assertEqual(self.client.get('/article/noimg2/').status_code, 200)

    def test_article_author_without_slug_ok(self):
        author = mk_author('tmp')
        mk_article('noslugauthor', author=author)
        type(author).objects.filter(pk=author.pk).update(slug=None)
        self.assertEqual(self.client.get('/article/noslugauthor/').status_code, 200)

    def test_article_in_other_language_still_reachable(self):
        mk_article('en-only', language='en')
        self.assertEqual(self.client.get('/article/en-only/').status_code, 200)

    def test_article_author_photo_rendered_when_present(self):
        author = mk_author('withpic')
        mk_article('pic', author=author)
        self.assertIn('author-img-overlay', html_of(self.get_ok('/article/pic/')))

    def test_recommended_falls_back_to_popular_when_no_category(self):
        mk_article('x1', views=9)
        mk_article('x2', views=3)
        html = html_of(self.get_ok('/article/x2/'))
        self.assertIn('/article/x1/', html)

    def test_article_text_is_rendered_unescaped_by_design(self):
        mk_article('rich', text='<h2>Sub</h2><p>x</p>')
        self.assertIn('<h2>Sub</h2>', html_of(self.get_ok('/article/rich/')))

    def test_article_page_has_comment_form_with_hidden_article_id(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn(str(self.article.id), html)

    def test_view_counter_displayed_matches_db(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertEqual(Article.objects.get(pk=self.article.pk).views, 1)
        self.assertIn('<p>1</p>', html)


class AuthorAndAboutTests(Base):
    def test_authors_list_empty_ok(self):
        self.assertEqual(self.client.get('/authors').status_code, 200)

    def test_authors_list_shows_authors(self):
        mk_author('a1')
        mk_author('a2')
        html = html_of(self.get_ok('/authors'))
        self.assertIn('/authors/a1', html)
        self.assertIn('/authors/a2', html)

    def test_authors_list_is_ordered_deterministically(self):
        for s in ['b', 'a', 'c']:
            mk_author(s, name_en=f'Name {s}')
        html = html_of(self.get_ok('/authors'))
        self.in_order(html, 'Name a', 'Name b', 'Name c')

    def test_author_detail_ok_and_lists_published_only(self):
        author = mk_author('a1')
        mk_article('pub', author=author)
        mk_article('dr', author=author, published=False)
        html = html_of(self.get_ok('/authors/a1'))
        self.assertIn('/article/pub/', html)
        self.assertNotIn('/article/dr/', html)

    def test_author_detail_hides_future_dated(self):
        author = mk_author('a1')
        mk_article('fut', author=author, publish_at=now() + timedelta(days=1))
        self.assertNotIn('/article/fut/', html_of(self.get_ok('/authors/a1')))

    def test_author_detail_unknown_404(self):
        self.assertEqual(self.client.get('/authors/none').status_code, 404)

    def test_author_detail_en_language(self):
        mk_author('a1')
        self.client.cookies['django_language'] = 'en'
        self.assertIn('En a1', html_of(self.get_ok('/authors/a1')))

    def test_author_without_image_ok(self):
        author = mk_author('noimg')
        type(author).objects.filter(pk=author.pk).update(image='')
        self.assertEqual(self.client.get('/authors/noimg').status_code, 200)
        self.assertEqual(self.client.get('/authors').status_code, 200)

    def test_about_us_on_fresh_install(self):
        self.assertEqual(self.client.get('/about-us').status_code, 200)

    def test_about_us_shows_ua_text(self):
        AboutUsText.objects.create(pk=1, text_ua='український текст', text_en='english text')
        self.assertIn('український текст', html_of(self.get_ok('/about-us')))

    def test_about_us_shows_en_text(self):
        AboutUsText.objects.create(pk=1, text_ua='український текст', text_en='english text')
        self.client.cookies['django_language'] = 'en'
        self.assertIn('english text', html_of(self.get_ok('/about-us')))

    def test_about_us_works_when_row_has_other_pk(self):
        AboutUsText.objects.create(pk=5, text_ua='other', text_en='other')
        self.assertEqual(self.client.get('/about-us').status_code, 200)


class SearchTests(Base):
    def test_search_by_title_case_insensitive_ascii(self):
        mk_article('s1', name='Alpha Beta')
        self.assertIn('/article/s1/', html_of(self.get_ok('/search/?q=alpha')))

    def test_search_by_title_case_insensitive_cyrillic(self):
        mk_article('s2', name='Привіт Світ')
        self.assertIn('/article/s2/', html_of(self.get_ok('/search/?q=привіт')))

    def test_search_in_body(self):
        mk_article('s3', name='Zzz', text='<p>needle in body</p>')
        self.assertIn('/article/s3/', html_of(self.get_ok('/search/?q=needle')))

    def test_search_does_not_match_html_markup(self):
        mk_article('s4', name='Zzz', text='<strong class="highlight">x</strong>')
        self.assertNotIn('/article/s4/', html_of(self.get_ok('/search/?q=highlight')))

    def test_search_hides_unpublished(self):
        mk_article('s5', name='needle', published=False)
        self.assertNotIn('/article/s5/', html_of(self.get_ok('/search/?q=needle')))

    def test_search_hides_future(self):
        mk_article('s6', name='needle', publish_at=now() + timedelta(days=1))
        self.assertNotIn('/article/s6/', html_of(self.get_ok('/search/?q=needle')))

    def test_search_respects_interface_language(self):
        mk_article('s7', name='needle', language='en')
        self.assertNotIn('/article/s7/', html_of(self.get_ok('/search/?q=needle')))

    def test_search_wildcards_are_literal(self):
        mk_article('s8', name='plain title')
        for q in ['%', '_', '%%', '\\']:
            with self.subTest(q=q):
                self.assertNotIn('/article/s8/', html_of(self.get_ok('/search/', data={'q': q})))

    def test_empty_query_does_not_dump_catalog(self):
        mk_article('s9', name='anything')
        self.assertNotIn('/article/s9/', html_of(self.get_ok('/search/?q=')))

    def test_whitespace_query_does_not_dump_catalog(self):
        mk_article('s10', name='anything')
        self.assertNotIn('/article/s10/', html_of(self.get_ok('/search/?q=%20%20')))

    def test_search_no_results_has_message(self):
        text = visible_text(html_of(self.get_ok('/search/?q=zzzzzz')))
        self.assertTrue('нічого' in text.lower() or 'not found' in text.lower() or 'немає' in text.lower())

    def test_search_query_echoed_in_input_escaped(self):
        html = html_of(self.get_ok('/search/', data={'q': '"><script>alert(1)</script>'}))
        self.assertNotIn('<script>alert(1)</script>', html)

    def test_search_result_count_is_bounded(self):
        for i in range(150):
            mk_article(f'many{i}', name='common word')
        self.assertLess(html_of(self.get_ok('/search/?q=common')).count('class="article-card"'), 101)

    def test_search_multiword_query(self):
        mk_article('s11', name='red green blue')
        self.assertIn('/article/s11/', html_of(self.get_ok('/search/?q=red green')))

    def test_search_very_long_query_ok(self):
        self.assertEqual(self.client.get('/search/', data={'q': 'я' * 20000}).status_code, 200)



class FeedSitemapMiscTests(Base):
    def setUp(self):
        super().setUp()
        self.root, self.child, self.author, self.arts = seed_site(3)

    def test_feed_lists_only_published_current_language(self):
        mk_article('fd-draft', published=False)
        mk_article('fd-en', language='en')
        body = html_of(self.get_ok('/feed/'))
        self.assertNotIn('fd-draft', body)
        self.assertNotIn('fd-en', body)
        self.assertIn('seed-0', body)

    def test_feed_has_at_most_five_items(self):
        for i in range(10):
            mk_article(f'f{i}')
        self.assertLessEqual(html_of(self.get_ok('/feed/')).count('<item>'), 5)

    def test_feed_newest_first_by_publish_date(self):
        old = mk_article('fd-old', publish_at=now() - timedelta(days=30))
        Article.objects.filter(pk=old.pk).update(created_at=now() + timedelta(days=1))
        body = html_of(self.get_ok('/feed/'))
        self.assertLess(body.find('seed-0'), body.find('fd-old') if 'fd-old' in body else 10 ** 9)

    def test_feed_excludes_future_dated(self):
        mk_article('fd-fut', publish_at=now() + timedelta(days=1))
        self.assertNotIn('fd-fut', html_of(self.get_ok('/feed/')))

    def test_feed_content_type_is_rss(self):
        self.assertIn('rss', self.get_ok('/feed/')['Content-Type'])

    def test_sitemap_has_only_published(self):
        mk_article('sm-draft', published=False)
        body = html_of(self.get_ok('/sitemap.xml'))
        self.assertNotIn('sm-draft', body)
        self.assertIn('seed-0', body)

    def test_sitemap_lists_categories(self):
        self.assertIn('/category/root/', html_of(self.get_ok('/sitemap.xml')))

    def test_sitemap_locations_use_real_domain(self):
        body = html_of(self.get_ok('/sitemap.xml'))
        self.assertNotIn('example.com', body)

    def test_sitemap_lastmod_is_stable_between_requests(self):
        import re
        a = re.findall(r'<lastmod>(.*?)</lastmod>', html_of(self.get_ok('/sitemap.xml')))
        b = re.findall(r'<lastmod>(.*?)</lastmod>', html_of(self.get_ok('/sitemap.xml')))
        self.assertEqual(sorted(set(a)), sorted(set(b)))

    def test_robots_txt_exists(self):
        self.assertEqual(self.client.get('/robots.txt').status_code, 200)

    def test_healthz_exists(self):
        self.assertEqual(self.client.get('/healthz').status_code, 200)

    def test_custom_404_page_is_branded(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)
        self.assertIn('Низовина', html_of(response))


    def test_custom_500_template_exists(self):
        from .helpers import TEMPLATES_DIR
        self.assertTrue((TEMPLATES_DIR / '500.html').exists())

    def test_404_page_has_menu_and_link_home(self):
        self.assertIn('href="/"', html_of(self.client.get('/no-such-page/')))


    def test_login_page_ok(self):
        self.assertEqual(self.client.get('/login/').status_code, 200)

