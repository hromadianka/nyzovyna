from ckeditor_uploader.views import ImageUploadView
from django.http import JsonResponse

from .uploads import validate_image

_upload = ImageUploadView.as_view()


def ckeditor_upload(request):
    """CKEditor upload endpoint with CSRF protection kept on and the same image checks as the model fields."""
    uploaded = request.FILES.get('upload') if request.method == 'POST' else None
    if uploaded is not None:
        error = validate_image(uploaded)
        if error:
            return JsonResponse({'uploaded': 0, 'error': {'message': error}}, status=400)
    return _upload(request)
