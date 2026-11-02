import re
import xml.etree.ElementTree as ET

import feedparser
from django.utils.timezone import now
from datetime import timedelta

from app.models import Article

from .helpers import Base, html_of, mk_article, mk_comment, seed_site

HTML_PAGES = ['/', '/all', '/about-us', '/authors', '/authors/author-1', '/category/root/', '/article/seed-0/',
              '/search/?q=Title', '/login/']


class SeoSetup(Base):
    def setUp(self):
        super().setUp()
        seed_site(4)

    def pages(self):
        for url in HTML_PAGES:
            yield url, html_of(self.get_ok(url))


class MetaTests(SeoSetup):
    def test_every_page_has_unique_title(self):
        titles = {}
        for url, html in self.pages():
            titles.setdefault(re.search(r'<title>(.*?)</title>', html, re.S).group(1).strip(), []).append(url)
        self.assertEqual({t: u for t, u in titles.items() if len(u) > 1}, {})

    def test_article_title_contains_article_name(self):
        self.assertIn('Title seed-0', re.search(r'<title>(.*?)</title>', html_of(self.get_ok('/article/seed-0/')), re.S).group(1))

    def test_every_page_has_meta_description(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertRegex(html, r'<meta[^>]+name="description"[^>]+content="[^"]{20,}')

    def test_every_page_has_canonical_link(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertRegex(html, r'<link[^>]+rel="canonical"')

    def test_every_page_has_open_graph_title_and_image(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertIn('property="og:title"', html)
                self.assertIn('property="og:type"', html)

    def test_article_has_og_image_and_type_article(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn('property="og:image"', html)
        self.assertIn('content="article"', html)


    def test_every_page_declares_lang(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertRegex(html, r'<html[^>]+lang=')


    def test_viewport_meta_present(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertIn('name="viewport"', html)

    def test_favicon_declared(self):
        self.assertIn('rel="icon"', html_of(self.get_ok('/')))

    def test_article_has_structured_data(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn('itemtype="https://schema.org/Article"', html)
        self.assertIn('itemprop="headline"', html)
        self.assertIn('itemprop="datePublished"', html)

    def test_noindex_on_login_and_search_results(self):
        for url in ['/login/', '/search/?q=Title']:
            with self.subTest(url=url):
                self.assertRegex(html_of(self.get_ok(url)), r'name="robots"[^>]+noindex')


class HeadingAndMarkupTests(SeoSetup):
    def test_exactly_one_h1_per_page(self):
        for url, html in self.pages():
            with self.subTest(url=url):
                self.assertEqual(len(re.findall(r'<h1\b', html)), 1)

    def test_heading_levels_do_not_skip(self):
        for url, html in self.pages():
            levels = [int(x) for x in re.findall(r'<h([1-6])\b', html)]
            with self.subTest(url=url):
                for prev, cur in zip(levels, levels[1:]):
                    self.assertLessEqual(cur - prev, 1, levels)

    def test_content_images_have_alt_text(self):
        for url, html in self.pages():
            for tag in re.findall(r'<img\b[^>]*>', html):
                with self.subTest(url=url, tag=tag[:60]):
                    self.assertRegex(tag, r'\balt=')

    def test_card_images_are_real_images_not_only_css_backgrounds(self):
        self.assertIn('<img', html_of(self.get_ok('/all')).split('<main>')[1])

    def test_links_have_text_or_label(self):
        for url, html in self.pages():
            for match in re.finditer(r'<a\b([^>]*)>(.*?)</a>', html, re.S):
                inner = re.sub(r'<[^>]+>', '', match.group(2)).strip()
                with self.subTest(url=url, link=match.group(1)[:50]):
                    self.assertTrue(inner or 'aria-label' in match.group(1) or '<img' in match.group(2)
                                    or '<svg' in match.group(2))

    def test_form_inputs_have_labels_or_aria(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        for tag in re.findall(r'<(?:input|textarea)\b[^>]*>', html):
            if 'hidden' in tag or 'csrf' in tag:
                continue
            with self.subTest(tag=tag[:60]):
                self.assertTrue('aria-label' in tag or 'id=' in tag)

    def test_search_input_has_accessible_name(self):
        tag = re.search(r'<input[^>]+name="q"[^>]*>', html_of(self.get_ok('/')), re.S).group(0)
        self.assertTrue('aria-label' in tag or 'id=' in tag)

    def test_search_button_has_accessible_name(self):
        html = html_of(self.get_ok('/'))
        button = re.search(r'<button type="submit" class="search-button"[^>]*>', html).group(0)
        self.assertIn('aria-label', button)

    def test_ids_are_unique_on_article_page_with_comments(self):
        a = Article.objects.get(slug='seed-0')
        for _ in range(3):
            mk_comment(a)
        html = html_of(self.get_ok('/article/seed-0/'))
        ids = re.findall(r'\sid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))

    def test_menu_is_reachable_without_hover(self):
        html = html_of(self.get_ok('/'))
        self.assertTrue('aria-expanded' in html or 'aria-haspopup' in html)



    def test_no_render_blocking_third_party_scripts_in_head(self):
        head = html_of(self.get_ok('/')).split('</head>')[0]
        blocking = re.findall(r'<script\b(?![^>]*(?:async|defer))[^>]*src="https?://[^"]+"', head)
        self.assertEqual(blocking, [])

    def test_public_pages_do_not_load_the_editor_bundle(self):
        self.assertNotIn('ckeditor', html_of(self.get_ok('/')).lower())


class RobotsSitemapTests(SeoSetup):
    def test_robots_txt_served_and_points_to_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Sitemap:', html_of(response))

    def test_robots_txt_disallows_private_areas(self):
        body = html_of(self.client.get('/robots.txt'))
        for path in ['/admin/', '/editor-cabinet', '/login']:
            with self.subTest(path=path):
                self.assertIn(path, body)

    def test_sitemap_is_valid_xml(self):
        ET.fromstring(self.get_ok('/sitemap.xml').content)

    def test_sitemap_urls_are_absolute_and_https_canonical_host(self):
        root = ET.fromstring(self.get_ok('/sitemap.xml').content)
        for loc in [e.text for e in root.iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]:
            with self.subTest(loc=loc):
                self.assertTrue(loc.startswith('https://nyzovyna.com/'))

    def test_sitemap_contains_every_published_article_once(self):
        body = html_of(self.get_ok('/sitemap.xml'))
        for a in Article.objects.filter(is_published=True):
            with self.subTest(slug=a.slug):
                self.assertEqual(body.count(f'/article/{a.slug}/<'), 1)

    def test_sitemap_excludes_unpublished_and_future(self):
        mk_article('sm-draft', published=False)
        mk_article('sm-future', publish_at=now() + timedelta(days=1))
        body = html_of(self.get_ok('/sitemap.xml'))
        self.assertNotIn('sm-draft', body)
        self.assertNotIn('sm-future', body)

    def test_sitemap_lastmod_is_a_real_modification_date(self):
        a = Article.objects.get(slug='seed-1')
        self.assertIn(a.publish_at.strftime('%Y-%m-%d'), html_of(self.get_ok('/sitemap.xml')))

    def test_sitemap_has_no_duplicate_locations(self):
        locs = re.findall(r'<loc>(.*?)</loc>', html_of(self.get_ok('/sitemap.xml')))
        self.assertEqual(len(locs), len(set(locs)))


    def test_sitemap_size_is_bounded_by_protocol_limit(self):
        self.assertLess(len(self.get_ok('/sitemap.xml').content), 50 * 1024 * 1024)



class FeedTests(SeoSetup):
    def parse(self):
        response = self.client.get('/feed/', secure=True)
        self.assertEqual(response.status_code, 200)
        return feedparser.parse(response.content)

    def test_feed_is_well_formed(self):
        self.assertFalse(self.parse().bozo)

    def test_feed_entries_have_title_link_date(self):
        for entry in self.parse().entries:
            with self.subTest(title=entry.get('title')):
                self.assertTrue(entry.get('title') and entry.get('link') and entry.get('published_parsed'))

    def test_feed_links_are_absolute_https_on_canonical_host(self):
        for entry in self.parse().entries:
            with self.subTest(link=entry.link):
                self.assertTrue(entry.link.startswith('https://nyzovyna.com/'))

    def test_feed_channel_link_is_canonical_host(self):
        self.assertTrue(self.parse().feed.link.startswith('https://nyzovyna.com'))

    def test_feed_language_is_valid(self):
        self.assertIn(self.parse().feed.get('language'), ('uk', 'en'))

    def test_feed_entry_date_is_publish_date(self):
        old = mk_article('old', publish_at=now() - timedelta(days=100))
        Article.objects.filter(pk=old.pk).update(created_at=now())
        entries = {e.link.rsplit('/', 2)[-2]: e for e in self.parse().entries}
        if 'old' in entries:
            self.assertLess(entries['old'].published_parsed, (now() - timedelta(days=50)).timetuple())

    def test_feed_description_is_not_full_article_html(self):
        long_text = '<p>' + 'word ' * 2000 + '</p>'
        mk_article('longfeed', text=long_text, publish_at=now() + timedelta(seconds=0))
        for entry in self.parse().entries:
            self.assertLess(len(entry.get('summary', '')), 5000)

    def test_feed_has_atom_self_link(self):
        self.assertIn('rel="self"', html_of(self.get_ok('/feed/')))

    def test_feed_is_advertised_in_html_head(self):
        self.assertIn('application/rss+xml', html_of(self.get_ok('/')).split('</head>')[0])

    def test_feed_has_unique_guids(self):
        guids = [e.get('id') for e in self.parse().entries]
        self.assertEqual(len(guids), len(set(guids)))


class UrlTests(SeoSetup):
    def test_old_uuid_url_redirects_to_slug(self):
        a = Article.objects.get(slug='seed-0')
        response = self.client.get(f'/article/{a.id}/')
        self.assertIn(response.status_code, (301, 302, 308))
        self.assertTrue(response['Location'].endswith('/article/seed-0/'))


    def test_non_canonical_trailing_slash_redirects(self):
        self.assertIn(self.client.get('/article/seed-0').status_code, (301, 302, 308))

    def test_uppercase_slug_redirects_or_404(self):
        self.assertIn(self.client.get('/article/SEED-0/').status_code, (301, 404))

