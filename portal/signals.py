# portal/signals.py
from __future__ import annotations

from django.db.models.signals import post_migrate
from django.dispatch import receiver

from core.roles import (
    GRUPO_ADMINISTRACION,
    GRUPO_GERENTE,
    GRUPO_JEFE,
    GRUPO_MECANICO,
    sincronizar_permisos_grupo,
)

# Los moderadores de cada asociación NO usan grupos: su permiso sale de la membresía (portal/permisos.py).
# Accesos de clientes al portal: los identifica y aprueba el personal que atiende clientes.
_ACCESOS_CLIENTE = [
    "portal.gestionar_accesos_cliente",
    "portal.view_accesocliente",
    "portal.add_accesocliente",
    "portal.change_accesocliente",
]

PERMISOS_PORTAL_POR_GRUPO = {
    # Crea asociaciones, nombra moderadores y puede moderar todo.
    GRUPO_GERENTE: [
        "portal.view_asociacion",
        "portal.add_asociacion",
        "portal.change_asociacion",
        "portal.view_membresia",
        "portal.add_membresia",
        "portal.change_membresia",
        "portal.view_perfilpiloto",
        "portal.view_registromoderacion",
    ] + _ACCESOS_CLIENTE,
    GRUPO_JEFE: list(_ACCESOS_CLIENTE),
    GRUPO_ADMINISTRACION: list(_ACCESOS_CLIENTE),
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="portal_sincronizar_permisos")
def sincronizar_permisos_portal(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'portal'. Idempotente."""
    if getattr(sender, "name", None) != "portal":
        return

    for nombre_grupo, labels in PERMISOS_PORTAL_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "portal", labels)
