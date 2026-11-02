from django.core.cache import cache


def client_id(request):
    # Heroku's router appends the connecting address, so the last entry is the one clients cannot forge.
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def hit(scope, request, limit, window):
    """Count one event for this client; True once more than `limit` happened inside `window` seconds."""
    key = f'rl:{scope}:{client_id(request)}'
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count > limit
