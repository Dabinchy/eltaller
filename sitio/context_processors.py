"""
Parte del sitio público (El Taller, El Prepa o Campeonatos) para el encabezado, el pie y la
pantalla de ingreso. Fuera del sitio público (panel, portal, admin) no agrega nada.
"""
from __future__ import annotations

from django.utils.functional import SimpleLazyObject

from . import partes

_AREAS_PRIVADAS = ("/panel/", "/portal/", "/admin/", "/archivos/")


def sitio(request):
    ruta = getattr(request, "path", "") or "/"
    if ruta.startswith(_AREAS_PRIVADAS):
        return {}

    cache: dict = {}

    def _datos() -> dict:
        if not cache:
            cache.update(partes.contexto(request, partes.parte_de_request(request)))
        return cache

    return {
        "parte": SimpleLazyObject(lambda: _datos()["parte"]),
        "partes": SimpleLazyObject(lambda: _datos()["partes"]),
    }
