"""
Proveedores y compras del taller.

Portado del POS original sin la FK a Empresa. Cambios respecto del original:
- Sin vencimiento de lote (se eliminó StockLote) ni la columna legacy total_linea.
- confirmar() y anular() son métodos del modelo y hacen t odo en una transacción
  (antes el stock lo aplicaba una señal después de guardar).
- Se registra quién confirmó/anuló y los movimientos de stock llevan el usuario.
- Los ítems sólo se modifican mientras la compra está en BORRADOR.
- Los servicios suman al total pero no tocan stock ni costo promedio.
- El adjunto (factura) se guarda en almacenamiento privado, sin URL pública.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.text import slugify

from core.almacenamiento import almacenamiento_privado
from productos.models import MovimientoStock, StockSucursal, ajustar_stock

CERO = Decimal("0.00")
ADJUNTO_MAX_MB = 10
_DOC_NUMERICO_RE = re.compile(r"^[0-9\s\-\.]+$")


def _q2(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validar_tamano_adjunto(archivo) -> None:
    if archivo and archivo.size > ADJUNTO_MAX_MB * 1024 * 1024:
        raise ValidationError(f"El archivo no puede superar los {ADJUNTO_MAX_MB} MB.")


def ruta_adjunto_compra(instance: "Compra", filename: str) -> str:
    """compras/<id_proveedor>_<slug>/<YYYY>/<MM>/<archivo> (dentro del almacenamiento privado)."""
    fecha = instance.fecha or timezone.now()
    prov = instance.proveedor if instance.proveedor_id else None
    carpeta = f"{prov.id}_{slugify(prov.nombre)[:30]}" if prov else "sin_proveedor"
    return f"compras/{carpeta}/{fecha:%Y}/{fecha:%m}/{filename}"


# ===========================
# Proveedor
# ===========================

class Proveedor(models.Model):
    nombre = models.CharField(max_length=120)
    documento = models.CharField(max_length=40, blank=True, help_text="CUIT u otro documento.")
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    activo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("nombre",)
        permissions = [("gestionar_proveedores", "Puede gestionar proveedores")]
        indexes = [models.Index(fields=["nombre"]), models.Index(fields=["activo"])]
        constraints = [
            models.UniqueConstraint(
                fields=["documento"],
                condition=~Q(documento=""),
                name="uq_proveedor_documento_no_vacio",
                violation_error_message="Ya existe un proveedor con este documento.",
            ),
        ]
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"

    def __str__(self) -> str:
        return self.nombre

    def _normalizar(self) -> None:
        self.nombre = (self.nombre or "").strip()
        doc = (self.documento or "").strip()
        if doc and _DOC_NUMERICO_RE.match(doc):  # CUIT con guiones/puntos → sólo dígitos
            doc = re.sub(r"\D+", "", doc)
        self.documento = doc

    def clean(self):
        super().clean()
        self._normalizar()

    def save(self, *args, **kwargs):
        self._normalizar()
        self.full_clean()
        return super().save(*args, **kwargs)


# ===========================
# Compra
# ===========================

class Compra(models.Model):
    """Cabecera de compra (factura / remito de proveedor)."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        ANULADA = "ANULADA", "Anulada"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="compras")
    sucursal = models.ForeignKey(
        "core.Sucursal", on_delete=models.PROTECT, related_name="compras",
        help_text="Sucursal donde entra el stock.",
    )
    fecha = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.BORRADOR, editable=False)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    iva_total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)

    aplicada_a_stock = models.BooleanField(default=False, editable=False)

    observaciones = models.TextField(blank=True, null=True)
    documento_adjunto = models.FileField(
        upload_to=ruta_adjunto_compra,
        storage=almacenamiento_privado,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validar_tamano_adjunto,
        ],
        help_text=f"Factura / remito escaneado (PDF o imagen). Máx. {ADJUNTO_MAX_MB} MB. Archivo privado.",
    )

    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="compras_creadas", editable=False,
    )
    confirmada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="compras_confirmadas", editable=False,
    )
    confirmada_el = models.DateTimeField(null=True, blank=True, editable=False)
    anulada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="compras_anuladas", editable=False,
    )
    anulada_el = models.DateTimeField(null=True, blank=True, editable=False)

    creado_el = models.DateTimeField(auto_now_add=True, editable=False)
    modificado_el = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("-fecha", "-id")
        permissions = [
            ("registrar_compras", "Puede registrar compras"),
            ("anular_compras", "Puede anular compras"),
        ]
        indexes = [
            models.Index(fields=["sucursal", "fecha"]),
            models.Index(fields=["proveedor", "fecha"]),
            models.Index(fields=["estado"]),
        ]
        verbose_name = "compra"
        verbose_name_plural = "compras"

    def __str__(self) -> str:
        return f"Compra #{self.id} - {self.proveedor} - {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if self.pk and "update_fields" not in kwargs:
            estado = Compra.objects.filter(pk=self.pk).values_list("estado", flat=True).first()
            if estado and estado != self.Estado.BORRADOR:
                raise ValidationError("Sólo se pueden editar compras en BORRADOR.")
        self.full_clean()
        super().save(*args, **kwargs)

    def recalcular_totales(self) -> None:
        ag = self.detalles.aggregate(
            subtotal=Coalesce(Sum("subtotal"), CERO),
            iva=Coalesce(Sum("iva_total"), CERO),
            total=Coalesce(Sum("total"), CERO),
        )
        # _q2: en SQLite las sumas de decimales pueden volver con residuos de punto flotante.
        self.subtotal, self.iva_total, self.total = _q2(ag["subtotal"]), _q2(ag["iva"]), _q2(ag["total"])
        Compra.objects.filter(pk=self.pk).update(
            subtotal=self.subtotal, iva_total=self.iva_total, total=self.total, modificado_el=timezone.now()
        )

    def _refrescar_desde(self, compra: "Compra") -> None:
        for f in self._meta.concrete_fields:
            setattr(self, f.attname, getattr(compra, f.attname))

    # ------------ operaciones de negocio ------------

    def confirmar(self, *, user) -> "Compra":
        """BORRADOR → CONFIRMADA: suma stock y actualiza costo promedio, t odo o nada."""
        if not (user.is_superuser or user.has_perm("compras.registrar_compras")):
            raise PermissionDenied("No tiene permiso para confirmar compras.")

        with transaction.atomic():
            compra = Compra.objects.select_for_update().select_related("sucursal").get(pk=self.pk)
            if compra.estado != self.Estado.BORRADOR:
                raise ValidationError("Sólo se pueden confirmar compras en BORRADOR.")
            if not compra.detalles.exists():
                raise ValidationError("La compra no tiene ítems.")

            for det in compra.detalles.select_related("producto"):
                # Primero el costo (usa el stock previo), después el stock.
                StockSucursal.actualizar_costo_promedio_por_compra(
                    sucursal=compra.sucursal, producto=det.producto,
                    cantidad=det.cantidad, costo_unitario=det.costo_unitario,
                )
                ajustar_stock(
                    sucursal=compra.sucursal, producto=det.producto, delta=det.cantidad,
                    tipo=MovimientoStock.Tipo.COMPRA, referencia=compra, usuario=user,
                    descripcion=f"Compra #{compra.id}",
                )

            compra.estado = self.Estado.CONFIRMADA
            compra.aplicada_a_stock = True
            compra.confirmada_por = user
            compra.confirmada_el = timezone.now()
            compra.save(update_fields=["estado", "aplicada_a_stock", "confirmada_por", "confirmada_el", "modificado_el"])

        self._refrescar_desde(compra)
        return self

    def anular(self, *, user) -> "Compra":
        """
        CONFIRMADA → ANULADA devuelve el stock (falla si ya se usó). BORRADOR → ANULADA sólo cambia el estado.
        El costo promedio no se recalcula.
        """
        if not (user.is_superuser or user.has_perm("compras.anular_compras")):
            raise PermissionDenied("No tiene permiso para anular compras.")

        with transaction.atomic():
            compra = Compra.objects.select_for_update().select_related("sucursal").get(pk=self.pk)
            if compra.estado == self.Estado.ANULADA:
                raise ValidationError("La compra ya está ANULADA.")

            if compra.aplicada_a_stock:
                for det in compra.detalles.select_related("producto"):
                    try:
                        ajustar_stock(
                            sucursal=compra.sucursal, producto=det.producto, delta=-det.cantidad,
                            tipo=MovimientoStock.Tipo.DEVOLUCION_COMPRA, referencia=compra, usuario=user,
                            descripcion=f"Anulación compra #{compra.id}",
                        )
                    except ValidationError:
                        raise ValidationError(
                            f"No se puede anular: parte de {det.producto} ya se usó "
                            f"y el stock quedaría negativo."
                        )

            compra.estado = self.Estado.ANULADA
            compra.aplicada_a_stock = False
            compra.anulada_por = user
            compra.anulada_el = timezone.now()
            compra.save(update_fields=["estado", "aplicada_a_stock", "anulada_por", "anulada_el", "modificado_el"])

        self._refrescar_desde(compra)
        return self


