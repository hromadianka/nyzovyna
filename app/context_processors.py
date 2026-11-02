from django.utils.functional import SimpleLazyObject
from django.utils.translation import get_language

from .models import MAX_CATEGORY_DEPTH, Category
from .seo import html_lang


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
    roots = by_parent.get(None, [])
    # the menu template recurses; cut anything deeper than the model allows (and any cycle)
    level, seen = roots, set()
    for _ in range(MAX_CATEGORY_DEPTH):
        next_level = []
        for category in level:
            seen.add(category.id)
            next_level.extend(child for child in category.menu_children if child.id not in seen)
        level = next_level
    for category in level:
        category.menu_children = []
    return roots


def categories(request):
    # Lazy on purpose: when the menu fragment is served from cache nothing is evaluated.
    return {
        'categories': Category.objects.all(),
        'menu_categories': SimpleLazyObject(build_menu_tree),
    }

def language(request):
    return {
        'current_language': get_language(),
        'html_lang': html_lang(),
    }
