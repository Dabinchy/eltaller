"""Formularios de productos, stock, precios, clientes, proveedores y compras."""
from __future__ import annotations

from django import forms

from clientes.models import Cliente
from compras.models import Compra, CompraDetalle, Proveedor
from core.forms_caja import CampoMonto
from productos.models import ListaPrecio, PrecioProducto, Producto

from .forms_taller import FORMATO_FECHA_HORA, ProductoChoiceField, _fecha_hora, _sucursales_para


# ============================================================
# Productos, stock y precios
# ============================================================

class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = ("tipo", "nombre", "categoria", "marca", "codigo_barras", "sku", "controla_stock",
                  "unidad_medida", "cantidad_unidad", "precio_base", "iva_tasa", "precio_incluye_impuestos",
                  "imagen", "vendible", "activo")
        labels = {"precio_base": "Precio base (si no hay lista de precios)"}
        help_texts = {"controla_stock": "Los servicios (mano de obra) nunca controlan stock."}

    def __init__(self, *args, puede_precio=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not puede_precio:
            del self.fields["precio_base"]


class AjusteStockForm(forms.Form):
    operacion = forms.ChoiceField(choices=[("SUMAR", "Sumar (ingreso, inventario)"), ("RESTAR", "Restar (rotura, pérdida)")])
    cantidad = forms.DecimalField(min_value=0.001, decimal_places=3)
    motivo = forms.CharField(max_length=200)


class StockMinimoForm(forms.Form):
    stock_minimo = forms.DecimalField(min_value=0, decimal_places=3, label="Stock mínimo")


class PrecioForm(forms.ModelForm):
    producto = ProductoChoiceField(queryset=Producto.objects.filter(activo=True).order_by("tipo", "nombre"))

    class Meta:
        model = PrecioProducto
        fields = ("lista", "producto", "tipo", "precio", "desde", "hasta")
        widgets = {"desde": _fecha_hora(), "hasta": _fecha_hora()}
        help_texts = {"hasta": "Vacío = vigente hasta nuevo aviso. Las promociones tienen que tener fin."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["desde"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["hasta"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["lista"].queryset = ListaPrecio.objects.all()


class ListaPrecioForm(forms.ModelForm):
    class Meta:
        model = ListaPrecio
        fields = ("nombre", "es_default")


# ============================================================
# Clientes
# ============================================================

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ("nombre", "doc_tipo", "doc_numero", "telefono", "email", "direccion", "limite_credito", "activo")
        help_texts = {"limite_credito": "0 = sin crédito (no se le puede fiar)."}


class PagoCuentaForm(forms.Form):
    monto = CampoMonto(label="Monto que paga")
    medio = forms.ChoiceField(choices=[("EFECTIVO", "Efectivo (entra a la caja)"), ("TARJETA", "Tarjeta"),
                                       ("TRANSFERENCIA", "Transferencia")])
    nota = forms.CharField(max_length=120, required=False)


# ============================================================
# Compras
# ============================================================

class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = ("nombre", "documento", "telefono", "email", "direccion", "activo")


class CompraForm(forms.ModelForm):
    class Meta:
        model = Compra
        fields = ("proveedor", "sucursal", "fecha", "observaciones", "documento_adjunto")
        widgets = {"fecha": _fecha_hora(), "observaciones": forms.Textarea(attrs={"rows": 2}),
                   "documento_adjunto": forms.FileInput}

    def __init__(self, *args, user=None, es_gerente=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["proveedor"].queryset = Proveedor.objects.filter(activo=True)
        self.fields["sucursal"].queryset = _sucursales_para(user, es_gerente)
        if user and user.sucursal_id and not self.instance.pk:
            self.fields["sucursal"].initial = user.sucursal_id


class CompraItemForm(forms.ModelForm):
    producto = ProductoChoiceField(queryset=Producto.objects.filter(activo=True).order_by("tipo", "nombre"))

    class Meta:
        model = CompraDetalle
        fields = ("producto", "cantidad", "costo_unitario", "iva_tasa")
        labels = {"costo_unitario": "Costo unitario sin IVA"}
