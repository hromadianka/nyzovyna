import logging

from django.apps import AppConfig
from django.db import transaction

logger = logging.getLogger(__name__)


def remove_stored_file(sender, instance, **kwargs):
    """Django never deletes a file when its row goes away; do it once the delete is committed."""
    storage, name = instance.file.storage, instance.file.name
    if not name:
        return

    def delete():
        try:
            storage.delete(name)
        except Exception:
            logger.exception('could not delete stored file %s', name)

    transaction.on_commit(delete)


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .menu_cache import invalidate_menu_cache
        from .models import BookFile, Category

        post_save.connect(lambda **kw: invalidate_menu_cache(), sender=Category,
                          weak=False, dispatch_uid='menu_cache_save')
        post_delete.connect(lambda **kw: invalidate_menu_cache(), sender=Category,
                            weak=False, dispatch_uid='menu_cache_delete')

        post_delete.connect(remove_stored_file, sender=BookFile, weak=False, dispatch_uid='book_file_cleanup')
