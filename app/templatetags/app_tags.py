from django import template
from django.utils.safestring import mark_safe

from app.sanitize import sanitize_html

register = template.Library()

def comment_depth(comment):
    depth = 0
    while comment.parent_comment:
        depth += 1
        comment = comment.parent_comment
    return depth

register.filter('comment_depth', comment_depth)

def multiply(value, arg):
    return value * arg

register.filter('multiply', multiply)


@register.filter(name='sanitize_html')
def sanitize_html_filter(value):
    return mark_safe(sanitize_html(value))
