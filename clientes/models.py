"""
Clientes del taller y su cuenta corriente.

Portado del POS original sin la FK a Empresa (el taller es una sola empresa).
Los clientes son de todo el taller (no por sucursal).
"""
from __future__ import annotations

import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import CondicionIVA


def _solo_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


class Cliente(models.Model):
    DOCUMENTO_CHOICES = [
        ("DNI", "DNI"),
        ("CUIT", "CUIT"),
        ("CUIL", "CUIL"),
        ("PASAPORTE", "Pasaporte"),
        ("OTRO", "Otro"),
    ]
    DOCUMENTOS_NUMERICOS = {"DNI", "CUIT", "CUIL"}

    nombre = models.CharField(max_length=200)
    doc_tipo = models.CharField(
        max_length=10,
        choices=DOCUMENTO_CHOICES,
        blank=True,
        help_text="Tipo de documento (DNI, CUIT, CUIL, etc.)",
    )
    doc_numero = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Número de documento / CUIT. En DNI, CUIT y CUIL se guardan sólo los dígitos.",
    )

    # AFIP: sin uso en el taller (campos inertes).
    condicion_iva = models.CharField(
        max_length=10,
        choices=CondicionIVA.choices,
        default=CondicionIVA.CONSUMIDOR_FINAL,
    )
    es_consumidor_final = models.BooleanField(default=True)

    email = models.EmailField(blank=True, null=True)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)

    limite_credito = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Límite de crédito en cuenta corriente (0 = sin crédito).",
    )
    activo = models.BooleanField(default=True)

    listas_autorizadas = models.ManyToManyField(
        "productos.ListaPrecio",
        blank=True,
        related_name="clientes_autorizados",
        help_text="Listas de precios que el cliente puede usar (opcional).",
    )

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("nombre",)
        indexes = [
            models.Index(fields=["nombre"]),
            models.Index(fields=["doc_numero"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["doc_numero"],
                condition=~Q(doc_numero=""),
                name="uq_cliente_doc_numero_no_vacio",
                violation_error_message="Ya existe un cliente con este número de documento.",
            ),
            models.CheckConstraint(
                condition=Q(limite_credito__gte=Decimal("0.00")),
                name="cliente_limite_credito_no_negativo",
            ),
        ]
        permissions = [
            ("ver_clientes", "Puede ver clientes"),
            ("gestionar_clientes", "Puede crear/editar clientes"),
            ("movimientos_cc", "Puede operar movimientos de cuenta corriente de clientes"),
        ]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def __str__(self) -> str:
        if self.doc_numero:
            return f"{self.nombre} ({self.doc_numero})"
        return self.nombre

    @property
    def es_cf_real(self) -> bool:
        """True si está marcado como consumidor final y su condición IVA es CF."""
        return self.condicion_iva == CondicionIVA.CONSUMIDOR_FINAL and self.es_consumidor_final

    @property
    def saldo_cc(self) -> Decimal:
        """Saldo de la cuenta corriente (0.00 si todavía no tiene cuenta)."""
        try:
            return self.cuenta_corriente.saldo or Decimal("0.00")
        except CuentaCorriente.DoesNotExist:
            return Decimal("0.00")

    def clean(self):
        super().clean()

        # Normalización (evita saltar la unicidad con espacios, puntos o guiones)
        self.nombre = (self.nombre or "").strip()
        self.doc_tipo = (self.doc_tipo or "").strip().upper()
        self.doc_numero = (self.doc_numero or "").strip()

        if self.doc_numero and not self.doc_tipo:
            raise ValidationError({"doc_tipo": "Si hay número de documento, el tipo es obligatorio."})
        if self.doc_tipo and not self.doc_numero:
            raise ValidationError({"doc_numero": "Si hay tipo de documento, el número es obligatorio."})

        if self.doc_numero and self.doc_tipo in self.DOCUMENTOS_NUMERICOS:
            self.doc_numero = _solo_digitos(self.doc_numero)
            if not self.doc_numero:
                raise ValidationError({"doc_numero": "El número de documento debe contener dígitos."})

    def save(self, *args, **kwargs):
        # Antes de validar opciones: 'cuit' → 'CUIT'.
        self.doc_tipo = (self.doc_tipo or "").strip().upper()
        # Valida también cuando se guarda desde scripts u ORM, sin formularios.
        self.full_clean()
        return super().save(*args, **kwargs)


class CuentaCorriente(models.Model):
    """Una por cliente. Se crea sola al dar de alta el cliente (ver signals.py)."""

    cliente = models.OneToOneField(Cliente, on_delete=models.PROTECT, related_name="cuenta_corriente")
    saldo = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Deuda del cliente. Nunca es negativa.",
    )
    actualizado_el = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "cuenta corriente"
        verbose_name_plural = "cuentas corrientes"
        constraints = [
            models.CheckConstraint(condition=Q(saldo__gte=0), name="ck_cc_saldo_no_negativo"),
        ]

    def __str__(self):
        return f"CC {self.cliente} = {self.saldo}"


class MovimientoCuentaCorriente(models.Model):
    class Tipo(models.TextChoices):
        DEBITO = "DEBITO", "Débito (aumenta deuda)"
        CREDITO = "CREDITO", "Crédito (pago del cliente)"

    cuenta = models.ForeignKey(CuentaCorriente, on_delete=models.PROTECT, related_name="movimientos")
    fecha = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.DEBITO)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    descripcion = models.CharField(max_length=255, blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cc_movs_creados",
    )
    creado_el = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("-creado_el",)
        indexes = [
            models.Index(fields=["cuenta", "fecha"]),
            models.Index(fields=["tipo"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_cc_mov_monto_positivo"),
        ]
        verbose_name = "movimiento de cuenta corriente"
        verbose_name_plural = "movimientos de cuenta corriente"

    def __str__(self):
        signo = "+" if self.tipo == self.Tipo.DEBITO else "-"
        return f"{self.fecha:%Y-%m-%d} {signo}{self.monto} · {self.cuenta}"

    def clean(self):
        super().clean()

        if self.monto is None or self.monto <= 0:
            raise ValidationError({"monto": "El monto debe ser positivo."})

        # Sólo el personal del taller registra movimientos (nunca un piloto).
        if self.creado_por_id and getattr(self.creado_por, "es_piloto", False):
            raise ValidationError({"creado_por": "Un piloto no puede registrar movimientos de cuenta corriente."})

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(
                "No se pueden editar movimientos existentes; registrá un movimiento contrario."
            )

        self.full_clean()

        with transaction.atomic():
            cta = CuentaCorriente.objects.select_for_update().get(pk=self.cuenta_id)
            deuda = cta.saldo or Decimal("0.00")

            if self.tipo == self.Tipo.DEBITO:
                cta.saldo = deuda + self.monto
            else:
                if self.monto > deuda:
                    raise ValidationError(
                        {"monto": f"El pago ({self.monto}) supera la deuda actual ({deuda})."}
                    )
                cta.saldo = deuda - self.monto

            super().save(*args, **kwargs)
            cta.save(update_fields=["saldo", "actualizado_el"])
