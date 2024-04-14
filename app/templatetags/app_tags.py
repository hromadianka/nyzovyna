from django import template

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
