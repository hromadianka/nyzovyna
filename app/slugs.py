from django.utils.text import slugify

_CYRILLIC = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ie', 'ж': 'zh', 'з': 'z',
    'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
    'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ь': '', 'ю': 'iu', 'я': 'ia', 'ё': 'e', 'ы': 'y', 'э': 'e', 'ъ': '',
}


def make_slug(text, fallback):
    """slugify() drops every non-Latin letter, which left Ukrainian names with an empty slug."""
    transliterated = ''.join(_CYRILLIC.get(ch, ch) for ch in (text or '').lower())
    return slugify(transliterated) or fallback


def unique_slug(model, base, max_length, pk=None):
    """First free slug for `base`, cut so that the numeric suffix still fits into max_length."""
    base = base[:max_length].rstrip('-') or base[:max_length]
    slug, n = base, 1
    while model.objects.filter(slug=slug).exclude(pk=pk).exists():
        suffix = f'-{n}'
        slug = f'{base[:max_length - len(suffix)].rstrip("-")}{suffix}'
        n += 1
    return slug
