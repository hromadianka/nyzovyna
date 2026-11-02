from django.db import migrations
from django.utils.timezone import now


def publish_pending_scheduled(apps, schema_editor):
    """Scheduled articles used to wait with is_published=False for a job that never ran; visibility now follows
    publish_at, so the pending ones only need the flag switched on."""
    Article = apps.get_model('app', 'Article')
    Article.objects.filter(is_published=False, publish_at__gt=now()).update(is_published=True)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0009_alter_article_slug_alter_author_slug_and_more'),
    ]

    operations = [
        migrations.RunPython(publish_pending_scheduled, migrations.RunPython.noop),
    ]
