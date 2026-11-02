from django.utils.functional import SimpleLazyObject
from django.utils.translation import get_language

from .models import Category


def build_menu_tree():
    """Load every category in one query and attach `menu_children` in memory.

    Returns the root categories; each node (at any depth) has a `menu_children` list.
    """
    by_parent = {}
    for category in Category.objects.all():
        by_parent.setdefault(category.parent_id, []).append(category)
    for siblings in by_parent.values():
        for category in siblings:
            category.menu_children = by_parent.get(category.id, [])
    return by_parent.get(None, [])


def categories(request):
    # Lazy on purpose: when the menu fragment is served from cache nothing is evaluated.
    return {
        'categories': Category.objects.all(),
        'menu_categories': SimpleLazyObject(build_menu_tree),
    }

def language(request):
    return {
        'current_language': get_language(),
    }
