"""
Formularios del contenido del sitio público en el panel (/panel/sitio/).

Usan las mismas reglas que el admin (validaciones del modelo, fotos que se limpian y achican,
videos sólo de YouTube o Vimeo). Las fotos se cambian con un campo común y se quitan con la
casilla "Quitar foto" (en lugar del widget del admin).
"""
from __future__ import annotations

from django import forms
from django.core.validators import FileExtensionValidator

from core import imagenes
from sitio.models import Consulta, FotoTrabajo, Portada, Publicacion, Servicio, Testimonio, Trabajo

_FORMATO_FECHA_HORA = "%Y-%m-%dT%H:%M"


class _Disposicion:
    """Reparte los campos en dos columnas: datos (izquierda) y foto/publicación (columna lateral)."""

    lateral: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Textos largos más altos; resúmenes y frases, de 3 renglones (Django trae 10 por defecto).
        for nombre, campo in self.fields.items():
            if isinstance(campo.widget, forms.Textarea):
                campo.widget.attrs["rows"] = 8 if nombre in ("cuerpo", "descripcion") else 3

    def campos_principales(self):
        return [c for c in self.visible_fields() if c.name not in self._lateral_total()]

    def campos_laterales(self):
        return [c for c in self.visible_fields() if c.name in self._lateral_total()]

    def _lateral_total(self):
        fotos = getattr(self, "campos_foto", ())
        return set(self.lateral) | {f"quitar_{c}" for c in fotos}


class _ConFotos(_Disposicion, forms.ModelForm):
    """Agrega "Quitar foto" a cada campo de imagen opcional que ya tiene una foto cargada."""

    campos_foto: tuple[str, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.campos_foto:
            if campo not in self.fields:
                continue
            self.fields[campo].widget = forms.FileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})
            if getattr(self.instance, campo) and not self.fields[campo].required:
                self.fields[f"quitar_{campo}"] = forms.BooleanField(label="Quitar foto", required=False)

    def fotos_actuales(self) -> dict:
        """{campo: url} de las fotos ya cargadas (para mostrar la vista previa)."""
        out = {}
        for campo in self.campos_foto:
            archivo = getattr(self.instance, campo, None)
            if archivo:
                mini = getattr(self.instance, f"{campo}_miniatura", None) or getattr(self.instance, "miniatura", None)
                out[campo] = (mini or archivo).url
        return out

    def save(self, commit=True):
        obj = super().save(commit=False)
        for campo in self.campos_foto:
            if self.cleaned_data.get(f"quitar_{campo}") and not self.files.get(self.add_prefix(campo)):
                setattr(obj, campo, None)
        if commit:
            obj.save()
        return obj


class PublicacionForm(_ConFotos):
    campos_foto = ("portada",)
    lateral = ("portada", "video_url", "fecha", "publicada")

    class Meta:
        model = Publicacion
        fields = ("parte", "titulo", "resumen", "cuerpo", "portada", "video_url", "fecha", "publicada")
        widgets = {
            "resumen": forms.Textarea,
            "fecha": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=_FORMATO_FECHA_HORA),
        }
        labels = {"publicada": "Publicada (se ve en la web desde la fecha indicada)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha"].input_formats = [_FORMATO_FECHA_HORA, "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]


class TrabajoForm(_ConFotos):
    campos_foto = ("portada",)
    lateral = ("portada", "video_url", "fecha", "destacado", "publicado")

    class Meta:
        model = Trabajo
        fields = ("tipo", "titulo", "auto", "resumen", "descripcion", "portada", "video_url", "fecha",
                  "destacado", "publicado")
        widgets = {"resumen": forms.Textarea, "fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}
        labels = {"destacado": "Destacado (aparece en la portada)", "publicado": "Publicado (se ve en la web)"}


class ServicioForm(_ConFotos):
    campos_foto = ("imagen",)
    lateral = ("imagen", "icono", "publicado")

    class Meta:
        model = Servicio
        fields = ("parte", "seccion", "titulo", "icono", "resumen", "descripcion", "imagen", "publicado")
        labels = {"publicado": "Publicado (se ve en la web)"}


class TestimonioForm(_Disposicion, forms.ModelForm):
    lateral = ("publicado",)

    class Meta:
        model = Testimonio
        fields = ("parte", "nombre", "detalle", "texto", "publicado")
        widgets = {"texto": forms.Textarea(attrs={"rows": 4})}
        labels = {"publicado": "Publicado (se ve en la web)"}


class PortadaForm(_ConFotos):
    campos_foto = ("imagen",)
    lateral = ("imagen", "video_url")

    class Meta:
        model = Portada
        fields = ("titulo", "subtitulo", "imagen", "video_url")
        widgets = {"subtitulo": forms.Textarea(attrs={"rows": 3})}


# ---------------- Galería de un trabajo ----------------

class _VariasFotos(forms.ClearableFileInput):
    allow_multiple_selected = True


class _CampoVariasFotos(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", _VariasFotos(attrs={"accept": "image/jpeg,image/png,image/webp", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        archivos = data if isinstance(data, (list, tuple)) else [data]
        archivos = [a for a in archivos if a]
        if not archivos:
            raise forms.ValidationError("Elegí al menos una foto.")
        if len(archivos) > 30:
            raise forms.ValidationError("Hasta 30 fotos por vez.")
        validar_ext = FileExtensionValidator(imagenes.EXTENSIONES)
        for archivo in archivos:
            super().clean(archivo, initial)
            try:
                validar_ext(archivo)
                imagenes.validar_tamano(archivo)
            except forms.ValidationError as e:
                raise forms.ValidationError(f"{archivo.name}: {' '.join(e.messages)}")
        return archivos


class SubirFotosForm(forms.Form):
    fotos = _CampoVariasFotos(label="Fotos", help_text="Podés elegir varias a la vez. JPG, PNG o WEBP (hasta 15 MB cada una).")
    etapa = forms.ChoiceField(
        label="Etapa", required=False, choices=[("", "Sin etapa")] + list(FotoTrabajo.Etapa.choices),
        help_text="Se puede cambiar después en cada foto.",
    )


class FotoForm(forms.ModelForm):
    class Meta:
        model = FotoTrabajo
        fields = ("epigrafe", "etapa")


class ConsultaNotasForm(forms.ModelForm):
    class Meta:
        model = Consulta
        fields = ("notas",)
        widgets = {"notas": forms.Textarea(attrs={"rows": 4, "placeholder": "Ej.: le pasé el presupuesto por WhatsApp."})}
