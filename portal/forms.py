"""
Formularios del portal. Siempre con lista cerrada de campos: el piloto nunca puede tocar
aprobaciones, cuota, consentimientos, usuario, patente, VIN ni km.
"""
from __future__ import annotations

from django import forms

from .models import Asociacion, PerfilPiloto
from .models_contenido import Archivo, Auto, Palmares


class RegistroForm(forms.Form):
    nombre = forms.CharField(max_length=60)
    apellido = forms.CharField(max_length=60)
    dni = forms.CharField(label="DNI / documento", max_length=15, help_text="Es privado: no se muestra en la web.")
    email = forms.EmailField()
    username = forms.CharField(label="Usuario", max_length=60, help_text="Con este usuario vas a ingresar.")
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repetí la contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    soy_piloto = forms.BooleanField(label="Soy piloto", required=False)
    asociacion = forms.ModelChoiceField(
        label="Asociación en la que corro", queryset=Asociacion.objects.filter(activa=True), required=False,
    )
    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento", required=False, widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Privada. Sirve para saber si sos menor (los menores necesitan permiso del tutor para publicar).",
    )
    licencia = forms.CharField(label="Licencia (opcional)", max_length=40, required=False)

    soy_cliente = forms.BooleanField(label="Soy cliente del taller", required=False)
    nota_cliente = forms.CharField(
        label="¿Cómo te identificamos?", required=False, max_length=300,
        widget=forms.Textarea(attrs={"rows": 2}), help_text="Ej.: 'Traje el Fiesta rojo en marzo'.",
    )

    # Campo trampa: invisible para las personas; los robots lo completan.
    web = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean(self):
        datos = super().clean()
        if datos.get("password") and datos.get("password") != datos.get("password2"):
            self.add_error("password2", "Las contraseñas no coinciden.")
        if not datos.get("soy_piloto") and not datos.get("soy_cliente"):
            raise forms.ValidationError("Marcá si sos piloto, cliente del taller o las dos cosas.")
        if datos.get("soy_piloto") and not datos.get("asociacion"):
            self.add_error("asociacion", "Elegí tu asociación.")
        return datos


class PerfilForm(forms.ModelForm):
    class Meta:
        model = PerfilPiloto
        fields = ("nombre_publico", "foto", "bio", "instagram", "sitio_web", "perfil_publico",
                  "licencia", "fecha_nacimiento", "telefono")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
            "fecha_nacimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "foto": forms.FileInput,
        }
        labels = {"perfil_publico": "Mostrar mi perfil en la web (después de la aprobación)"}
        help_texts = {
            "instagram": "Tu usuario o el link a tu perfil.",
            "foto": "JPG, PNG o WEBP. Se le borra la ubicación y se achica.",
        }


class PalmaresForm(forms.ModelForm):
    class Meta:
        model = Palmares
        fields = ("anio", "campeonato", "categoria", "resultado", "detalle")


class AutoForm(forms.ModelForm):
    class Meta:
        model = Auto
        fields = ("marca", "modelo", "anio", "numero_competicion", "categoria", "descripcion")
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 4})}


class InvitarForm(forms.Form):
    piloto = forms.CharField(
        label="Piloto a invitar", max_length=80,
        help_text="Su usuario o su nombre público. Tiene que tener la cuenta aprobada.",
    )


class ArchivoForm(forms.Form):
    """Para el piloto: nunca puede elegir 'interno del taller'."""

    tipo = forms.ChoiceField(choices=[
        (Archivo.Tipo.FOTO, "Foto"), (Archivo.Tipo.VIDEO, "Video (link de YouTube o Vimeo)"),
        (Archivo.Tipo.SETUP, "Setup"), (Archivo.Tipo.TELEMETRIA, "Telemetría"),
        (Archivo.Tipo.DOCUMENTO, "Documento"),
    ])
    titulo = forms.CharField(label="Título", max_length=120)
    descripcion = forms.CharField(label="Descripción", max_length=500, required=False)
    visibilidad = forms.ChoiceField(choices=[
        (Archivo.Visibilidad.PRIVADO, "Privado (sólo los pilotos)"),
        (Archivo.Visibilidad.PILOTO, "Compartido con el taller"),
        (Archivo.Visibilidad.PUBLICO, "Público (después de la aprobación)"),
    ], initial=Archivo.Visibilidad.PRIVADO)
    archivo = forms.FileField(required=False)
    url_video = forms.URLField(label="Link del video", required=False)

    def clean(self):
        datos = super().clean()
        if datos.get("tipo") == Archivo.Tipo.VIDEO:
            if not datos.get("url_video"):
                self.add_error("url_video", "Pegá el link del video.")
            datos["archivo"] = None
        else:
            if not datos.get("archivo"):
                self.add_error("archivo", "Elegí el archivo.")
            datos["url_video"] = ""
        return datos
