from django.conf import settings
from django.db import migrations


def set_site_domain(apps, schema_editor):
    """Sitemap and feed URLs are built from the Site row, which Django creates as example.com."""
    Site = apps.get_model('sites', 'Site')
    Site.objects.update_or_create(pk=settings.SITE_ID, defaults={'domain': 'nyzovyna.com', 'name': 'Низовина'})


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0013_article_slug_history'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(set_site_domain, migrations.RunPython.noop),
    ]
