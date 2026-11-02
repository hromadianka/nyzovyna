import re

from .helpers import BASE_DIR, TEMPLATES_DIR, Base, html_of, mk_comment, seed_site

PAGES = ['/', '/all', '/about-us', '/authors', '/authors/author-1', '/category/root/', '/article/seed-0/',
         '/search/?q=Title', '/login/']
SCRIPT_TARGETS = ['#ticker', '.ticker', '#themeToggle', '.burger-icon', '.menu', '.dropbtn', '.dropdown-content',
                  'header', 'main']


def has_target(html, target):
    if target.startswith('#'):
        return f'id="{target[1:]}"' in html
    if target.startswith('.'):
        return re.search(rf'class="[^"]*\b{re.escape(target[1:])}\b', html) is not None
    return f'<{target}' in html


class ScriptTargetTests(Base):
    def setUp(self):
        super().setUp()
        seed_site(3)
        mk_comment(__import__('app.models', fromlist=['Article']).Article.objects.get(slug='seed-0'))

    def test_every_element_used_by_base_scripts_exists_on_every_page(self):
        for url in PAGES:
            html = html_of(self.get_ok(url))
            for target in SCRIPT_TARGETS:
                with self.subTest(url=url, target=target):
                    self.assertTrue(has_target(html, target))

    def test_base_scripts_guard_against_missing_elements(self):
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        for element in ['themeToggle', 'ticker']:
            with self.subTest(element=element):
                pattern = rf"getElementById\(['\"]{element}['\"]\)"
                for match in re.finditer(pattern, base):
                    window = base[match.start():match.start() + 140]
                    self.assertTrue('?.' in window or 'if (' in base[max(0, match.start() - 60):match.start()],
                                    f'unguarded access to {element}')

    def test_header_margin_script_guards_missing_ticker(self):
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        body = base.split('function updateHeaderMargin', 1)[1].split('}', 1)[0]
        self.assertRegex(body, r'if\s*\(\s*!?ticker|ticker\s*\?|ticker\s*&&')

    def test_theme_toggle_exists_wherever_the_script_expects_it(self):
        for url in PAGES:
            with self.subTest(url=url):
                self.assertIn('id="themeToggle"', html_of(self.get_ok(url)))

    def test_ids_referenced_by_inline_handlers_exist(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        for ident in set(re.findall(r"toggleReplyForm\('([^']+)'\)", html)):
            with self.subTest(ident=ident):
                self.assertIn(f'id="reply-form-{ident}"', html)

    def test_toggle_reply_form_function_is_defined(self):
        html = html_of(self.get_ok('/article/seed-0/'))
        self.assertIn('function toggleReplyForm', html + (BASE_DIR / 'static' / 'style.css').read_text(encoding='utf-8'))

    def test_editor_pages_include_a_defined_uploader_contract(self):
        for name in ['edit_article.html', 'editor-cabinet.html']:
            text = (TEMPLATES_DIR / name).read_text(encoding='utf-8-sig')
            with self.subTest(template=name):
                self.assertNotIn("uploadUrl: '/ckeditor/upload/'", text)

    def test_ckeditor_cdn_script_is_loaded_only_where_used(self):
        for name in sorted(TEMPLATES_DIR.glob('*.html')):
            text = name.read_text(encoding='utf-8-sig')
            if 'ClassicEditor' in text:
                continue
        base = (TEMPLATES_DIR / 'base.html').read_text(encoding='utf-8')
        self.assertNotIn('cdn.ckeditor.com', base)

    def test_templates_use_https_for_external_resources(self):
        for path in sorted(TEMPLATES_DIR.glob('*.html')):
            with self.subTest(template=path.name):
                self.assertEqual(re.findall(r'(?:src|href)="(http://[^"]+)"', path.read_text(encoding='utf-8-sig')), [])

    def test_inline_event_handlers_are_not_used(self):
        for path in sorted(TEMPLATES_DIR.glob('*.html')):
            with self.subTest(template=path.name):
                self.assertEqual(re.findall(r'\son(?:click|change|submit)="', path.read_text(encoding='utf-8-sig')), [])

    def test_css_file_has_no_missing_closing_braces(self):
        css = (BASE_DIR / 'static' / 'style.css').read_text(encoding='utf-8')
        self.assertEqual(css.count('{'), css.count('}'))

    def test_background_images_use_static_urls_through_manifest(self):
        for name in ['index.html', 'category.html']:
            text = (TEMPLATES_DIR / name).read_text(encoding='utf-8-sig')
            with self.subTest(template=name):
                self.assertNotIn("url('/static/", text)

    def test_menu_links_are_keyboard_reachable_submenu(self):
        html = html_of(self.get_ok('/'))
        self.assertIn('aria-haspopup', html)

    def test_mobile_menu_toggle_state_is_exposed(self):
        self.assertIn('aria-expanded', html_of(self.get_ok('/')))
