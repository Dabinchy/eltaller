"""Formularios de caja y PIN. Los montos se escriben a la argentina: 1.234,56."""
from __future__ import annotations

from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import TipoMovCaja
from .numeros import parse_decimal_ar


class CampoMonto(forms.CharField):
    def __init__(self, *args, obligatorio=True, **kwargs):
        kwargs.setdefault("widget", forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,00"}))
        super().__init__(*args, required=obligatorio, **kwargs)
        self.obligatorio = obligatorio

    def clean(self, value):
        value = super().clean(value)
        monto = parse_decimal_ar(value, allow_empty=not self.obligatorio)
        if monto is None:
            return Decimal("0.00")
        if monto < 0:
            raise ValidationError("El monto no puede ser negativo.")
        return monto.quantize(Decimal("0.01"))


def _campo_pin(etiqueta="Tu PIN", requerido=True):
    return forms.CharField(
        label=etiqueta, required=requerido, max_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )


class AbrirCajaForm(forms.Form):
    saldo_inicial = CampoMonto(label="Efectivo inicial", obligatorio=False,
                               help_text="Lo que hay en la caja al abrir. Vacío = 0.")
    pin = _campo_pin()


class CerrarCajaForm(forms.Form):
    total_contado = CampoMonto(label="Efectivo contado", help_text="Contá el efectivo de la caja e ingresalo.")
    observacion = forms.CharField(label="Observación", required=False, max_length=255)
    pin = _campo_pin()


class MovimientoCajaForm(forms.Form):
    tipo = forms.ChoiceField(choices=[
        (TipoMovCaja.INGRESO, "Ingreso de efectivo"),
        (TipoMovCaja.EGRESO, "Egreso de efectivo (retiro, pago)"),
        (TipoMovCaja.AJUSTE, "Ajuste (suma)"),
    ])
    monto = CampoMonto(label="Monto")
    motivo = forms.CharField(max_length=255)
    pin = _campo_pin()


class PinForm(forms.Form):
    pin_actual = _campo_pin("PIN actual", requerido=False)
    nuevo_pin = _campo_pin("Nuevo PIN")
    repetir_pin = _campo_pin("Repetí el nuevo PIN")
