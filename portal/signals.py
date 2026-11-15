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

# Ver los autos del portal y vincularlos con la ficha del taller.
_AUTOS = ["portal.view_auto", "portal.change_auto", "portal.view_pilotoauto", "portal.view_ordencomentario"]

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
        "portal.view_palmares",
        "portal.view_archivo",
        "portal.view_registromoderacion",
    ] + _ACCESOS_CLIENTE + _AUTOS,
    GRUPO_JEFE: _ACCESOS_CLIENTE + _AUTOS,
    GRUPO_ADMINISTRACION: _ACCESOS_CLIENTE + _AUTOS,
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="portal_sincronizar_permisos")
def sincronizar_permisos_portal(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'portal'. Idempotente."""
    if getattr(sender, "name", None) != "portal":
        return

    for nombre_grupo, labels in PERMISOS_PORTAL_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "portal", labels)


# ============================================================
# Al borrar un archivo, borrar también el archivo físico y su miniatura
# ============================================================

from django.db import transaction  # noqa: E402
from django.db.models.signals import post_delete  # noqa: E402

from .models_contenido import Archivo  # noqa: E402


@receiver(post_delete, sender=Archivo, dispatch_uid="portal_borrar_archivo_fisico")
def borrar_archivo_fisico(sender, instance: Archivo, **kwargs):
    archivos = [f for f in (instance.archivo, instance.miniatura) if f]
    # on_commit: si la transacción se deshace, el archivo no se pierde.
    transaction.on_commit(lambda: [f.storage.delete(f.name) for f in archivos])
