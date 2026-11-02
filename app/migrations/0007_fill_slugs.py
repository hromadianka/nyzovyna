from django.db import migrations

from app.slugs import make_slug, unique_slug

SOURCES = (
    ('Article', lambda obj: obj.name, 'article', 200),
    ('Author', lambda obj: obj.name_en or obj.name_ua, 'author', 100),
    ('Category', lambda obj: obj.name_ua or obj.name_en, 'category', 100),
)


def fill_slugs(apps, schema_editor):
    for model_name, source, fallback, max_length in SOURCES:
        model = apps.get_model('app', model_name)
        for obj in model.objects.filter(slug__isnull=True) | model.objects.filter(slug=''):
            obj.slug = unique_slug(model, make_slug(source(obj), fallback), max_length, pk=obj.pk)
            obj.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0006_article_slug_author_slug_category_slug_and_more'),
    ]

    operations = [
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
    ]
