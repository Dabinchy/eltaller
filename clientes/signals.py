# clientes/signals.py
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from core.roles import (
    GRUPO_ADMINISTRACION,
    GRUPO_GERENTE,
    GRUPO_JEFE,
    GRUPO_MECANICO,
    sincronizar_permisos_grupo,
)

from .models import Cliente, CuentaCorriente


@receiver(post_save, sender=Cliente, dispatch_uid="clientes_crear_cc_para_cliente")
def crear_cc_para_cliente(sender, instance: Cliente, created: bool, **kwargs):
    """
    Crea la CuentaCorriente al dar de alta el Cliente.
    on_commit: si el alta termina en rollback, no queda una cuenta huérfana.
    """
    if not created:
        return
    transaction.on_commit(lambda: CuentaCorriente.objects.get_or_create(cliente=instance))


# ============================================================
# Permisos de CLIENTES por grupo
# ============================================================

_ATENCION_Y_COBRO = [
    "clientes.ver_clientes",
    "clientes.gestionar_clientes",
    "clientes.movimientos_cc",
    "clientes.view_cliente",
    "clientes.add_cliente",
    "clientes.change_cliente",
    "clientes.view_cuentacorriente",
    "clientes.view_movimientocuentacorriente",
]

PERMISOS_CLIENTES_POR_GRUPO = {
    GRUPO_GERENTE: list(_ATENCION_Y_COBRO),
    GRUPO_JEFE: list(_ATENCION_Y_COBRO),
    GRUPO_ADMINISTRACION: list(_ATENCION_Y_COBRO),
    # Sin acceso a clientes: ve lo necesario (nombre, vehículo) dentro de sus órdenes.
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="clientes_sincronizar_permisos")
def sincronizar_permisos_clientes(sender, **kwargs):
    """Deja en cada grupo exactamente estos permisos de 'clientes'. Idempotente."""
    if getattr(sender, "name", None) != "clientes":
        return

    for nombre_grupo, labels in PERMISOS_CLIENTES_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "clientes", labels)
