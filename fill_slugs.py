from django.utils.text import slugify
from app.models import Article, Author, Category

updated_articles = 0
updated_authors = 0
updated_categories = 0

for obj in Article.objects.all():
    if not obj.slug:
        base_slug = slugify(obj.name)
        slug = base_slug
        n = 1
        while Article.objects.filter(slug=slug).exclude(id=obj.id).exists():
            slug = f"{base_slug}-{n}"
            n += 1
        obj.slug = slug
        obj.save()
        updated_articles += 1

for obj in Author.objects.all():
    if not obj.slug:
        base_slug = slugify(obj.name_en or obj.name_ua)
        slug = base_slug
        n = 1
        while Author.objects.filter(slug=slug).exclude(id=obj.id).exists():
            slug = f"{base_slug}-{n}"
            n += 1
        obj.slug = slug
        obj.save()
        updated_authors += 1

for obj in Category.objects.all():
    if not obj.slug:
        base_slug = slugify(obj.name_en or obj.name_ua)
        slug = base_slug
        n = 1
        while Category.objects.filter(slug=slug).exclude(id=obj.id).exists():
            slug = f"{base_slug}-{n}"
            n += 1
        obj.slug = slug
        obj.save()
        updated_categories += 1

print(f"✅ Done. Added slugs for {updated_articles} Articles, {updated_authors} Authors, {updated_categories} Categories.")