class CompraDetalle(models.Model):
    compra = models.ForeignKey(Compra, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey("productos.Producto", on_delete=models.PROTECT, related_name="compras_detalle")

    cantidad = models.DecimalField(max_digits=12, decimal_places=3)
    costo_unitario = models.DecimalField(
        max_digits=14, decimal_places=4, help_text="Costo unitario sin IVA (para el costo promedio)."
    )
    iva_tasa = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("21.00"), help_text="IVA %.")

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    iva_total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)

    creado_el = models.DateTimeField(auto_now_add=True, editable=False)
    modificado_el = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        indexes = [models.Index(fields=["compra", "producto"])]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_compra_detalle_cantidad_positiva"),
            models.CheckConstraint(condition=Q(costo_unitario__gte=0), name="ck_compra_detalle_costo_no_negativo"),
            models.CheckConstraint(
                condition=Q(iva_tasa__gte=0) & Q(iva_tasa__lte=100), name="ck_compra_detalle_iva_entre_0_100"
            ),
        ]
        verbose_name = "detalle de compra"
        verbose_name_plural = "detalles de compra"

    def __str__(self) -> str:
        return f"{self.compra} | {self.producto} x {self.cantidad}"

    def _verificar_compra_borrador(self) -> None:
        estado = Compra.objects.filter(pk=self.compra_id).values_list("estado", flat=True).first()
        if estado and estado != Compra.Estado.BORRADOR:
            raise ValidationError("Sólo se pueden modificar ítems de compras en BORRADOR.")

    def clean(self):
        super().clean()
        if self.cantidad is not None and self.cantidad <= 0:
            raise ValidationError({"cantidad": "La cantidad debe ser positiva."})
        if self.costo_unitario is not None and self.costo_unitario < 0:
            raise ValidationError({"costo_unitario": "El costo unitario debe ser ≥ 0."})

    def recalcular(self) -> None:
        cant = Decimal(str(self.cantidad or 0)).quantize(Decimal("0.001"))
        costo = Decimal(str(self.costo_unitario or 0)).quantize(Decimal("0.0001"))
        iva = Decimal(str(self.iva_tasa or 0)).quantize(Decimal("0.01"))
        self.subtotal = _q2(cant * costo)
        self.iva_total = _q2(self.subtotal * iva / 100)
        self.total = _q2(self.subtotal + self.iva_total)

    def save(self, *args, **kwargs):
        self._verificar_compra_borrador()
        self.recalcular()
        self.full_clean()
        super().save(*args, **kwargs)
        self.compra.recalcular_totales()

    def delete(self, *args, **kwargs):
        self._verificar_compra_borrador()
        compra = self.compra
        resultado = super().delete(*args, **kwargs)
        compra.recalcular_totales()
        return resultado
