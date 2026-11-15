# taller/signals.py
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

_VEHICULOS_Y_TURNOS = [
    "taller.view_vehiculo",
    "taller.add_vehiculo",
    "taller.change_vehiculo",
    "taller.view_turno",
    "taller.add_turno",
    "taller.change_turno",
]

_TECNICOS = ["taller.view_tecnico", "taller.add_tecnico", "taller.change_tecnico"]

PERMISOS_TALLER_POR_GRUPO = {
    GRUPO_GERENTE: _VEHICULOS_Y_TURNOS + _TECNICOS,
    GRUPO_JEFE: _VEHICULOS_Y_TURNOS + _TECNICOS,
    # Crea turnos y atiende clientes; ve los técnicos para asignar trabajo.
    GRUPO_ADMINISTRACION: _VEHICULOS_Y_TURNOS + ["taller.view_tecnico"],
    # Trabaja desde sus órdenes asignadas (se agregan con las órdenes de trabajo).
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="taller_sincronizar_permisos")
def sincronizar_permisos_taller(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'taller'. Idempotente."""
    if getattr(sender, "name", None) != "taller":
        return

    for nombre_grupo, labels in PERMISOS_TALLER_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "taller", labels)
