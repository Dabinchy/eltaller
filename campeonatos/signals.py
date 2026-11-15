# campeonatos/signals.py
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

# Los campeonatos los manejan los moderadores de cada asociación desde el portal (no usan grupos).
# El gerente sólo los consulta desde el admin (y puede moderar por portal/permisos.py).
_CONSULTA = [
    f"campeonatos.view_{m}"
    for m in ("campeonato", "puntajeposicion", "categoria", "fecha", "carrera", "inscripcion", "resultado")
]

PERMISOS_CAMPEONATOS_POR_GRUPO = {
    GRUPO_GERENTE: _CONSULTA,
    GRUPO_JEFE: [],
    GRUPO_ADMINISTRACION: [],
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="campeonatos_sincronizar_permisos")
def sincronizar_permisos_campeonatos(sender, **kwargs):
    if getattr(sender, "name", None) != "campeonatos":
        return
    for nombre_grupo, labels in PERMISOS_CAMPEONATOS_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "campeonatos", labels)
