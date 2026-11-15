# compras/signals.py
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

# Proveedores + cargar y confirmar compras (el alcance por sucursal lo aplican admin y vistas).
_REGISTRAR = [
    "compras.gestionar_proveedores",
    "compras.registrar_compras",
    "compras.view_proveedor",
    "compras.add_proveedor",
    "compras.change_proveedor",
    "compras.view_compra",
    "compras.add_compra",
    "compras.change_compra",
    "compras.view_compradetalle",
    "compras.add_compradetalle",
    "compras.change_compradetalle",
    "compras.delete_compradetalle",  # quitar renglones mientras la compra está en BORRADOR
]

PERMISOS_COMPRAS_POR_GRUPO = {
    GRUPO_GERENTE: _REGISTRAR + ["compras.anular_compras"],
    GRUPO_JEFE: list(_REGISTRAR),
    # Las compras muestran costos: administración y mecánico no acceden.
    GRUPO_ADMINISTRACION: [],
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="compras_sincronizar_permisos")
def sincronizar_permisos_compras(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'compras'. Idempotente."""
    if getattr(sender, "name", None) != "compras":
        return

    for nombre_grupo, labels in PERMISOS_COMPRAS_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "compras", labels)
