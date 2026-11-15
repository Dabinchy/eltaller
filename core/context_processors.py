"""
Datos disponibles en todos los templates.

- empresa: datos del taller (una sola fila).
- marca: nombre y logo según el área: "El Prepa" en el portal de pilotos, "El Taller" en el resto.
- menu: el menú del área actual (panel o portal), armado según los permisos. Se calcula sólo
  si el template lo usa.
"""
from __future__ import annotations

from django.conf import settings
from django.templatetags.static import static
from django.utils.functional import SimpleLazyObject


def _empresa():
    from .models import Empresa

    try:
        return Empresa.objects.first()
    except Exception:  # base sin migrar o error al renderizar páginas de error
        return None


def _area(request) -> str:
    ruta = getattr(request, "path", "") or "/"
    if ruta.startswith("/portal/"):
        return "portal"
    if ruta.startswith("/panel/"):
        return "panel"
    return "publico"


def empresa(request):
    emp = SimpleLazyObject(_empresa)

    def _marca():
        if _area(request) == "portal":
            return {"nombre": settings.PORTAL_MARCA_NOMBRE, "logo": static(settings.PORTAL_MARCA_LOGO)}
        # Siempre la marca El Taller (el logo de Empresa no la reemplaza).
        return {"nombre": settings.TALLER_MARCA_NOMBRE, "logo": static(settings.TALLER_MARCA_LOGO)}

    return {"empresa": emp, "marca": SimpleLazyObject(_marca)}


def menu(request):
    usuario = getattr(request, "user", None)
    area = _area(request)
    if not usuario or not usuario.is_authenticated or area == "publico":
        return {}

    def _armar():
        from .menu import construir_menu

        return construir_menu(usuario, area)

    return {"menu": SimpleLazyObject(_armar)}
