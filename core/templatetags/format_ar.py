"""Formato argentino para montos: {{ total|money_ar }} → $ 1.234,56  ({{ total|money_ar:0 }} sin decimales)."""
from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def money_ar(value, decimals=2):
    try:
        dec = int(decimals)
    except (TypeError, ValueError):
        dec = 2
    try:
        formatted = number_format(value, decimal_pos=dec, use_l10n=True, force_grouping=True)
    except (TypeError, ValueError):
        formatted = number_format(0, decimal_pos=dec, use_l10n=True, force_grouping=True)
    return f"$ {formatted}"


@register.filter(name="format_ar")
def format_ar(value, decimals=2):
    """Alias de money_ar (compatibilidad con templates del POS)."""
    return money_ar(value, decimals)
