"""
Pagos de cuenta corriente.

Cuando un cliente paga su deuda EN EFECTIVO, el dinero entra a la caja: se registra el crédito en
la cuenta corriente y, en la misma transacción, un ingreso en la sesión de caja abierta.
Con tarjeta o transferencia sólo baja la deuda (no hay efectivo que contar).
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from core.models import CajaMovimiento, SesionCaja, TipoMovCaja

from .models import Cliente, CuentaCorriente, MovimientoCuentaCorriente

MEDIOS = {"EFECTIVO": "Efectivo", "TARJETA": "Tarjeta", "TRANSFERENCIA": "Transferencia"}


def registrar_pago(cliente: Cliente, usuario, *, monto: Decimal, medio: str, sesion: SesionCaja | None = None,
                   nota: str = "") -> MovimientoCuentaCorriente:
    if not (usuario.is_superuser or usuario.has_perm("clientes.movimientos_cc")):
        raise PermissionDenied("No tenés permiso para registrar pagos de cuenta corriente.")
    if medio not in MEDIOS:
        raise ValidationError("Medio de pago inválido.")
    monto = Decimal(monto or 0).quantize(Decimal("0.01"))
    if monto <= 0:
        raise ValidationError("El monto tiene que ser mayor que cero.")
    if medio == "EFECTIVO":
        if sesion is None or sesion.estado != SesionCaja.Estado.ABIERTA:
            raise ValidationError("Para cobrar en efectivo tiene que haber una caja abierta.")
        if not usuario.is_superuser and usuario.sucursal_id and sesion.caja.sucursal_id != usuario.sucursal_id:
            raise PermissionDenied("Esa caja es de otra sucursal.")

    descripcion = f"Pago ({MEDIOS[medio].lower()})" + (f" · {nota.strip()}" if nota.strip() else "")
    with transaction.atomic():
        cuenta, _ = CuentaCorriente.objects.get_or_create(cliente=cliente)
        movimiento = MovimientoCuentaCorriente.objects.create(
            cuenta=cuenta, tipo=MovimientoCuentaCorriente.Tipo.CREDITO, monto=monto,
            descripcion=descripcion[:255], creado_por=usuario,
        )  # valida que no supere la deuda
        if medio == "EFECTIVO":
            sesion = SesionCaja.objects.select_for_update().get(pk=sesion.pk)
            if sesion.estado != SesionCaja.Estado.ABIERTA:
                raise ValidationError("La caja se cerró mientras se registraba el pago.")
            CajaMovimiento.objects.create(
                caja=sesion.caja, sesion=sesion, tipo=TipoMovCaja.INGRESO, monto=monto,
                motivo=f"Pago cuenta corriente: {cliente.nombre}"[:255], creado_por=usuario,
            )
            SesionCaja.objects.filter(pk=sesion.pk).update(saldo_estimado=F("saldo_estimado") + monto)
    return movimiento
