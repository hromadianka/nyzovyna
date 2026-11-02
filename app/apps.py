from django.apps import AppConfig


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .menu_cache import invalidate_menu_cache
        from .models import Category

        post_save.connect(lambda **kw: invalidate_menu_cache(), sender=Category,
                          weak=False, dispatch_uid='menu_cache_save')
        post_delete.connect(lambda **kw: invalidate_menu_cache(), sender=Category,
                            weak=False, dispatch_uid='menu_cache_delete')
