from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Category

ROBOTS_DISALLOW = ('/admin/', '/editor-cabinet', '/login/', '/logout/', '/publish', '/create-category/',
                   '/create_new_author/', '/about-us-edit', '/search/')


@never_cache
@require_GET
def healthz(request):
    try:
        connection.ensure_connection()
        Category.objects.exists()
    except DatabaseError:
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})


@require_GET
def robots_txt(request):
    lines = ['User-agent: *'] + [f'Disallow: {path}' for path in ROBOTS_DISALLOW]
    lines.append(f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}')
    return HttpResponse('\n'.join(lines) + '\n', content_type='text/plain; charset=utf-8')
