from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache

from .models import Editor


def is_editor(user):
    return user.is_authenticated and (user.is_superuser or Editor.objects.filter(user=user).exists())


def editor_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_editor(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return never_cache(wrapper)
