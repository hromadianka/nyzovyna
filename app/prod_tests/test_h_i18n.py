import gettext
import re

from django.conf import settings
from django.conf.locale import LANG_INFO
from django.utils import translation
from django.utils.translation import get_language_info

from .helpers import BASE_DIR, TEMPLATES_DIR, Base, html_of, mk_article, mk_category, mk_comment, seed_site, visible_text

PUBLIC_TEMPLATES = ['base.html', 'index.html', 'category.html', 'article.html', 'author_detail.html', 'authors.html',
                    'about-us.html', 'search.html', 'login.html', 'comment.html', 'recursive_menu.html']
CYR = re.compile(r'[А-Яа-яЁёІіЇїЄєҐґ]')
LOCALE_DIR = BASE_DIR / 'locale'


def template_text(name):
    return (TEMPLATES_DIR / name).read_text(encoding='utf-8-sig')


def strip_i18n(text):
    text = re.sub(r"{%\s*trans\s+(\"[^\"]*\"|'[^']*')[^%]*%}", '', text)
    text = re.sub(r'{%\s*blocktrans.*?{%\s*endblocktrans\s*%}', '', text, flags=re.S)
    text = re.sub(r'{#.*?#}', '', text, flags=re.S)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'<(script|style)\b.*?</\1>', '', text, flags=re.S | re.I)
    return re.sub(r'{{.*?}}|{%.*?%}', '', text, flags=re.S)


def trans_msgids(name):
    return [m[1:-1] for m in re.findall(r"{%\s*trans\s+(\"[^\"]*\"|'[^']*')", template_text(name))]


def po_msgids(lang):
    text = (LOCALE_DIR / lang / 'LC_MESSAGES' / 'django.po').read_text(encoding='utf-8')
    return re.findall(r'^msgid "(.+)"$', text, flags=re.M)


def mo_catalog(lang):
    with open(LOCALE_DIR / lang / 'LC_MESSAGES' / 'django.mo', 'rb') as fh:
        return gettext.GNUTranslations(fh)._catalog


class LanguageConfigTests(Base):
    def test_language_code_is_a_known_django_language(self):
        self.assertIn(settings.LANGUAGE_CODE, LANG_INFO)

    def test_every_configured_language_is_known_to_django(self):
        for code, _ in settings.LANGUAGES:
            with self.subTest(code=code):
                get_language_info(code)

    def test_content_language_header_is_valid_bcp47(self):
        self.assertIn(self.client.get('/')['Content-Language'], ('uk', 'en'))

    def test_html_lang_attribute_present_and_valid(self):
        self.assertRegex(html_of(self.client.get('/')), r'<html[^>]+lang="(uk|en)"')

    def test_html_lang_follows_selected_language(self):
        self.client.cookies['django_language'] = 'en'
        self.assertRegex(html_of(self.client.get('/')), r'<html[^>]+lang="en"')

    def test_locale_directories_exist_for_each_language(self):
        for code, _ in settings.LANGUAGES:
            with self.subTest(code=code):
                self.assertTrue((LOCALE_DIR / code / 'LC_MESSAGES' / 'django.mo').exists())

    def test_compiled_catalog_is_not_older_than_source(self):
        for code, _ in settings.LANGUAGES:
            base = LOCALE_DIR / code / 'LC_MESSAGES'
            with self.subTest(code=code):
                self.assertGreaterEqual((base / 'django.mo').stat().st_mtime + 1, (base / 'django.po').stat().st_mtime)

    def test_django_stock_translation_exists_for_ukrainian(self):
        with translation.override('uk'):
            self.assertNotEqual(translation.gettext('Page not found'), 'Page not found')

    def test_accept_language_header_is_ignored_by_design(self):
        mk_article('x')
        self.assertIn('Останні публікації', html_of(self.client.get('/', HTTP_ACCEPT_LANGUAGE='en')))


