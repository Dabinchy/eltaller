"""Formularios de ventas: ítems de mostrador, cliente, cobro y anulación."""
from __future__ import annotations

from django import forms

from clientes.models import Cliente
from core.forms_caja import CampoMonto
from productos.models import Producto

from .forms_taller import ProductoChoiceField


class ItemVentaForm(forms.Form):
    producto = ProductoChoiceField(queryset=Producto.objects.filter(activo=True, vendible=True).order_by("tipo", "nombre"))
    cantidad = forms.DecimalField(min_value=0.001, decimal_places=3, initial=1)
    precio_unitario = CampoMonto(label="Precio unitario (vacío = de lista)", obligatorio=False)

    def __init__(self, *args, puede_precio=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not puede_precio:
            del self.fields["precio_unitario"]

    def clean_precio_unitario(self):
        # CampoMonto devuelve 0 si está vacío: acá vacío significa "precio de lista".
        crudo = (self.data.get(self.add_prefix("precio_unitario")) or "").strip()
        return self.cleaned_data["precio_unitario"] if crudo else None


class ClienteVentaForm(forms.Form):
    cliente = forms.ModelChoiceField(
        queryset=Cliente.objects.filter(activo=True).order_by("nombre"), required=False,
        empty_label="Consumidor final (sin cliente)",
    )


class CobroForm(forms.Form):
    monto_efectivo = CampoMonto(label="Efectivo", obligatorio=False,
                                help_text="Lo que queda en la caja (ya descontado el vuelto).")
    monto_tarjeta = CampoMonto(label="Tarjeta", obligatorio=False)
    monto_transferencia = CampoMonto(label="Transferencia", obligatorio=False)
    monto_ctacte = CampoMonto(label="Cuenta corriente", obligatorio=False,
                              help_text="Requiere cliente con crédito disponible.")


class AnularVentaForm(forms.Form):
    pin = forms.CharField(label="PIN del gerente", max_length=6,
                          widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}))
