# productos/signals.py
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

# Lectura del catálogo, precios y stock (lo mínimo para operar).
_LECTURA = [
    "productos.view_producto",
    "productos.view_categoria",
    "productos.view_listaprecio",
    "productos.view_precioproducto",
    "productos.view_stocksucursal",
]

PERMISOS_PRODUCTOS_POR_GRUPO = {
    # Todo: catálogo, precios, costos, stock de todas las sucursales.
    GRUPO_GERENTE: _LECTURA + [
        "productos.gestionar_productos",
        "productos.gestionar_precios",
        "productos.ver_costos",
        "productos.add_producto",
        "productos.change_producto",
        "productos.add_categoria",
        "productos.change_categoria",
        "productos.add_listaprecio",
        "productos.change_listaprecio",
        "productos.add_precioproducto",
        "productos.change_precioproducto",
        "productos.add_stocksucursal",
        "productos.change_stocksucursal",
        "productos.view_movimientostock",
    ],
    # Alta/edición de productos y stock de SU sucursal; ve costos. No cambia precios.
    GRUPO_JEFE: _LECTURA + [
        "productos.gestionar_productos",
        "productos.ver_costos",
        "productos.add_producto",
        "productos.change_producto",
        "productos.add_categoria",
        "productos.change_categoria",
        "productos.add_stocksucursal",
        "productos.change_stocksucursal",
        "productos.view_movimientostock",
    ],
    # Sólo ve catálogo, precios y stock (sin costos).
    GRUPO_ADMINISTRACION: list(_LECTURA),
    # Ve productos y precios para cargar repuestos y mano de obra en sus órdenes (sin costos).
    GRUPO_MECANICO: list(_LECTURA),
}


@receiver(post_migrate, dispatch_uid="productos_sincronizar_permisos")
def sincronizar_permisos_productos(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'productos'. Idempotente."""
    if getattr(sender, "name", None) != "productos":
        return

    for nombre_grupo, labels in PERMISOS_PRODUCTOS_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "productos", labels)
