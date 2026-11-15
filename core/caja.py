"""
Operaciones de caja que necesitan PIN (además de abrir, que ya lo pide SesionCaja.abrir).

- Cerrar: permiso core.cerrar_caja (gerente y jefe; administración NO) + PIN.
- Movimiento manual (ingreso, egreso, ajuste): permiso core.movimientos_caja + PIN; actualiza el
  saldo estimado de la sesión abierta. Un egreso no puede dejar la caja en negativo.
- Quien no es gerente sólo opera cajas de su sucursal fija.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from .models import Caja, CajaMovimiento, SesionCaja, TipoMovCaja

TIPOS_MANUALES = (TipoMovCaja.INGRESO, TipoMovCaja.EGRESO, TipoMovCaja.AJUSTE)


def es_gerente(user) -> bool:
    from .admin import _es_gerente

    return _es_gerente(user)


def cajas_visibles(user):
    """Cajas que el usuario puede ver: todas (gerente) o las de su sucursal fija."""
    qs = Caja.objects.select_related("sucursal").filter(activa=True)
    if getattr(user, "es_portal", True):
        return qs.none()
    if user.is_superuser or es_gerente(user):
        return qs
    return qs.filter(sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()


def sesiones_visibles(user):
    return SesionCaja.objects.select_related("caja__sucursal").filter(caja__in=cajas_visibles(user))


def _verificar_pin(usuario, pin: str) -> None:
    if not usuario.action_pin_hash:
        raise ValidationError("Primero configurá tu PIN (menú Sistema → Mi PIN).")
    usuario.verify_action_pin_or_raise((pin or "").strip())


def cerrar_sesion(sesion: SesionCaja, usuario, *, pin: str, total_contado: Decimal, observacion: str = "",
                  ip: str | None = None) -> SesionCaja:
    if not (usuario.is_superuser or usuario.has_perm("core.cerrar_caja")):
        raise PermissionDenied("No tenés permiso para cerrar la caja.")
    _verificar_pin(usuario, pin)
    sesion.cerrar(usuario, total_contado, observacion=observacion, ip=ip)
    sesion.refresh_from_db()
    return sesion


def registrar_movimiento(caja: Caja, usuario, *, tipo: str, monto: Decimal, motivo: str, pin: str) -> CajaMovimiento:
    if not (usuario.is_superuser or usuario.has_perm("core.movimientos_caja")):
        raise PermissionDenied("No tenés permiso para registrar movimientos de caja.")
    if not cajas_visibles(usuario).filter(pk=caja.pk).exists():
        raise PermissionDenied("Esa caja no es de tu sucursal.")
    if tipo not in TIPOS_MANUALES:
        raise ValidationError("Para abrir o cerrar la caja usá esas pantallas.")
    monto = Decimal(monto or 0).quantize(Decimal("0.01"))
    if monto <= 0:
        raise ValidationError("El monto tiene que ser mayor que cero.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Indicá el motivo del movimiento.")
    _verificar_pin(usuario, pin)

    with transaction.atomic():
        sesion = SesionCaja.objects.select_for_update().filter(caja=caja, estado=SesionCaja.Estado.ABIERTA).first()
        if not sesion:
            raise ValidationError("La caja no está abierta. Abrila antes de registrar movimientos.")
        delta = -monto if tipo == TipoMovCaja.EGRESO else monto
        if sesion.saldo_estimado + delta < 0:
            raise ValidationError(
                f"El egreso ({monto}) supera el efectivo estimado en caja ({sesion.saldo_estimado})."
            )
        movimiento = CajaMovimiento.objects.create(
            caja=caja, sesion=sesion, tipo=tipo, monto=monto, motivo=motivo[:255], creado_por=usuario,
        )
        SesionCaja.objects.filter(pk=sesion.pk).update(saldo_estimado=F("saldo_estimado") + delta)
    return movimiento


def configurar_pin(usuario, *, nuevo: str, repetido: str, actual: str = "") -> None:
    """Cambia el PIN; si ya tenía uno, exige el actual (salvo superusuario)."""
    if nuevo != repetido:
        raise ValidationError({"repetir_pin": "Los dos PIN no coinciden."})
    if not nuevo.isdigit() or not 4 <= len(nuevo) <= 6:
        raise ValidationError({"nuevo_pin": "El PIN tiene que tener entre 4 y 6 números."})
    if usuario.action_pin_hash and not usuario.is_superuser:
        if not actual:
            raise ValidationError({"pin_actual": "Ingresá tu PIN actual para cambiarlo."})
        try:
            usuario.verify_action_pin_or_raise(actual)
        except PermissionDenied as e:
            raise ValidationError({"pin_actual": str(e)})
    from .models import Usuario, _pin_fingerprint

    # Dos usuarios no pueden tener el mismo PIN (también lo impide la base).
    if Usuario.objects.filter(action_pin_fingerprint=_pin_fingerprint(nuevo)).exclude(pk=usuario.pk).exists():
        raise ValidationError({"nuevo_pin": "Ese PIN no está disponible. Elegí otro."})
    usuario.set_action_pin(nuevo)
    usuario.pin_failed_attempts = 0
    usuario.pin_locked_until = None
    usuario.save(update_fields=["action_pin_hash", "action_pin_fingerprint", "pin_failed_attempts", "pin_locked_until"])
