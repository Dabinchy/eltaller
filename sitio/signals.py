# sitio/signals.py
"""
Permisos del contenido del sitio público por grupo (se sincronizan después de cada migración).

- Gerente y Administración: cargan y editan todo el contenido, y ven y responden las consultas.
- Jefe: ve y responde las consultas (no edita el contenido).
- Mecánico: nada.
"""
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

_MODELOS_CONTENIDO = ("portada", "servicio", "trabajo", "fototrabajo", "testimonio", "publicacion")

_CONTENIDO = [
    f"sitio.{accion}_{modelo}"
    for modelo in _MODELOS_CONTENIDO
    for accion in ("view", "add", "change", "delete")
]
_CONSULTAS_RESPONDER = ["sitio.view_consulta", "sitio.change_consulta"]
_CONSULTAS_TODO = _CONSULTAS_RESPONDER + ["sitio.delete_consulta"]

PERMISOS_SITIO_POR_GRUPO = {
    GRUPO_GERENTE: _CONTENIDO + _CONSULTAS_TODO,
    GRUPO_ADMINISTRACION: _CONTENIDO + _CONSULTAS_TODO,
    GRUPO_JEFE: _CONSULTAS_RESPONDER,
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="sitio_sincronizar_permisos")
def sincronizar_permisos_sitio(sender, **kwargs):
    if getattr(sender, "name", None) != "sitio":
        return
    for nombre_grupo, labels in PERMISOS_SITIO_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "sitio", labels)
