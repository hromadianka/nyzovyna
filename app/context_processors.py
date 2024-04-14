from .models import Category
from django.utils.translation import get_language


def categories(request):
    categories = Category.objects.all() 
    return {'categories': categories}

def language(request):
    return {
        'current_language': get_language(),
    }

