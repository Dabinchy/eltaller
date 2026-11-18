"""
Contenido del sitio público, editable desde el admin (sin tocar código).

- Portada: el encabezado grande de cada parte (una por parte).
- Servicio: lo que hace El Taller y cada sección de El Prepa.
- Trabajo (+ FotoTrabajo): trabajos de El Taller y proyectos de El Prepa, con galería.
- Testimonio: opiniones de clientes.
- Publicacion: novedades de cualquiera de las tres partes.
- Consulta: lo que mandan los visitantes por los formularios (presupuesto, contacto, proyecto).

Reglas comunes:
- Nada se ve en la web sin "publicado" (o "publicada").
- Las fotos se limpian (sin GPS ni metadatos), se achican y generan miniatura (core/imagenes.py).
- Los videos van como link de YouTube o Vimeo (no se suben archivos de video).
- Los textos son texto común: los saltos de línea se respetan y no se acepta HTML.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core import imagenes
from portal.models import _slug_unico
from portal.models_contenido import video_embed


class Parte(models.TextChoices):
    TALLER = "taller", "El Taller"
    PREPA = "prepa", "El Prepa"
    CAMPEONATOS = "campeonatos", "Campeonatos"


PARTES_CON_SERVICIOS = [(Parte.TALLER.value, Parte.TALLER.label), (Parte.PREPA.value, Parte.PREPA.label)]

_VALIDADORES_IMAGEN = [FileExtensionValidator(imagenes.EXTENSIONES), imagenes.validar_tamano]
_AYUDA_FOTO = "JPG, PNG o WEBP (hasta 15 MB). Se achica sola y se le borran los datos ocultos (como la ubicación)."
_AYUDA_VIDEO = "Opcional. Link de YouTube o Vimeo (puede ser 'no listado')."
_AYUDA_TEXTO = "Texto común: se respetan los saltos de línea."


def _validar_video(url: str) -> None:
    if url and not video_embed(url):
        raise ValidationError({"video_url": "Pegá un link válido de YouTube o Vimeo."})


def _procesar_foto(instancia, campo: str, campo_mini: str | None = None) -> None:
    """Foto nueva: se limpia, se achica y (si hay campo_mini) se genera la miniatura."""
    foto = getattr(instancia, campo)
    if foto and not foto._committed:
        grande, mini = imagenes.procesar_imagen(foto.file, foto.name)
        foto.save(grande.name, grande, save=False)
        if campo_mini:
            getattr(instancia, campo_mini).save(mini.name, mini, save=False)
    elif not foto and campo_mini and getattr(instancia, campo_mini):
        setattr(instancia, campo_mini, None)


class PublicadosQuerySet(models.QuerySet):
    def publicados(self):
        return self.filter(publicado=True)


# ===========================
# Portada
# ===========================

class Portada(models.Model):
    parte = models.CharField(max_length=12, choices=Parte.choices, unique=True)
    titulo = models.CharField("título", max_length=90)
    subtitulo = models.TextField("subtítulo", max_length=300, blank=True, help_text="Una o dos frases.")
    imagen = models.ImageField(
        "foto de fondo", upload_to="sitio/portadas/", blank=True, validators=_VALIDADORES_IMAGEN,
        help_text="Horizontal, ideal 1920 × 1080. " + _AYUDA_FOTO,
    )
    video_url = models.URLField("link de video", blank=True, help_text=_AYUDA_VIDEO)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("parte",)
        verbose_name = "portada"
        verbose_name_plural = "portadas"

    def __str__(self) -> str:
        return f"Portada de {self.get_parte_display()}"

    @property
    def video_embed_url(self) -> str | None:
        return video_embed(self.video_url)

    def clean(self):
        super().clean()
        _validar_video(self.video_url)

    def save(self, *args, **kwargs):
        _procesar_foto(self, "imagen")
        super().save(*args, **kwargs)


# ===========================
# Servicio
# ===========================

class Servicio(models.Model):
    class Seccion(models.TextChoices):
        COMPETICION = "competicion", "Competición"
        PERSONALIZACION = "personalizacion", "Personalización"
        CLASICOS = "clasicos", "Clásicos"

    # Íconos de Bootstrap Icons que se pueden elegir (así nadie tiene que escribir nombres raros).
    ICONOS = [
        ("bi-tools", "Herramientas"),
        ("bi-wrench-adjustable", "Llave"),
        ("bi-gear", "Engranaje"),
        ("bi-activity", "Diagnóstico"),
        ("bi-cpu", "Electrónica"),
        ("bi-lightning-charge", "Electricidad"),
        ("bi-battery-charging", "Batería"),
        ("bi-thermometer-half", "Refrigeración"),
        ("bi-droplet", "Aceite y fluidos"),
        ("bi-fuel-pump", "Combustible"),
        ("bi-disc", "Frenos"),
        ("bi-arrows-collapse-vertical", "Suspensión"),
        ("bi-speedometer2", "Potencia"),
        ("bi-flag", "Competición"),
        ("bi-trophy", "Trofeo"),
        ("bi-shield-check", "Seguridad"),
        ("bi-brush", "Pintura y estética"),
        ("bi-palette", "Personalización"),
        ("bi-hourglass-split", "Clásicos"),
        ("bi-car-front", "Auto"),
        ("bi-truck", "Traslado"),
        ("bi-clipboard-check", "Revisión"),
        ("bi-calendar-check", "Turnos"),
        ("bi-phone", "Seguimiento"),
    ]

    parte = models.CharField(max_length=12, choices=PARTES_CON_SERVICIOS, default=Parte.TALLER)
    seccion = models.CharField(
        "sección", max_length=16, choices=Seccion.choices, blank=True,
        help_text="Sólo para El Prepa: en qué página aparece.",
    )
    titulo = models.CharField("título", max_length=80)
    icono = models.CharField("ícono", max_length=40, choices=ICONOS, default="bi-tools")
    resumen = models.CharField(max_length=160, help_text="Una línea: se ve en las tarjetas.")
    descripcion = models.TextField("descripción", blank=True, help_text=_AYUDA_TEXTO)
    imagen = models.ImageField(
        "foto", upload_to="sitio/servicios/", blank=True, validators=_VALIDADORES_IMAGEN, help_text=_AYUDA_FOTO,
    )
    miniatura = models.ImageField(upload_to="sitio/servicios/mini/", blank=True, editable=False)
    orden = models.PositiveSmallIntegerField(default=0, help_text="Menor número = aparece antes.")
    publicado = models.BooleanField(default=False)

    objects = PublicadosQuerySet.as_manager()

    class Meta:
        ordering = ("parte", "seccion", "orden", "titulo")
        verbose_name = "servicio"
        verbose_name_plural = "servicios"

    def __str__(self) -> str:
        return self.titulo

    def clean(self):
        super().clean()
        if self.parte == Parte.PREPA and not self.seccion:
            raise ValidationError({"seccion": "Elegí en qué sección de El Prepa aparece."})
        if self.parte == Parte.TALLER and self.seccion:
            raise ValidationError({"seccion": "La sección es sólo para servicios de El Prepa."})

    def save(self, *args, **kwargs):
        _procesar_foto(self, "imagen", "miniatura")
        super().save(*args, **kwargs)


# ===========================
# Trabajos y proyectos
# ===========================

class Trabajo(models.Model):
    """Trabajo de El Taller (autos de calle) o proyecto de El Prepa. La parte sale del tipo."""

    class Tipo(models.TextChoices):
        CALLE = "calle", "Auto de calle (El Taller)"
        COMPETICION = "competicion", "Competición (El Prepa)"
        PERSONALIZACION = "personalizacion", "Personalización (El Prepa)"
        CLASICO = "clasico", "Clásico (El Prepa)"

    tipo = models.CharField(max_length=16, choices=Tipo.choices, default=Tipo.CALLE)
    titulo = models.CharField("título", max_length=100)
    slug = models.SlugField(
        max_length=70, unique=True, blank=True, help_text="Para la dirección de la página. Se completa solo.",
    )
    auto = models.CharField(max_length=100, blank=True, help_text="Ej.: Ford Falcon Sprint 1978.")
    resumen = models.CharField(max_length=200, help_text="Una o dos líneas: se ve en las tarjetas.")
    descripcion = models.TextField("descripción", blank=True, help_text=_AYUDA_TEXTO)
    portada = models.ImageField(
        "foto de portada", upload_to="sitio/trabajos/", blank=True, validators=_VALIDADORES_IMAGEN,
        help_text=_AYUDA_FOTO,
    )
    portada_miniatura = models.ImageField(upload_to="sitio/trabajos/mini/", blank=True, editable=False)
    video_url = models.URLField("link de video", blank=True, help_text=_AYUDA_VIDEO)
    fecha = models.DateField(default=timezone.localdate, help_text="Cuándo se terminó (ordena la lista).")
    destacado = models.BooleanField(default=False, help_text="Aparece en la portada.")
    publicado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = PublicadosQuerySet.as_manager()

    class Meta:
        ordering = ("-fecha", "-id")
        indexes = [models.Index(fields=["tipo", "publicado"])]
        verbose_name = "trabajo o proyecto"
        verbose_name_plural = "trabajos y proyectos"

    def __str__(self) -> str:
        return self.titulo

    @property
    def parte(self) -> str:
        return Parte.TALLER if self.tipo == self.Tipo.CALLE else Parte.PREPA

    @property
    def video_embed_url(self) -> str | None:
        return video_embed(self.video_url)

    def clean(self):
        super().clean()
        _validar_video(self.video_url)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slug_unico(Trabajo, self.titulo, self.pk)
        _procesar_foto(self, "portada", "portada_miniatura")
        super().save(*args, **kwargs)


class FotoTrabajo(models.Model):
    class Etapa(models.TextChoices):
        ANTES = "antes", "Antes"
        PROCESO = "proceso", "Proceso"
        DESPUES = "despues", "Después"

    trabajo = models.ForeignKey(Trabajo, on_delete=models.CASCADE, related_name="fotos")
    imagen = models.ImageField("foto", upload_to="sitio/trabajos/fotos/", validators=_VALIDADORES_IMAGEN)
    miniatura = models.ImageField(upload_to="sitio/trabajos/fotos/mini/", blank=True, editable=False)
    epigrafe = models.CharField("epígrafe", max_length=140, blank=True)
    etapa = models.CharField(max_length=8, choices=Etapa.choices, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("orden", "id")
        verbose_name = "foto"
        verbose_name_plural = "fotos"

    def __str__(self) -> str:
        return self.epigrafe or f"Foto {self.pk or ''}".strip()

    def save(self, *args, **kwargs):
        _procesar_foto(self, "imagen", "miniatura")
        super().save(*args, **kwargs)


# ===========================
# Testimonios
# ===========================

class Testimonio(models.Model):
    parte = models.CharField(max_length=12, choices=PARTES_CON_SERVICIOS, default=Parte.TALLER)
    nombre = models.CharField(max_length=80, help_text="Como quiere aparecer (ej.: 'Marcela G.').")
    detalle = models.CharField(max_length=100, blank=True, help_text="Ej.: 'Fiat 128 · cliente desde 2019'.")
    texto = models.TextField(max_length=600, help_text="Con permiso de la persona.")
    orden = models.PositiveSmallIntegerField(default=0)
    publicado = models.BooleanField(default=False)
    creado = models.DateTimeField(auto_now_add=True)

    objects = PublicadosQuerySet.as_manager()

    class Meta:
        ordering = ("parte", "orden", "-creado")
        verbose_name = "testimonio"
        verbose_name_plural = "testimonios"

    def __str__(self) -> str:
        return f"{self.nombre} ({self.get_parte_display()})"


# ===========================
# Novedades
# ===========================

class PublicacionQuerySet(models.QuerySet):
    def publicadas(self):
        return self.filter(publicada=True, fecha__lte=timezone.now())


class Publicacion(models.Model):
    parte = models.CharField(max_length=12, choices=Parte.choices, default=Parte.TALLER)
    titulo = models.CharField("título", max_length=120)
    slug = models.SlugField(
        max_length=70, unique=True, blank=True, help_text="Para la dirección de la página. Se completa solo.",
    )
    resumen = models.CharField(max_length=300, help_text="Se ve en la lista de novedades.")
    cuerpo = models.TextField("texto", blank=True, help_text=_AYUDA_TEXTO)
    portada = models.ImageField(
        "foto de portada", upload_to="sitio/publicaciones/", blank=True, validators=_VALIDADORES_IMAGEN,
        help_text=_AYUDA_FOTO,
    )
    portada_miniatura = models.ImageField(upload_to="sitio/publicaciones/mini/", blank=True, editable=False)
    video_url = models.URLField("link de video", blank=True, help_text=_AYUDA_VIDEO)
    fecha = models.DateTimeField(
        default=timezone.now, help_text="Con una fecha futura, aparece recién ese día.",
    )
    publicada = models.BooleanField(default=False)
    actualizada = models.DateTimeField(auto_now=True)

    objects = PublicacionQuerySet.as_manager()

    class Meta:
        ordering = ("-fecha", "-id")
        indexes = [models.Index(fields=["publicada", "fecha"])]
        verbose_name = "novedad"
        verbose_name_plural = "novedades"

    def __str__(self) -> str:
        return self.titulo

    @property
    def video_embed_url(self) -> str | None:
        return video_embed(self.video_url)

    def clean(self):
        super().clean()
        _validar_video(self.video_url)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slug_unico(Publicacion, self.titulo, self.pk)
        _procesar_foto(self, "portada", "portada_miniatura")
        super().save(*args, **kwargs)


# ===========================
# Consultas de visitantes
# ===========================

class Consulta(models.Model):
    class Tipo(models.TextChoices):
        PRESUPUESTO = "presupuesto", "Pedido de presupuesto"
        CONTACTO = "contacto", "Contacto"
        PROYECTO = "proyecto", "Proyecto (El Prepa)"

    class Estado(models.TextChoices):
        NUEVA = "nueva", "Nueva"
        RESPONDIDA = "respondida", "Respondida"
        ARCHIVADA = "archivada", "Archivada"

    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    parte = models.CharField(max_length=12, choices=Parte.choices, default=Parte.TALLER)
    nombre = models.CharField(max_length=80)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    email = models.EmailField(blank=True)
    vehiculo = models.CharField("vehículo", max_length=100, blank=True)
    mensaje = models.TextField(max_length=2000)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.NUEVA)
    notas = models.TextField("notas internas", blank=True, help_text="Sólo las ve el personal.")
    creada = models.DateTimeField(auto_now_add=True)
    respondida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        editable=False,
    )
    respondida_el = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("-creada",)
        indexes = [models.Index(fields=["estado", "creada"])]
        constraints = [
            models.CheckConstraint(
                condition=~Q(telefono="") | ~Q(email=""),
                name="ck_consulta_con_contacto",
                violation_error_message="Dejá un teléfono o un email para poder responderte.",
            ),
        ]
        verbose_name = "consulta"
        verbose_name_plural = "consultas"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} de {self.nombre}"

    def marcar(self, estado: str, usuario=None) -> None:
        """Cambia el estado; al marcarla respondida guarda quién y cuándo."""
        self.estado = estado
        if estado == self.Estado.RESPONDIDA:
            self.respondida_por = usuario
            self.respondida_el = timezone.now()
        self.save(update_fields=["estado", "respondida_por", "respondida_el"])
