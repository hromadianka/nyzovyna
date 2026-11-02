import logging

from django.core.cache.backends.locmem import LocMemCache
from django.db import OperationalError
from django.http import HttpResponse
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


class DatabaseUnavailableMiddleware:
    """Answer 503 with a plain page instead of a 500 when the database cannot be reached."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, OperationalError):
            return None
        logger.error('database unavailable for %s %s: %s', request.method, request.path, exception)
        response = HttpResponse(render_to_string('503.html'), status=503)
        response['Retry-After'] = '30'
        return response


class ResilientLocMemCache(LocMemCache):
    """A cache outage must degrade to cache misses, never to a 500 on every page."""

    def _guard(self, name, fallback, *args, **kwargs):
        try:
            return getattr(super(), name)(*args, **kwargs)
        except Exception:
            logger.exception('cache %s failed', name)
            return fallback

    def get(self, key, default=None, version=None):
        return self._guard('get', default, key, default, version)

    def set(self, key, value, timeout=300, version=None):
        return self._guard('set', None, key, value, timeout, version)

    def add(self, key, value, timeout=300, version=None):
        return self._guard('add', False, key, value, timeout, version)

    def delete(self, key, version=None):
        return self._guard('delete', False, key, version)

    def incr(self, key, delta=1, version=None):
        try:
            return super().incr(key, delta, version)
        except ValueError:
            raise
        except Exception:
            logger.exception('cache incr failed')
            return 1