class TranslationCoverageTests(Base):
    def test_every_trans_string_exists_in_english_po(self):
        known = set(po_msgids('en'))
        for name in PUBLIC_TEMPLATES:
            for msgid in trans_msgids(name):
                with self.subTest(template=name, msgid=msgid):
                    self.assertIn(msgid, known)

    def test_every_trans_string_exists_in_compiled_catalog(self):
        catalog = mo_catalog('en')
        for name in PUBLIC_TEMPLATES:
            for msgid in set(trans_msgids(name)):
                with self.subTest(template=name, msgid=msgid):
                    self.assertIn(msgid, catalog)

    def test_english_translations_differ_from_ukrainian_source(self):
        catalog = mo_catalog('en')
        for name in PUBLIC_TEMPLATES:
            for msgid in set(trans_msgids(name)):
                if msgid in catalog and CYR.search(msgid):
                    with self.subTest(template=name, msgid=msgid):
                        self.assertNotEqual(catalog[msgid], msgid)

    def test_no_empty_translations_in_catalogs(self):
        for code, _ in settings.LANGUAGES:
            for msgid, msgstr in mo_catalog(code).items():
                if msgid:
                    with self.subTest(lang=code, msgid=msgid):
                        self.assertTrue(msgstr.strip())

    def test_po_files_have_no_fuzzy_entries_beyond_header(self):
        for code, _ in settings.LANGUAGES:
            body = (LOCALE_DIR / code / 'LC_MESSAGES' / 'django.po').read_text(encoding='utf-8').split('\n\n', 1)[1]
            with self.subTest(lang=code):
                self.assertNotIn('#, fuzzy', body)

    def test_po_header_is_filled_in(self):
        for code, _ in settings.LANGUAGES:
            text = (LOCALE_DIR / code / 'LC_MESSAGES' / 'django.po').read_text(encoding='utf-8')
            with self.subTest(lang=code):
                self.assertNotIn('FULL NAME', text)

    def test_english_pages_have_no_ukrainian_ui_strings(self):
        seed_site(2)
        self.client.cookies['django_language'] = 'en'
        for url in ['/', '/all', '/authors', '/about-us', '/search/?q=x', '/article/seed-0/', '/category/root/',
                    '/login/']:
            text = visible_text(html_of(self.get_ok(url)))
            with self.subTest(url=url):
                self.assertNotRegex(text, CYR)

    def test_english_ui_on_404_page(self):
        self.client.cookies['django_language'] = 'en'
        self.assertNotRegex(visible_text(html_of(self.client.get('/nope/'))), CYR)

    def test_hardcoded_cyrillic_literals_in_templates_are_wrapped(self):
        for name in PUBLIC_TEMPLATES:
            leftovers = [line.strip() for line in strip_i18n(template_text(name)).splitlines() if CYR.search(line)]
            with self.subTest(template=name):
                self.assertEqual(leftovers, [])

    def test_hardcoded_cyrillic_in_html_attributes_is_wrapped(self):
        for name in PUBLIC_TEMPLATES:
            text = re.sub(r"{%\s*trans.*?%}", '', template_text(name))
            attrs = re.findall(r'(?:placeholder|alt|title|aria-label)="([^"{]*[А-Яа-яІіЇїЄє][^"]*)"', text)
            with self.subTest(template=name):
                self.assertEqual(attrs, [])

    def test_view_messages_are_translatable(self):
        source = (BASE_DIR / 'app' / 'views.py').read_text(encoding='utf-8-sig')
        literals = []
        for line in source.splitlines():
            code = line.split('#', 1)[0]
            if CYR.search(code) and '_(' not in code and 'gettext' not in code:
                literals.append(line.strip())
        self.assertEqual(literals, [])

    def test_comment_form_placeholders_translate(self):
        mk_article('c1')
        self.client.cookies['django_language'] = 'en'
        self.assertNotIn('Введіть', html_of(self.get_ok('/article/c1/')))

    def test_reply_label_translates(self):
        mk_comment(mk_article('c2'))
        self.client.cookies['django_language'] = 'en'
        self.assertNotIn('Відповісти', html_of(self.get_ok('/article/c2/')))

    def test_login_errors_translate(self):
        self.client.cookies['django_language'] = 'en'
        response = self.client.post('/login/', {'login': 'x', 'password': 'y'})
        self.assertNotRegex(visible_text(html_of(response)), CYR)


