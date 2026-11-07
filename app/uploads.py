import os
import uuid

from django.conf import settings
from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
ALLOWED_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP'}


def validate_image(upload):
    """Return an error message for an unacceptable image upload, otherwise None and give it a neutral name."""
    extension = os.path.splitext(upload.name or '')[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return 'Неправильний формат файлу.'
    if upload.size == 0 or upload.size > MAX_IMAGE_BYTES:
        return 'Файл порожній або завеликий (максимум 5 МБ).'
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            image_format, (width, height) = image.format, image.size
            if image_format not in ALLOWED_FORMATS or width * height > MAX_IMAGE_PIXELS:
                return 'Неправильний формат файлу.'
            image.verify()
    except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        return 'Файл не є коректним зображенням.'
    finally:
        upload.seek(0)
    upload.name = f'{uuid.uuid4().hex}{extension}'
    return None


def validate_pdf(upload):
    """Return an error message for an unacceptable PDF upload, otherwise None (the file is rewound).

    Only the header is checked: a full parse would cost a dependency, and the files are served from another
    domain, so a disguised file cannot run in the site's origin.
    """
    if os.path.splitext(upload.name or '')[1].lower() != '.pdf':
        return 'Дозволені лише файли PDF.'
    if upload.size == 0 or upload.size > settings.BOOK_MAX_FILE_BYTES:
        return f'Файл порожній або завеликий (максимум {settings.BOOK_MAX_FILE_BYTES // (1024 * 1024)} МБ).'
    upload.seek(0)
    header = upload.read(5)
    upload.seek(0)
    if header != b'%PDF-':
        return 'Файл не є коректним PDF.'
    return None
