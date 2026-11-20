"""Ayudas de plantilla para /panel/sitio/."""
from django import template

register = template.Library()

_PARTES = {"taller": "El Taller", "prepa": "El Prepa", "campeonatos": "Campeonatos"}


@register.filter
def clave(diccionario, k):
    """{{ dic|clave:nombre }}: valor de un diccionario con una clave variable."""
    try:
        return diccionario.get(k)
    except AttributeError:
        return None


@register.inclusion_tag("panel/sitio/_parte.html")
def parte_chip(clave_parte):
    return {"clave": clave_parte, "nombre": _PARTES.get(clave_parte, clave_parte)}
