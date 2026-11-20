"""
Parte del sitio público (El Taller, El Prepa o Campeonatos) para el encabezado, el pie y la
pantalla de ingreso. Fuera del sitio público (panel, portal, admin) no agrega nada.

personal_sitio: True si quien navega es personal que puede editar el contenido (ve la barra
"Editar esta página" y los lápices en las tarjetas).
"""
from __future__ import annotations

from django.utils.functional import SimpleLazyObject

from . import partes

_AREAS_PRIVADAS = ("/panel/", "/portal/", "/admin/", "/archivos/")
_PERMISOS_EDICION = tuple(
    f"sitio.change_{m}" for m in ("publicacion", "trabajo", "servicio", "testimonio", "portada")
)


def puede_editar_sitio(user) -> bool:
    if not getattr(user, "is_authenticated", False) or getattr(user, "es_portal", False):
        return False
    return user.is_superuser or any(user.has_perm(p) for p in _PERMISOS_EDICION)


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
        "personal_sitio": puede_editar_sitio(getattr(request, "user", None)),
    }
