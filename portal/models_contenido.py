"""
Portal de pilotos: contenido (autos, pilotos por auto, palmarés).

Las reglas (quién publica, invita o aprueba) están en portal/servicios_contenido.py.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

from core import imagenes
from core.almacenamiento import almacenamiento_privado

from .models import Membresia, PerfilPiloto, _slug_unico


def _anio_maximo() -> int:
    return timezone.now().year + 1


# ===========================
# Auto (presentación del piloto)
# ===========================

class Auto(models.Model):
    # Si cambian después de aprobado, el auto se marca para revisión.
    CAMPOS_PUBLICOS = ("marca", "modelo", "anio", "numero_competicion", "categoria", "descripcion", "portada_id")

    marca = models.CharField(max_length=60)
    modelo = models.CharField(max_length=80)
    anio = models.PositiveSmallIntegerField("año", null=True, blank=True, validators=[MinValueValidator(1900)])
    numero_competicion = models.CharField("número", max_length=10, blank=True)
    categoria = models.CharField("categoría", max_length=80, blank=True)
    descripcion = models.TextField("descripción", blank=True, validators=[MaxLengthValidator(3000)])
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    portada = models.ForeignKey(
        "Archivo", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Una de las fotos de este auto.",
    )

    publicado = models.BooleanField(default=False, help_text="Lo decide el piloto principal.")
    aprobado = models.BooleanField(default=False, editable=False)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    aprobado_el = models.DateTimeField(null=True, blank=True, editable=False)
    cambio_tras_aprobacion = models.BooleanField("cambió después de aprobado", default=False, editable=False)

    # Ficha operativa en el taller (sólo la vincula el personal).
    vehiculo_taller = models.OneToOneField(
        "taller.Vehiculo", on_delete=models.SET_NULL, null=True, blank=True, related_name="auto_portal",
        editable=False,
    )

    activo = models.BooleanField(default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("marca", "modelo")
        verbose_name = "auto"
        verbose_name_plural = "autos"

    def __str__(self) -> str:
        numero = f" #{self.numero_competicion}" if self.numero_competicion else ""
        return f"{self.marca} {self.modelo}{numero}"

    # ------------ consultas ------------

    def pilotos_aceptados(self):
        return PerfilPiloto.objects.filter(autos__auto=self, autos__estado=PilotoAuto.Estado.ACEPTADA)

    @property
    def principal(self) -> PerfilPiloto | None:
        pa = self.pilotos.filter(principal=True).select_related("piloto").first()
        return pa.piloto if pa else None

    @property
    def visible_en_web(self) -> bool:
        principal = self.principal
        return bool(
            self.activo and self.publicado and self.aprobado and principal
            and principal.usuario.is_active and principal.asociaciones_aprobadas().exists()
        )

    # ------------ guardado ------------

    def clean(self):
        super().clean()
        if self.anio and self.anio > _anio_maximo():
            raise ValidationError({"anio": f"El año no puede ser mayor que {_anio_maximo()}."})
        if self.portada_id and (self.portada.auto_id != self.pk or self.portada.tipo != Archivo.Tipo.FOTO):
            raise ValidationError({"portada": "La portada tiene que ser una foto de este auto."})

    def _cambiaron_datos_publicos(self) -> bool:
        anterior = Auto.objects.filter(pk=self.pk).values(*self.CAMPOS_PUBLICOS).first()
        return bool(anterior) and any(
            str(anterior[c] or "") != str(getattr(self, c) or "") for c in self.CAMPOS_PUBLICOS
        )

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields"):
            return super().save(*args, **kwargs)
        self.full_clean()
        if not self.slug:
            self.slug = _slug_unico(Auto, f"{self.marca} {self.modelo} {self.numero_competicion}", self.pk)
        if self.pk and self.aprobado and self._cambiaron_datos_publicos():
            self.cambio_tras_aprobacion = True
        super().save(*args, **kwargs)


class PilotoAuto(models.Model):
    """Quién maneja cada auto. Un solo principal; los demás entran por invitación aceptada."""

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Invitación pendiente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    auto = models.ForeignKey(Auto, on_delete=models.CASCADE, related_name="pilotos")
    piloto = models.ForeignKey(PerfilPiloto, on_delete=models.CASCADE, related_name="autos")
    principal = models.BooleanField(default=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    invitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    respondida_el = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-principal", "created_at")
        constraints = [
            models.UniqueConstraint(fields=["auto", "piloto"], name="uq_pilotoauto_auto_piloto"),
            models.UniqueConstraint(
                fields=["auto"], condition=Q(principal=True), name="uq_pilotoauto_un_principal",
                violation_error_message="El auto ya tiene piloto principal.",
            ),
            models.CheckConstraint(
                condition=Q(principal=False) | Q(estado="ACEPTADA"),
                name="ck_pilotoauto_principal_aceptado",
            ),
        ]
        verbose_name = "piloto del auto"
        verbose_name_plural = "pilotos del auto"

    def __str__(self) -> str:
        rol = "principal" if self.principal else self.get_estado_display().lower()
        return f"{self.piloto} en {self.auto} ({rol})"


# ===========================
# Palmarés
# ===========================

class Palmares(models.Model):
    piloto = models.ForeignKey(PerfilPiloto, on_delete=models.CASCADE, related_name="palmares")
    anio = models.PositiveSmallIntegerField("año", validators=[MinValueValidator(1950)])
    campeonato = models.CharField(max_length=120)
    categoria = models.CharField("categoría", max_length=80, blank=True)
    resultado = models.CharField(max_length=40, help_text="Ej.: 'Campeón', '3°', 'Ganador fecha 5'.")
    detalle = models.CharField(max_length=255, blank=True)
    posicion = models.PositiveSmallIntegerField("orden", default=0, validators=[MaxValueValidator(999)])

    class Meta:
        ordering = ("piloto", "-anio", "posicion", "id")
        verbose_name = "palmarés"
        verbose_name_plural = "palmarés"

    def __str__(self) -> str:
        return f"{self.anio} · {self.campeonato} · {self.resultado}"

    def clean(self):
        super().clean()
        if self.anio and self.anio > _anio_maximo():
            raise ValidationError({"anio": f"El año no puede ser mayor que {_anio_maximo()}."})

    def _marcar_perfil(self) -> None:
        """El palmarés es parte del perfil público: un cambio lo manda a revisión."""
        PerfilPiloto.objects.filter(pk=self.piloto_id, aprobado=True).update(cambio_tras_aprobacion=True)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        self._marcar_perfil()

    def delete(self, *args, **kwargs):
        resultado = super().delete(*args, **kwargs)
        self._marcar_perfil()
        return resultado


# ===========================
# Archivos
# ===========================

def _ruta_archivo(instance: "Archivo", filename: str) -> str:
    """pilotos/<usuario>/<tipo>/<uuid>_<nombre>: nombre impredecible y sin caracteres raros."""
    nombre = get_valid_filename(Path(filename).name)[-80:] or "archivo"
    dueno = instance.subido_por_id or "taller"
    return f"archivos/{dueno}/{instance.tipo.lower()}/{uuid.uuid4().hex[:12]}_{nombre}"


_VIDEO_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "vimeo.com", "www.vimeo.com"}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")


def video_embed(url: str) -> str | None:
    """Devuelve la URL para incrustar el video (YouTube o Vimeo) o None si el link no es válido."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or host not in _VIDEO_HOSTS:
        return None
    if "vimeo" in host:
        vid = p.path.strip("/").split("/")[0]
        return f"https://player.vimeo.com/video/{vid}" if vid.isdigit() else None
    if host == "youtu.be":
        vid = p.path.strip("/")
    elif p.path.startswith(("/shorts/", "/embed/", "/live/")):
        vid = p.path.split("/")[2] if len(p.path.split("/")) > 2 else ""
    else:
        vid = parse_qs(p.query).get("v", [""])[0]
    return f"https://www.youtube-nocookie.com/embed/{vid}" if _YOUTUBE_ID.match(vid or "") else None


