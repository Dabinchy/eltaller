"""Formularios de gestión de campeonatos (moderadores)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms

from .models import Campeonato, Carrera, Categoria, Fecha, Resultado, TipoCarrera


class CampeonatoForm(forms.ModelForm):
    class Meta:
        model = Campeonato
        fields = ("asociacion", "nombre", "temporada", "descripcion", "reglamento_url", "plazo_carga_dias",
                  "puntos_pole", "puntos_vuelta_rapida", "abandonos_suman")
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, asociaciones=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            del self.fields["asociacion"]  # un campeonato no cambia de asociación
        else:
            self.fields["asociacion"].queryset = asociaciones


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ("nombre", "orden")


class PuntosForm(forms.Form):
    tipo = forms.ChoiceField(choices=TipoCarrera.choices, label="Tipo de carrera")
    puntos = forms.CharField(label="Puntos por posición", help_text="Separados por coma, del 1° en adelante. Ej.: 20, 17, 15, 13, 11")

    def clean_puntos(self):
        try:
            valores = [Decimal(v.strip().replace(",", ".")) for v in self.cleaned_data["puntos"].replace(";", ",").split(",") if v.strip()]
        except InvalidOperation:
            raise forms.ValidationError("Escribí sólo números separados por coma.")
        if not valores or any(v < 0 for v in valores):
            raise forms.ValidationError("Cargá al menos un puntaje (sin negativos).")
        return valores


class FechaForm(forms.ModelForm):
    class Meta:
        model = Fecha
        fields = ("numero", "nombre", "circuito", "dia", "categorias", "multiplicador")
        widgets = {"dia": forms.DateInput(attrs={"type": "date"}), "categorias": forms.CheckboxSelectMultiple}
        help_texts = {"categorias": "Si no marcás ninguna, corren todas."}

    def __init__(self, *args, campeonato=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categorias"].queryset = campeonato.categorias.all()
        self.fields["numero"].initial = (campeonato.fechas.count() + 1)


class CarreraForm(forms.ModelForm):
    class Meta:
        model = Carrera
        fields = ("nombre", "tipo", "otorga_bonus")
        labels = {"nombre": "Nueva carrera (ej.: Serie 1)"}


class CorregirResultadoForm(forms.Form):
    condicion = forms.ChoiceField(choices=Resultado.Condicion.choices)
    posicion = forms.IntegerField(min_value=1, required=False)
    pole = forms.BooleanField(required=False)
    vuelta_rapida = forms.BooleanField(required=False)
    motivo = forms.CharField(max_length=255)
