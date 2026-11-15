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

# Gestión completa de órdenes (el alcance por sucursal lo aplica taller/permisos.py).
_ORDENES = [
    "taller.view_ordentrabajo",
    "taller.add_ordentrabajo",
    "taller.change_ordentrabajo",
    "taller.view_ordenitem",
    "taller.add_ordenitem",
    "taller.change_ordenitem",
    "taller.delete_ordenitem",
    "taller.view_ordenestadolog",
    "taller.aprobar_items",
    "taller.cambiar_estado_orden",
    "taller.entregar_orden",
    "taller.cancelar_orden",
]

PERMISOS_TALLER_POR_GRUPO = {
    GRUPO_GERENTE: _VEHICULOS_Y_TURNOS + _TECNICOS + _ORDENES,
    GRUPO_JEFE: _VEHICULOS_Y_TURNOS + _TECNICOS + _ORDENES,
    # Turnos, órdenes y presupuestos de su sucursal; aprueba ítems y entrega; ve técnicos.
    GRUPO_ADMINISTRACION: _VEHICULOS_Y_TURNOS + ["taller.view_tecnico"] + _ORDENES,
    # Sólo sus órdenes asignadas: escribe el diagnóstico, carga ítems y empieza/termina el trabajo.
    GRUPO_MECANICO: [
        "taller.view_ordentrabajo",
        "taller.change_ordentrabajo",
        "taller.view_ordenitem",
        "taller.add_ordenitem",
        "taller.change_ordenitem",
        "taller.view_ordenestadolog",
        "taller.trabajar_orden",
    ],
}


@receiver(post_migrate, dispatch_uid="taller_sincronizar_permisos")
def sincronizar_permisos_taller(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'taller'. Idempotente."""
    if getattr(sender, "name", None) != "taller":
        return

    for nombre_grupo, labels in PERMISOS_TALLER_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "taller", labels)
