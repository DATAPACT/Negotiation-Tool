# custom_filters.py

from django import template

register = template.Library()

@register.filter(name='date_format')
def date_format(value):
    # Example: Replace 'T' with space and capitalize the string
    return value.replace('T', ' ').split(".")[0]
