"""Seed synthetic data. Usage: PYTHONPATH=docs/prod-readiness/scripts DJANGO_SETTINGS_MODULE=fg_settings NYZ_DB_FILE=... python fg_seed.py"""
import os, sys, django
sys.path.insert(0, os.getcwd())
django.setup()
from django.contrib.auth.models import User
from django.utils.timezone import now
from datetime import timedelta
from app.models import *

User.objects.create_superuser('admin', 'a@example.com', 'adminpass')
Editor.objects.get_or_create(user=User.objects.get(username='admin'))
AboutUsText.objects.create(pk=1, text_ua='<p>Про нас: тестовий текст.</p>', text_en='<p>About us: test text.</p>')
def cat(ua, en, slug, parent=None, order=0):
    return Category.objects.create(name_ua=ua, name_en=en, slug=slug, parent=parent, order=order)
c1 = cat('Культура', 'Culture', 'culture', order=1)
c2 = cat('Кіно', 'Cinema', 'cinema', c1)
c3 = cat('Документальне', 'Documentary', 'documentary', c2)
c4 = cat('Політика', 'Politics', 'politics', order=2)
c5 = cat('Історія', 'History', 'history', order=3)
a1 = Author.objects.create(name_en='John Doe', name_ua='Іван Доу', slug='john-doe', description_en='Writer about things.', description_ua='Автор текстів.')
a2 = Author.objects.create(name_en='Jane Roe', name_ua='Ганна Ро', slug='jane-roe', description_en='Editor.', description_ua='Редакторка.')
cats = [c1, c2, c3, c4, c5]
arts = []
for i in range(12):
    lang = 'ua' if i % 2 == 0 else 'en'
    a = Article.objects.create(
        name=f'Test article {i} {lang}' if lang == 'en' else f'Тестова стаття {i}',
        slug=f'test-article-{i}', text=f'<p>Body of article {i}. ' + 'Lorem ipsum dolor sit amet. ' * 30 + '</p><h2>Sub</h2><p>More text.</p>',
        language=lang, author=a1 if i % 3 else a2, is_published=True, publish_at=now() - timedelta(days=i), views=i * 3)
    a.categories.set([cats[i % 5], cats[(i + 2) % 5]] if i % 4 == 0 else [cats[i % 5]])
    arts.append(a)
# unpublished + scheduled for sitemap/feed checks
Article.objects.create(name='Draft ua', slug='draft-ua', text='<p>d</p>', language='ua', is_published=False)
Article.objects.create(name='Future ua', slug='future-ua', text='<p>f</p>', language='ua', is_published=True, publish_at=now() + timedelta(days=5))
a0 = arts[0]
p = Comment.objects.create(article=a0, author='Alice', text='Parent comment')
r = Comment.objects.create(article=a0, author='Bob', text='Reply 1', parent_comment=p)
Comment.objects.create(article=a0, author='Carol', text='Reply to reply', parent_comment=r)
Comment.objects.create(article=a0, author='Dan', text='Second root')
print('seeded', Article.objects.count(), Category.objects.count(), Comment.objects.count())
