"""
Formularios públicos del sitio: pedido de presupuesto, contacto y consulta de proyecto (El Prepa).

Todos guardan una Consulta. Anti-spam: un campo trampa invisible ("web") y un límite de envíos
por conexión (ver views.guardar_consulta).
"""
from __future__ import annotations

from django import forms

from .models import Consulta


class ConsultaForm(forms.ModelForm):
    # Campo trampa: invisible para las personas; los robots lo completan.
    web = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    class Meta:
        model = Consulta
        fields = ("nombre", "telefono", "email", "vehiculo", "mensaje")
        labels = {
            "nombre": "Tu nombre",
            "telefono": "Teléfono o WhatsApp",
            "email": "Email",
            "vehiculo": "Vehículo",
            "mensaje": "¿En qué te ayudamos?",
        }
        help_texts = {"email": "Dejá un teléfono o un email para poder responderte."}
        widgets = {
            "nombre": forms.TextInput(attrs={"autocomplete": "name"}),
            "telefono": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "vehiculo": forms.TextInput(attrs={"placeholder": "Marca, modelo y año"}),
            "mensaje": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, tipo: str, parte: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tipo = tipo
        self.instance.parte = parte
        if tipo == Consulta.Tipo.CONTACTO:
            del self.fields["vehiculo"]
            self.fields["mensaje"].label = "Mensaje"
        elif tipo == Consulta.Tipo.PROYECTO:
            self.fields["vehiculo"].label = "Auto"
            self.fields["mensaje"].label = "Contanos tu proyecto"
        else:
            self.fields["vehiculo"].required = True
            self.fields["mensaje"].label = "¿Qué necesita tu vehículo?"
            self.fields["mensaje"].widget.attrs["placeholder"] = "Ej.: service de los 60.000 km, ruido en el tren delantero…"

    def clean(self):
        datos = super().clean()
        if not datos.get("telefono") and not datos.get("email") and "telefono" not in self.errors:
            self.add_error("telefono", "Dejá un teléfono o un email para poder responderte.")
        return datos

    @property
    def es_robot(self) -> bool:
        return bool(self.cleaned_data.get("web"))
