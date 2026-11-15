# ventas/signals.py
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

_COBRO = [
    "ventas.crear_venta",
    "ventas.finalizar_venta",
    "ventas.ver_ventas",
    "ventas.view_venta",
    "ventas.view_ventadetalle",
]

PERMISOS_VENTAS_POR_GRUPO = {
    # Todo, incluida la anulación (todas las sucursales).
    GRUPO_GERENTE: _COBRO + ["ventas.anular_venta"],
    # Cobra en su sucursal; no anula.
    GRUPO_JEFE: list(_COBRO),
    # Cobra en su sucursal; no anula ni ve costos (eso lo decide productos.ver_costos).
    GRUPO_ADMINISTRACION: list(_COBRO),
    # Sin acceso a ventas.
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="ventas_sincronizar_permisos")
def sincronizar_permisos_ventas(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'ventas'. Idempotente."""
    if getattr(sender, "name", None) != "ventas":
        return

    for nombre_grupo, labels in PERMISOS_VENTAS_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "ventas", labels)