class LanguageSwitchingTests(Base):
    def switch(self, language, next_url='/'):
        return self.client.post('/set-language/', {'language': language, 'next': next_url})

    def test_switch_sets_cookie(self):
        self.assertEqual(self.switch('en').cookies['django_language'].value, 'en')

    def test_switch_redirects_back_to_same_page(self):
        seed_site(1)
        self.assertEqual(self.switch('en', '/category/root/')['Location'], '/category/root/')

    def test_switch_keeps_query_string(self):
        self.assertEqual(self.switch('en', '/search/?q=abc')['Location'], '/search/?q=abc')

    def test_switch_from_article_stays_reachable(self):
        mk_article('sw', language='ua')
        self.switch('en', '/article/sw/')
        self.assertEqual(self.client.get('/article/sw/').status_code, 200)

    def test_switch_back_and_forth(self):
        mk_article('ua1', language='ua')
        mk_article('en1', language='en')
        self.switch('en')
        self.assertIn('/article/en1/', html_of(self.get_ok('/')))
        self.switch('ua')
        self.assertIn('/article/ua1/', html_of(self.get_ok('/')))

    def test_language_form_next_value_is_current_path_with_query(self):
        self.assertIn('value="/search/?q=abc"', html_of(self.client.get('/search/?q=abc')))

    def test_selected_language_shown_in_switcher(self):
        self.switch('en')
        self.assertRegex(html_of(self.get_ok('/')), r'dropbtn">\s*ENG')

    def test_menu_not_shared_between_languages(self):
        mk_category('politics', name_ua='Політика', name_en='Politics')
        self.assertIn('Політика', html_of(self.get_ok('/')))
        self.switch('en')
        html = html_of(self.get_ok('/'))
        self.assertIn('Politics', html)
        self.assertNotIn('Політика', html)

    def test_footer_not_shared_between_languages(self):
        mk_category('politics', name_ua='Політика', name_en='Politics')
        self.get_ok('/')
        self.switch('en')
        self.assertIn('Politics', html_of(self.get_ok('/')).split('<footer>')[1])

    def test_menu_rename_visible_in_both_languages(self):
        c = mk_category('r', name_ua='Стара', name_en='Old')
        self.get_ok('/')
        self.switch('en')
        self.get_ok('/')
        c.name_ua, c.name_en = 'Нова', 'New'
        c.save()
        self.assertIn('New', html_of(self.get_ok('/')))
        self.switch('ua')
        self.assertIn('Нова', html_of(self.get_ok('/')))

    def test_empty_second_language_shows_hint(self):
        mk_article('only-ua', language='ua')
        self.switch('en')
        text = visible_text(html_of(self.get_ok('/'))).lower()
        self.assertTrue('no articles' in text or 'not available' in text or 'немає' in text)

    def test_language_cookie_persists_across_pages(self):
        self.switch('en')
        for url in ['/', '/authors', '/about-us']:
            with self.subTest(url=url):
                seed_site(0) if url == '/about-us' else None
                self.assertRegex(html_of(self.client.get(url)), r'dropbtn">\s*ENG')

    def test_article_page_offers_link_to_translation(self):
        mk_article('uk-version', language='ua')
        mk_article('en-version', language='en')
        self.assertIn('/article/en-version/', html_of(self.get_ok('/article/uk-version/')))

    def test_switching_language_keeps_user_logged_in(self):
        self.login()
        self.switch('en')
        self.assertNotEqual(self.client.get('/publish').status_code, 302)


class EncodingTests(Base):
    def test_python_files_have_no_bom(self):
        for path in sorted(BASE_DIR.glob('app/**/*.py')) + sorted(BASE_DIR.glob('anarchia/*.py')):
            if '__pycache__' in path.parts:
                continue
            with self.subTest(file=str(path.relative_to(BASE_DIR))):
                self.assertFalse(path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_templates_have_no_bom(self):
        for path in sorted(TEMPLATES_DIR.glob('*.html')):
            with self.subTest(file=path.name):
                self.assertFalse(path.read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_files_with_bom_still_import_and_render(self):
        from anarchia import urls
        self.assertTrue(urls.urlpatterns)
        seed_site(1)
        self.assertNotIn('﻿', html_of(self.get_ok('/authors')))

    def test_responses_are_utf8(self):
        seed_site(1)
        for url in ['/', '/authors', '/feed/']:
            with self.subTest(url=url):
                self.assertIn('utf-8', self.get_ok(url)['Content-Type'].lower())

    def test_template_files_are_valid_utf8(self):
        for path in sorted(TEMPLATES_DIR.glob('*.html')):
            with self.subTest(file=path.name):
                path.read_bytes().decode('utf-8')

    def test_html_starts_with_doctype_and_declares_charset(self):
        html = html_of(self.get_ok('/'))
        self.assertTrue(html.lstrip().lower().startswith('<!doctype html>'))
        self.assertIn('charset="utf-8"', html.lower())


    def test_long_words_do_not_overflow_layout_css(self):
        css = (BASE_DIR / 'static' / 'style.css').read_text(encoding='utf-8')
        self.assertTrue('overflow-wrap' in css or 'word-break' in css or 'hyphens' in css)

    def test_mixed_scripts_in_title_survive_roundtrip(self):
        for i, title in enumerate(['Ґанок', 'Привіт Hello 你好', 'عربى', 'Ünïcödé', '🙂 smile']):
            with self.subTest(title=title):
                mk_article(f'u-{i}', name=title)
                self.assertIn(title, html_of(self.get_ok('/all')))

    def test_date_format_follows_language(self):
        mk_comment(mk_article('dt'))
        self.client.cookies['django_language'] = 'en'
        self.assertNotRegex(html_of(self.get_ok('/article/dt/')), r'\d{2}\.\d{2}\.\d{4}')
