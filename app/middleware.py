from django.core.cache import cache
from django.http import HttpResponse

from .ratelimit import client_id

LOGIN_PATHS = ('/login/', '/admin/login/')
MAX_FAILED_LOGINS = 10
LOCKOUT_SECONDS = 15 * 60


class LoginThrottleMiddleware:
    """Blocks a client after repeated failed logins on the editor and admin login forms."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'POST' or request.path not in LOGIN_PATHS:
            return self.get_response(request)
        key = f'loginfail:{client_id(request)}'
        if cache.get(key, 0) >= MAX_FAILED_LOGINS:
            return HttpResponse('Too many failed login attempts. Try again later.', status=429)
        response = self.get_response(request)
        if response.status_code != 302:
            cache.add(key, 0, LOCKOUT_SECONDS)
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOCKOUT_SECONDS)
        return response


class PermissionsPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
        return response