class Archivo(models.Model):
    class Tipo(models.TextChoices):
        FOTO = "FOTO", "Foto"
        VIDEO = "VIDEO", "Video (link)"
        SETUP = "SETUP", "Setup"
        TELEMETRIA = "TELEMETRIA", "Telemetría"
        DOCUMENTO = "DOCUMENTO", "Documento"

    class Visibilidad(models.TextChoices):
        PRIVADO = "PRIVADO", "Privado (sólo los pilotos)"
        PILOTO = "PILOTO", "Pilotos y taller"
        INTERNO = "INTERNO", "Interno del taller"
        PUBLICO = "PUBLICO", "Público (con aprobación)"

    # Formatos y tamaño máximo (MB) por tipo.
    FORMATOS = {
        Tipo.FOTO: (imagenes.EXTENSIONES, imagenes.MAX_MB),
        Tipo.SETUP: (["pdf", "txt", "csv", "xlsx", "json", "zip"], 10),
        Tipo.TELEMETRIA: (["csv", "ld", "ldx", "xrk", "xrz", "drk", "zip"], 50),
        Tipo.DOCUMENTO: (["pdf", "jpg", "jpeg", "png"], 10),
    }

    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="archivos_subidos", editable=False,
    )
    piloto = models.ForeignKey(PerfilPiloto, on_delete=models.CASCADE, null=True, blank=True, related_name="archivos")
    auto = models.ForeignKey(Auto, on_delete=models.CASCADE, null=True, blank=True, related_name="archivos")
    orden = models.ForeignKey(
        "taller.OrdenTrabajo", on_delete=models.CASCADE, null=True, blank=True, related_name="archivos",
    )

    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    visibilidad = models.CharField(max_length=10, choices=Visibilidad.choices, default=Visibilidad.PRIVADO)
    titulo = models.CharField("título", max_length=120)
    descripcion = models.CharField("descripción", max_length=500, blank=True)

    archivo = models.FileField(upload_to=_ruta_archivo, storage=almacenamiento_privado, null=True, blank=True)
    miniatura = models.ImageField(
        upload_to=_ruta_archivo, storage=almacenamiento_privado, null=True, blank=True, editable=False,
    )
    url_video = models.URLField("link del video", blank=True, help_text="YouTube o Vimeo.")
    tamano_bytes = models.PositiveBigIntegerField("tamaño (bytes)", default=0, editable=False)

    destacado = models.BooleanField(default=False)
    posicion = models.PositiveSmallIntegerField("orden", default=0)

    aprobado = models.BooleanField(default=False, editable=False)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    aprobado_el = models.DateTimeField(null=True, blank=True, editable=False)
    subido_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-destacado", "posicion", "-subido_el")
        constraints = [
            models.CheckConstraint(
                condition=Q(piloto__isnull=False) | Q(auto__isnull=False) | Q(orden__isnull=False),
                name="ck_archivo_con_destino",
                violation_error_message="El archivo tiene que pertenecer a un auto, una orden o un piloto.",
            ),
            models.CheckConstraint(
                condition=~Q(visibilidad="INTERNO") | Q(orden__isnull=False),
                name="ck_archivo_interno_solo_en_ordenes",
            ),
            models.CheckConstraint(
                condition=Q(orden__isnull=True) | Q(visibilidad__in=["INTERNO", "PILOTO"]),
                name="ck_archivo_orden_interno_o_piloto",
            ),
            models.CheckConstraint(
                condition=~Q(tipo="VIDEO") | ~Q(url_video=""),
                name="ck_archivo_video_con_link",
            ),
        ]
        indexes = [models.Index(fields=["subido_por"]), models.Index(fields=["visibilidad", "aprobado"])]
        verbose_name = "archivo"
        verbose_name_plural = "archivos"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()}: {self.titulo}"

    # ------------ consultas ------------

    @property
    def es_imagen(self) -> bool:
        return self.tipo == self.Tipo.FOTO

    @property
    def nombre_archivo(self) -> str:
        return Path(self.archivo.name).name.split("_", 1)[-1] if self.archivo else ""

    @property
    def video_embed_url(self) -> str | None:
        return video_embed(self.url_video) if self.tipo == self.Tipo.VIDEO else None

    @property
    def visible_en_web(self) -> bool:
        if self.visibilidad != self.Visibilidad.PUBLICO or not self.aprobado:
            return False
        if self.auto_id:
            return self.auto.visible_en_web
        return bool(self.piloto_id and self.piloto.visible_en_web)

    # ------------ validación y guardado ------------

    def clean(self):
        super().clean()
        if self.tipo == self.Tipo.VIDEO:
            if not video_embed(self.url_video):
                raise ValidationError({"url_video": "Pegá un link válido de YouTube o Vimeo."})
            if self.archivo:
                raise ValidationError({"archivo": "Un video se carga como link, no como archivo."})
            return
        if not self.archivo:
            raise ValidationError({"archivo": "Elegí el archivo."})
        if self.url_video:
            raise ValidationError({"url_video": "El link de video sólo va en el tipo Video."})
        if not self.archivo._committed:  # archivo nuevo: formato y tamaño según el tipo
            extensiones, max_mb = self.FORMATOS[self.tipo]
            ext = Path(self.archivo.name).suffix.lower().lstrip(".")
            if ext not in extensiones:
                raise ValidationError({"archivo": f"Formato no permitido para {self.get_tipo_display()}: "
                                                  f"{', '.join(extensiones)}."})
            if self.archivo.size > max_mb * 1024 * 1024:
                raise ValidationError({"archivo": f"El archivo no puede superar {max_mb} MB."})

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields"):
            return super().save(*args, **kwargs)
        self.full_clean()
        if self.archivo and not self.archivo._committed:
            if self.tipo == self.Tipo.FOTO:  # sin GPS, achicada, con miniatura
                grande, mini = imagenes.procesar_imagen(self.archivo.file, self.archivo.name)
                self.archivo.save(grande.name, grande, save=False)
                self.miniatura.save(mini.name, mini, save=False)
            self.tamano_bytes = self.archivo.size
        if self.tipo == self.Tipo.VIDEO:
            self.tamano_bytes = 0
        # Pasar a público (o subir algo público) siempre requiere una nueva aprobación.
        anterior = Archivo.objects.filter(pk=self.pk).values_list("visibilidad", flat=True).first()
        if self.visibilidad == self.Visibilidad.PUBLICO and anterior != self.Visibilidad.PUBLICO:
            self.aprobado = False
        super().save(*args, **kwargs)


