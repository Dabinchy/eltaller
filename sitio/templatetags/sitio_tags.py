"""Ayudas para las plantillas del sitio público: links de WhatsApp e Instagram."""
from __future__ import annotations

import re
from urllib.parse import quote

from django import template

register = template.Library()


@register.simple_tag
def whatsapp_url(numero: str, texto: str = "") -> str:
    """Link para abrir un chat de WhatsApp (wa.me). El número va con código de país."""
    digitos = re.sub(r"\D", "", numero or "")
    if not digitos:
        return ""
    url = f"https://wa.me/{digitos}"
    return f"{url}?text={quote(texto)}" if texto else url


@register.filter
def instagram_url(usuario: str) -> str:
    return f"https://www.instagram.com/{usuario}/" if usuario else ""
