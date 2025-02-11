from django.core.management.base import BaseCommand
from django.utils.timezone import now
from app.models import Article

class Command(BaseCommand):
    help = 'Публікує статті, в яких настав час публікації'

    def handle(self, *args, **kwargs):
        articles = Article.objects.filter(is_published=False, publish_at__lte=now())
        count = articles.update(is_published=True)
        self.stdout.write(self.style.SUCCESS(f'Опубліковано {count} статей'))