# ===========================
# Comentarios en órdenes
# ===========================

class OrdenComentario(models.Model):
    """
    Conversación sobre una orden entre el taller y el cliente.
    Lo que escribe el personal es interno salvo que lo marque visible; lo del cliente siempre se ve.
    """

    orden = models.ForeignKey("taller.OrdenTrabajo", on_delete=models.CASCADE, related_name="comentarios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    texto = models.TextField(validators=[MaxLengthValidator(2000)])
    visible_piloto = models.BooleanField("visible para el cliente", default=False)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("fecha", "id")
        verbose_name = "comentario de orden"
        verbose_name_plural = "comentarios de órdenes"

    def __str__(self) -> str:
        return f"OT #{self.orden.numero} · {self.autor} · {self.texto[:40]}"

    def clean(self):
        super().clean()
        self.texto = (self.texto or "").strip()
        if not self.texto:
            raise ValidationError({"texto": "Escribí el comentario."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


def piloto_habilitado(perfil: PerfilPiloto) -> bool:
    """Puede subir y editar contenido: cuenta activa y al menos una membresía de piloto aprobada."""
    return perfil.usuario.is_active and perfil.usuario.membresias.filter(
        rol=Membresia.Rol.PILOTO, estado=Membresia.Estado.APROBADA, asociacion__activa=True
    ).exists()
