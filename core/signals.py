# core/signals.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models.signals import post_migrate, pre_delete, pre_save
from django.dispatch import receiver

from .models import Caja, Empresa, SesionCaja, Sucursal
from .roles import (
    GRUPO_ADMINISTRACION,
    GRUPO_GERENTE,
    GRUPO_JEFE,
    GRUPO_MECANICO,
    sincronizar_permisos_grupo,
)


# ============================================================
# Protecciones de borrado (mensajes claros)
# Nota: con on_delete=PROTECT, Django puede lanzar ProtectedError antes de estas señales.
# Quedan como defensa en profundidad y para dar mensajes en castellano.
# ============================================================

@receiver(pre_delete, sender=Empresa, dispatch_uid="core_prevent_delete_empresa")
def prevenir_eliminar_empresa(sender, instance: Empresa, **kwargs):
    raise ValidationError("La empresa del taller no se puede eliminar.")


@receiver(pre_delete, sender=Sucursal, dispatch_uid="core_prevent_delete_sucursal_with_cajas")
def prevenir_eliminar_sucursal_con_cajas(sender, instance: Sucursal, **kwargs):
    if instance.cajas.exists():
        raise ValidationError(
            "No se puede eliminar una SUCURSAL con cajas asociadas. "
            "Orden de borrado: movimiento → sesión → caja → sucursal."
        )


@receiver(pre_delete, sender=Caja, dispatch_uid="core_prevent_delete_caja_with_deps")
def prevenir_eliminar_caja_con_dependencias(sender, instance: Caja, **kwargs):
    if instance.sesiones.exists() or instance.movimientos.exists():
        raise ValidationError(
            "No se puede eliminar una CAJA con sesiones o movimientos asociados. "
            "Orden de borrado: movimiento → sesión → caja."
        )


@receiver(pre_delete, sender=SesionCaja, dispatch_uid="core_prevent_delete_sesion_with_movs")
def prevenir_eliminar_sesion_con_movimientos(sender, instance: SesionCaja, **kwargs):
    if instance.movimientos.exists():
        raise ValidationError(
            "No se puede eliminar una SESIÓN con movimientos asociados. "
            "Orden de borrado: movimiento → sesión."
        )


# ============================================================
# Protecciones de integridad en cambios peligrosos
# (se aplican siempre, sin depender de vistas ni del admin)
# ============================================================

@receiver(pre_save, sender=Caja, dispatch_uid="core_prevent_move_caja_sucursal_if_deps")
def prevenir_mover_caja_de_sucursal_si_tiene_sesiones(sender, instance: Caja, **kwargs):
    """No se puede mover una Caja de sucursal si ya tiene sesiones o movimientos."""
    if not instance.pk:
        return

    old = Caja.objects.filter(pk=instance.pk).values("sucursal_id").first()
    if not old:
        return

    if instance.sucursal_id != old["sucursal_id"]:
        if instance.sesiones.exists() or instance.movimientos.exists():
            raise ValidationError(
                "No se puede cambiar la SUCURSAL de una CAJA con sesiones o movimientos asociados. "
                "Cree una nueva caja en la sucursal destino."
            )


@receiver(pre_save, sender=SesionCaja, dispatch_uid="core_prevent_move_sesion_caja")
def prevenir_mover_sesion_de_caja(sender, instance: SesionCaja, **kwargs):
    """Una SesionCaja es inmutable respecto de su caja."""
    if not instance.pk:
        return

    old = SesionCaja.objects.filter(pk=instance.pk).values("caja_id").first()
    if not old:
        return

    if instance.caja_id != old["caja_id"]:
        raise ValidationError("No se puede cambiar la CAJA de una SESIÓN existente.")


# ============================================================
# Grupos del personal y permisos de CORE
# ============================================================

PERMISOS_CORE_POR_GRUPO = {
    # Todo: caja completa, estructura (empresa, sucursales, cajas, usuarios).
    GRUPO_GERENTE: [
        "core.abrir_caja",
        "core.cerrar_caja",
        "core.movimientos_caja",
        "core.administrar_core",
        "core.view_empresa",
        "core.change_empresa",
        "core.view_sucursal",
        "core.add_sucursal",
        "core.change_sucursal",
        "core.view_caja",
        "core.add_caja",
        "core.change_caja",
        "core.view_sesioncaja",
        "core.view_cajamovimiento",
        "core.view_puntoventa",
        "core.add_puntoventa",
        "core.change_puntoventa",
        "core.view_usuario",
        "core.add_usuario",
        "core.change_usuario",
    ],
    # Opera la caja completa en su sucursal (abre, mueve efectivo y cierra).
    GRUPO_JEFE: [
        "core.abrir_caja",
        "core.cerrar_caja",
        "core.movimientos_caja",
        "core.view_sucursal",
        "core.view_caja",
        "core.view_sesioncaja",
        "core.view_cajamovimiento",
    ],
    # Atención y cobro: abre caja y registra movimientos, pero NO cierra.
    GRUPO_ADMINISTRACION: [
        "core.abrir_caja",
        "core.movimientos_caja",
        "core.view_sucursal",
        "core.view_caja",
        "core.view_sesioncaja",
        "core.view_cajamovimiento",
    ],
    # Sin permisos de core: trabaja desde las órdenes (app taller), en las que tiene asignadas.
    GRUPO_MECANICO: [],
}


@receiver(post_migrate, dispatch_uid="core_crear_grupos_y_permisos")
def crear_grupos_y_permisos_core(sender, **kwargs):
    """
    Crea los grupos del personal y sincroniza sus permisos de CORE.
    Corre al migrar la app 'core' (y en cada `migrate`) y es idempotente.
    """
    if getattr(sender, "name", None) != "core":
        return

    for nombre_grupo, labels in PERMISOS_CORE_POR_GRUPO.items():
        sincronizar_permisos_grupo(nombre_grupo, "core", labels)