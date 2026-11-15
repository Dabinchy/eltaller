"""Formularios de las pantallas del taller (turnos, vehículos, órdenes, ítems, comentarios, fotos)."""
from __future__ import annotations

from django import forms

from core.models import Sucursal
from productos.models import Producto
from taller.models import OrdenItem, OrdenTrabajo, Tecnico, Turno, Vehiculo

FORMATO_FECHA_HORA = "%Y-%m-%dT%H:%M"


def _fecha_hora(**attrs):
    return forms.DateTimeInput(attrs={"type": "datetime-local", **attrs}, format=FORMATO_FECHA_HORA)


class VehiculoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, v):
        return f"{v.identificacion} · {v.marca} {v.modelo} — {v.cliente}"


class ProductoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, p):
        tipo = "Servicio" if p.es_servicio else "Repuesto"
        codigo = f" [{p.codigo_barras or p.sku}]" if (p.codigo_barras or p.sku) else ""
        return f"{p.nombre}{codigo} · {tipo}"


def _sucursales_para(user, es_gerente: bool):
    qs = Sucursal.objects.filter(activa=True)
    if es_gerente:
        return qs
    return qs.filter(pk=user.sucursal_id) if user.sucursal_id else qs.none()


# ============================================================
# Vehículos
# ============================================================

class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ("cliente", "patente", "vin", "marca", "modelo", "anio", "combustible", "km_actual", "activo")
        help_texts = {"patente": "Opcional en autos de carrera. Cargá patente o VIN."}


# ============================================================
# Turnos
# ============================================================

class TurnoForm(forms.ModelForm):
    vehiculo = VehiculoChoiceField(queryset=Vehiculo.objects.filter(activo=True).select_related("cliente"))

    class Meta:
        model = Turno
        fields = ("sucursal", "vehiculo", "inicio", "duracion_min", "motivo")
        widgets = {"inicio": _fecha_hora()}

    def __init__(self, *args, user=None, es_gerente=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicio"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["sucursal"].queryset = _sucursales_para(user, es_gerente)
        if not self.instance.pk and user and user.sucursal_id:
            self.fields["sucursal"].initial = user.sucursal_id

    def clean(self):
        datos = super().clean()
        if datos.get("vehiculo"):
            self.instance.cliente = datos["vehiculo"].cliente  # el turno es del dueño del vehículo
        return datos


# ============================================================
# Órdenes
# ============================================================

class OrdenNuevaForm(forms.ModelForm):
    vehiculo = VehiculoChoiceField(queryset=Vehiculo.objects.filter(activo=True).select_related("cliente"))

    class Meta:
        model = OrdenTrabajo
        fields = ("sucursal", "vehiculo", "tecnico", "km_ingreso", "fecha_prometida", "motivo_cliente")
        widgets = {"fecha_prometida": _fecha_hora(), "motivo_cliente": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user=None, es_gerente=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_prometida"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["sucursal"].queryset = _sucursales_para(user, es_gerente)
        self.fields["tecnico"].queryset = Tecnico.objects.filter(activo=True)
        if user and user.sucursal_id:
            self.fields["sucursal"].initial = user.sucursal_id


class OrdenEditarForm(forms.ModelForm):
    class Meta:
        model = OrdenTrabajo
        fields = ("tecnico", "km_ingreso", "fecha_prometida", "motivo_cliente", "diagnostico")
        widgets = {
            "fecha_prometida": _fecha_hora(),
            "motivo_cliente": forms.Textarea(attrs={"rows": 2}),
            "diagnostico": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_prometida"].input_formats = [FORMATO_FECHA_HORA]
        self.fields["tecnico"].queryset = Tecnico.objects.filter(activo=True) | Tecnico.objects.filter(
            pk=self.instance.tecnico_id
        )


class OrdenDiagnosticoForm(forms.ModelForm):
    """El mecánico sólo escribe el diagnóstico."""

    class Meta:
        model = OrdenTrabajo
        fields = ("diagnostico",)
        widgets = {"diagnostico": forms.Textarea(attrs={"rows": 4})}


class ItemForm(forms.ModelForm):
    producto = ProductoChoiceField(queryset=Producto.objects.filter(activo=True).order_by("tipo", "nombre"))

    class Meta:
        model = OrdenItem
        fields = ("producto", "cantidad", "precio_unitario", "descripcion", "tecnico")
        labels = {"precio_unitario": "Precio unitario (vacío = de lista, 0 = sin cargo)"}

    def __init__(self, *args, puede_precio=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tecnico"].queryset = Tecnico.objects.filter(activo=True)
        if not puede_precio:
            del self.fields["precio_unitario"]  # el mecánico carga ítems; el precio sale de la lista


class ComentarioForm(forms.Form):
    texto = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), max_length=2000)
    visible_piloto = forms.BooleanField(label="Visible para el cliente", required=False)


class ArchivoOrdenForm(forms.Form):
    archivo = forms.FileField()
    titulo = forms.CharField(max_length=120, initial="Foto")
    tipo = forms.ChoiceField(choices=[("FOTO", "Foto"), ("DOCUMENTO", "Documento")])
    visibilidad = forms.ChoiceField(
        choices=[("INTERNO", "Interno del taller"), ("PILOTO", "Compartir con el cliente")],
    )
