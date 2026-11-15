"""
Ventas del taller.

Portado del POS original sin la FK a Empresa. Cambios respecto del original:
- Los servicios (y productos sin control de stock) se venden sin chequear ni descontar stock.
- El costo unitario se toma del costo promedio de la sucursal si no viene informado.
- Los ítems sólo se agregan, cambian o borran mientras la venta está ABIERTA.
- finalizar(): los medios de pago deben sumar exactamente el total, y el monto a cuenta
  corriente genera el débito al cliente (respetando su límite de crédito).
- anular(): revierte stock, efectivo y cuenta corriente. Sólo con ventas.anular_venta.
- Sin integración contable (la app contabilidad no está portada).
- Campos AFIP: se conservan, sin uso.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from clientes.models import Cliente, CuentaCorriente, MovimientoCuentaCorriente
from core.models import Caja, SesionCaja, Sucursal, Usuario
from productos.models import MovimientoStock, Producto, StockSucursal, ajustar_stock

CERO = Decimal("0.00")
MEDIOS_PAGO = ("monto_efectivo", "monto_tarjeta", "monto_transferencia", "monto_ctacte")


def _q2(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# =======================
# Venta
# =======================

class Venta(models.Model):
    class TipoComprobanteAFIP(models.IntegerChoices):
        FACTURA_A = 1, "Factura A"
        NOTA_DEBITO_A = 2, "Nota de débito A"
        NOTA_CREDITO_A = 3, "Nota de crédito A"
        FACTURA_B = 6, "Factura B"
        NOTA_DEBITO_B = 7, "Nota de débito B"
        NOTA_CREDITO_B = 8, "Nota de crédito B"
        FACTURA_C = 11, "Factura C"
        NOTA_DEBITO_C = 12, "Nota de débito C"
        NOTA_CREDITO_C = 13, "Nota de crédito C"

    class ConceptoAFIP(models.IntegerChoices):
        PRODUCTOS = 1, "Productos"
        SERVICIOS = 2, "Servicios"
        PRODUCTOS_Y_SERVICIOS = 3, "Productos y servicios"

    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        FINALIZADA = "FINALIZADA", "Finalizada"
        ANULADA = "ANULADA", "Anulada"

    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="ventas")
    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="ventas")
    sesion = models.ForeignKey(SesionCaja, on_delete=models.PROTECT, related_name="ventas")
    cliente = models.ForeignKey(
        Cliente, on_delete=models.SET_NULL, null=True, blank=True, related_name="ventas"
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.ABIERTA)

    # Totales
    total_items = models.PositiveIntegerField(default=0, help_text="Cantidad de renglones.")
    total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    costo_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=CERO, help_text="Costo total (sin IVA)."
    )
    utilidad_bruta = models.DecimalField(
        max_digits=14, decimal_places=2, default=CERO, help_text="Neto gravado - costo total."
    )

    # Medios de pago (deben sumar el total al finalizar)
    monto_efectivo = models.DecimalField(
        max_digits=14, decimal_places=2, default=CERO, help_text="Efectivo que queda en caja (ya descontado el vuelto)."
    )
    monto_tarjeta = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    monto_transferencia = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    monto_ctacte = models.DecimalField(
        max_digits=14, decimal_places=2, default=CERO, help_text="Importe a cuenta corriente del cliente."
    )

    # Seguimiento
    creada_el = models.DateTimeField(auto_now_add=True)
    finalizada_el = models.DateTimeField(null=True, blank=True)
    anulada_el = models.DateTimeField(null=True, blank=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ventas_creadas"
    )
    finalizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ventas_finalizadas"
    )
    anulada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ventas_anuladas"
    )

    # ---- AFIP (sin uso en el taller) ----
    tipo_comprobante_afip = models.PositiveSmallIntegerField(choices=TipoComprobanteAFIP.choices, null=True, blank=True)
    letra_comprobante = models.CharField(max_length=1, blank=True)
    punto_venta = models.ForeignKey(
        "core.PuntoVenta", on_delete=models.PROTECT, null=True, blank=True, related_name="ventas"
    )
    numero_comprobante = models.BigIntegerField(null=True, blank=True)
    fecha_emision = models.DateTimeField(default=timezone.now)
    concepto_afip = models.PositiveSmallIntegerField(choices=ConceptoAFIP.choices, null=True, blank=True)
    moneda_afip = models.CharField(max_length=3, default="PES")
    moneda_cotizacion = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("1.0000"))
    importe_neto_gravado = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    importe_exento = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    importe_iva = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    importe_tributos = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    cae = models.CharField(max_length=14, null=True, blank=True)
    cae_vencimiento = models.DateField(null=True, blank=True)
    cbte_tipo_original = models.PositiveSmallIntegerField(null=True, blank=True)
    cbte_punto_venta_original = models.PositiveIntegerField(null=True, blank=True)
    cbte_numero_original = models.BigIntegerField(null=True, blank=True)
    afip_estado = models.CharField(max_length=20, blank=True)
    afip_errores = models.TextField(blank=True)

    observacion = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-creada_el",)
        indexes = [
            models.Index(fields=["sucursal", "caja"]),
            models.Index(fields=["estado"]),
            models.Index(fields=["creada_el"]),
        ]
        permissions = [
            ("crear_venta", "Puede crear ventas"),
            ("finalizar_venta", "Puede finalizar ventas"),
            ("anular_venta", "Puede anular ventas"),
            ("ver_ventas", "Puede ver el listado de ventas"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(total__gte=0), name="venta_total_no_negativo"),
            models.CheckConstraint(condition=Q(monto_efectivo__gte=0), name="venta_monto_efectivo_no_negativo"),
            models.CheckConstraint(condition=Q(monto_tarjeta__gte=0), name="venta_monto_tarjeta_no_negativo"),
            models.CheckConstraint(
                condition=Q(monto_transferencia__gte=0), name="venta_monto_transferencia_no_negativo"
            ),
            models.CheckConstraint(condition=Q(monto_ctacte__gte=0), name="venta_monto_ctacte_no_negativo"),
        ]
        verbose_name = "venta"
        verbose_name_plural = "ventas"

    def __str__(self) -> str:
        return f"Venta #{self.id} - {self.sucursal} - {self.get_estado_display()}"

    def clean(self):
        super().clean()
        errores: dict[str, str] = {}
        if self.sucursal_id and self.caja_id and self.caja.sucursal_id != self.sucursal_id:
            errores["caja"] = "La caja no pertenece a la sucursal de la venta."
        if self.caja_id and self.sesion_id and self.sesion.caja_id != self.caja_id:
            errores["sesion"] = "La sesión no pertenece a la caja de la venta."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    # ------------ medios de pago ------------

    @property
    def total_medios_pago(self) -> Decimal:
        return sum((getattr(self, campo) or CERO for campo in MEDIOS_PAGO), CERO)

    @property
    def total_pagado(self) -> Decimal:
        """Alias de total_medios_pago (compatibilidad)."""
        return self.total_medios_pago

    @property
    def efectivo_en_caja(self) -> Decimal:
        return self.monto_efectivo or CERO

    # ------------ helpers internos ------------

    def recalcular_totales(self, save: bool = True):
        ag = self.detalles.aggregate(
            total=Coalesce(Sum("importe"), CERO),
            neto=Coalesce(Sum("importe_neto"), CERO),
            iva=Coalesce(Sum("importe_iva"), CERO),
            costo_total=Coalesce(Sum("costo_total"), CERO),
        )
        # _q2: en SQLite las sumas de decimales pueden volver con residuos de punto flotante.
        self.total = _q2(ag["total"])
        self.importe_neto_gravado = _q2(ag["neto"])
        self.importe_iva = _q2(ag["iva"])
        self.importe_exento = CERO
        self.importe_tributos = CERO
        self.costo_total = _q2(ag["costo_total"])
        self.utilidad_bruta = _q2(self.importe_neto_gravado - self.costo_total)
        self.total_items = self.detalles.count()

        if save:
            self.save(update_fields=[
                "total", "total_items", "importe_neto_gravado", "importe_exento",
                "importe_iva", "importe_tributos", "costo_total", "utilidad_bruta",
            ])

    def _aplicar_stock(self, signo: int, user: Optional[Usuario] = None) -> None:
        """signo -1 al finalizar (descuenta), +1 al anular (devuelve). Ignora servicios."""
        tipo = MovimientoStock.Tipo.VENTA if signo < 0 else MovimientoStock.Tipo.DEVOLUCION_VENTA
        for det in self.detalles.select_related("producto"):
            ajustar_stock(
                sucursal=self.sucursal,
                producto=det.producto,
                delta=signo * det.cantidad,
                tipo=tipo,
                referencia=self,
                usuario=user,
                descripcion=f"Venta #{self.id}",
            )

    def _bloquear(self, estado_esperado: str, mensaje: str) -> tuple["Venta", SesionCaja]:
        """Bloquea venta y sesión (select_for_update) y verifica estados. Usar dentro de atomic()."""
        venta = type(self).objects.select_for_update().select_related("sucursal", "cliente").get(pk=self.pk)
        if venta.estado != estado_esperado:
            raise ValidationError(mensaje)
        sesion = SesionCaja.objects.select_for_update().get(pk=venta.sesion_id)
        if sesion.estado != SesionCaja.Estado.ABIERTA:
            raise ValidationError("La sesión de caja asociada no está ABIERTA.")
        if sesion.caja_id != venta.caja_id:
            raise ValidationError("Inconsistencia: la sesión no pertenece a la caja de la venta.")
        return venta, sesion

    def _refrescar_desde(self, venta: "Venta") -> None:
        for f in self._meta.concrete_fields:
            setattr(self, f.attname, getattr(venta, f.attname))

    # ------------ operaciones de negocio ------------

    def finalizar(
        self,
        *,
        user: Usuario,
        efectivo=None,
        tarjeta=None,
        transferencia=None,
        ctacte=None,
    ) -> "Venta":
        """
        Cierra la venta: descuenta stock, suma el efectivo a la sesión de caja y, si hay
        monto a cuenta corriente, lo debita al cliente (respetando su límite de crédito).

        Los medios de pago pueden venir como argumentos o estar ya guardados en la venta.
        Deben sumar exactamente el total; si no se informa ninguno, todo es efectivo.
        """
        if not (user.is_superuser or user.has_perm("ventas.finalizar_venta")):
            raise PermissionDenied("No tiene permiso para finalizar ventas.")

        with transaction.atomic():
            venta, sesion = self._bloquear(
                self.Estado.ABIERTA, "La venta ya fue finalizada o anulada por otro usuario."
            )
            if not venta.detalles.exists():
                raise ValidationError("La venta no tiene ítems.")

            venta.recalcular_totales(save=False)
            if venta.total <= 0:
                raise ValidationError("El total de la venta debe ser mayor que 0.")

            # Medios de pago
            for campo, valor in zip(MEDIOS_PAGO, (efectivo, tarjeta, transferencia, ctacte)):
                if valor is not None:
                    setattr(venta, campo, _q2(valor))
            if any(getattr(venta, c) < 0 for c in MEDIOS_PAGO):
                raise ValidationError("Los montos de pago no pueden ser negativos.")
            if venta.total_medios_pago == 0:
                venta.monto_efectivo = venta.total
            if venta.total_medios_pago != venta.total:
                raise ValidationError(
                    f"Los medios de pago ({venta.total_medios_pago}) no coinciden con el total ({venta.total})."
                )

            venta._aplicar_stock(signo=-1, user=user)

            if venta.monto_ctacte > 0:
                if not venta.cliente_id:
                    raise ValidationError("Para cargar a cuenta corriente hay que elegir un cliente.")
                cuenta, _ = CuentaCorriente.objects.get_or_create(cliente=venta.cliente)
                MovimientoCuentaCorriente.objects.create(
                    cuenta=cuenta,
                    tipo=MovimientoCuentaCorriente.Tipo.DEBITO,
                    monto=venta.monto_ctacte,
                    descripcion=f"Venta #{venta.id}",
                    creado_por=user,
                )

            venta.estado = self.Estado.FINALIZADA
            venta.finalizada_el = timezone.now()
            venta.finalizada_por = user
            venta.save()

            SesionCaja.objects.filter(pk=sesion.pk).update(
                saldo_estimado=F("saldo_estimado") + venta.efectivo_en_caja
            )

        self._refrescar_desde(venta)
        return self

    def anular(self, *, user: Usuario) -> "Venta":
        """Revierte stock, efectivo de la sesión y cuenta corriente. Sólo con ventas.anular_venta."""
        if not (user.is_superuser or user.has_perm("ventas.anular_venta")):
            raise PermissionDenied("No tiene permiso para anular ventas.")

        with transaction.atomic():
            venta, sesion = self._bloquear(
                self.Estado.FINALIZADA, "Sólo se pueden anular ventas FINALIZADAS."
            )

            venta._aplicar_stock(signo=+1, user=user)

            if venta.monto_ctacte > 0 and venta.cliente_id:
                cuenta = CuentaCorriente.objects.get(cliente=venta.cliente)
                if venta.monto_ctacte > cuenta.saldo:
                    raise ValidationError(
                        f"No se puede anular: el cliente ya pagó parte de esta venta "
                        f"(deuda actual {cuenta.saldo}, a revertir {venta.monto_ctacte})."
                    )
                MovimientoCuentaCorriente.objects.create(
                    cuenta=cuenta,
                    tipo=MovimientoCuentaCorriente.Tipo.CREDITO,
                    monto=venta.monto_ctacte,
                    descripcion=f"Anulación venta #{venta.id}",
                    creado_por=user,
                )

            venta.estado = self.Estado.ANULADA
            venta.anulada_el = timezone.now()
            venta.anulada_por = user
            venta.save(update_fields=["estado", "anulada_el", "anulada_por"])

            SesionCaja.objects.filter(pk=sesion.pk).update(
                saldo_estimado=F("saldo_estimado") - venta.efectivo_en_caja
            )

        self._refrescar_desde(venta)
        return self


# =======================
# Detalle de venta
# =======================

class VentaDetalle(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="ventas_detalle")

    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1.000"))
    precio_unitario = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Vacío = precio vigente del producto. 0 = sin cargo.",
    )
    importe = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)

    # AFIP (sin uso)
    descripcion_afip = models.CharField(max_length=200, blank=True)
    unidad_medida_afip = models.CharField(max_length=3, blank=True)
    gtin = models.CharField(max_length=20, blank=True)

    precio_unitario_neto = models.DecimalField(
        max_digits=14, decimal_places=2, default=CERO, help_text="Precio unitario sin IVA."
    )
    alicuota_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("21.00"))
    importe_neto = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)
    importe_iva = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)

    costo_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Costo unitario (sin IVA). Si es 0, se toma el costo promedio de la sucursal.",
    )
    costo_total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("venta", "id")
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ventadetalle_cantidad_positiva"),
            models.CheckConstraint(condition=Q(precio_unitario__gte=0), name="ventadetalle_precio_no_negativo"),
        ]
        verbose_name = "detalle de venta"
        verbose_name_plural = "detalles de venta"

    def __str__(self) -> str:
        return f"Venta #{self.venta_id} · {self.producto} x {self.cantidad}"

    @property
    def subtotal(self):
        """Alias compatible: d.subtotal -> d.importe"""
        return self.importe

    def _verificar_venta_abierta(self) -> None:
        estado = Venta.objects.filter(pk=self.venta_id).values_list("estado", flat=True).first()
        if estado and estado != Venta.Estado.ABIERTA:
            raise ValidationError("Sólo se pueden modificar ítems de ventas ABIERTAS.")

    def clean(self):
        super().clean()
        if not self.producto_id:
            return
        producto = self.producto

        if self.cantidad is None or self.cantidad <= 0:
            raise ValidationError({"cantidad": "La cantidad debe ser mayor que 0."})
        self.cantidad = Decimal(self.cantidad).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        if not producto.activo:
            raise ValidationError({"producto": "No se puede vender un producto inactivo."})

        # Precio por defecto: precio vigente del producto
        # Vacío → precio vigente del producto. Un 0 explícito se respeta (sin cargo).
        if self.precio_unitario is None:
            self.precio_unitario = _q2(producto.precio_vigente)
        if self.precio_unitario < 0:
            raise ValidationError({"precio_unitario": "El precio no puede ser negativo."})
        self.importe = _q2(self.precio_unitario * self.cantidad)

        # Datos AFIP por línea
        self.descripcion_afip = self.descripcion_afip or producto.nombre[:200]
        self.gtin = self.gtin or (producto.codigo_barras or "")[:20]

        # IVA
        self.alicuota_iva = _q2(producto.iva_tasa if producto.iva_tasa is not None else self.alicuota_iva)
        if self.alicuota_iva > 0 and producto.precio_incluye_impuestos:
            self.precio_unitario_neto = _q2(self.precio_unitario / (1 + self.alicuota_iva / 100))
        else:
            self.precio_unitario_neto = _q2(self.precio_unitario)
        self.importe_neto = _q2(self.precio_unitario_neto * self.cantidad)
        self.importe_iva = max(_q2(self.importe - self.importe_neto), CERO)

        # Stock y costo (sólo productos que controlan stock)
        sucursal_id = self.venta.sucursal_id if self.venta_id else None
        if producto.controla_stock and sucursal_id:
            stock = StockSucursal.objects.filter(sucursal_id=sucursal_id, producto=producto).first()
            disponible = stock.stock if stock else Decimal("0.000")
            if disponible < self.cantidad:
                raise ValidationError(
                    f"Stock insuficiente para {producto} en {self.venta.sucursal}. "
                    f"Disponible: {disponible}, solicitado: {self.cantidad}"
                )
            if not self.costo_unitario and stock:
                self.costo_unitario = stock.costo_promedio

        self.costo_unitario = Decimal(self.costo_unitario or 0).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        self.costo_total = _q2(self.costo_unitario * self.cantidad)

    def save(self, *args, **kwargs):
        self._verificar_venta_abierta()
        self.full_clean()
        super().save(*args, **kwargs)
        self.venta.recalcular_totales(save=True)

    def delete(self, *args, **kwargs):
        self._verificar_venta_abierta()
        venta = self.venta
        resultado = super().delete(*args, **kwargs)
        venta.recalcular_totales(save=True)
        return resultado
