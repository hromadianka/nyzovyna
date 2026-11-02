import os
import uuid

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
