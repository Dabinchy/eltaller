"""
Portal de pilotos y campeonatos: cuentas.

- Asociacion: espacio propio de cada asociación (sus pilotos, moderadores y campeonatos).
- Membresia: une a un usuario del portal con una asociación, con rol (PILOTO / MODERADOR) y estado.
- PerfilPiloto: datos privados y públicos del piloto; nada sale a la web sin aprobación.
- RegistroModeracion: historial de cada decisión de moderación.

Las reglas (quién aprueba qué) están en portal/servicios.py y portal/permisos.py.
"""
from __future__ import annotations

import re
from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxLengthValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from core import imagenes
from core.almacenamiento import almacenamiento_privado

_INSTAGRAM_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


def _slug_unico(modelo, texto: str, pk=None, campo: str = "slug") -> str:
    base = slugify(texto)[:60] or "item"
    slug, n = base, 2
    while modelo.objects.filter(**{campo: slug}).exclude(pk=pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


# ===========================
# Asociación
# ===========================

class Asociacion(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True, help_text="Para su página pública. Se completa solo.")
    descripcion = models.TextField("descripción", blank=True)
    logo = models.ImageField(
        upload_to="asociaciones/", null=True, blank=True,
        validators=[FileExtensionValidator(imagenes.EXTENSIONES), imagenes.validar_tamano],
    )
    sitio_web = models.URLField(blank=True)
    instagram = models.CharField(max_length=100, blank=True, help_text="'@usuario' o el link; se guarda el usuario.")
    cuota_mb = models.PositiveIntegerField(
        "cuota por piloto (MB)", null=True, blank=True,
        help_text="Espacio por defecto de sus pilotos. Vacío = valor general del sistema.",
    )
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("nombre",)
        verbose_name = "asociación"
        verbose_name_plural = "asociaciones"

    def __str__(self) -> str:
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slug_unico(Asociacion, self.nombre, self.pk)
        self.instagram = _normalizar_instagram(self.instagram)
        _validar_instagram(self.instagram)
        self.full_clean()
        super().save(*args, **kwargs)


def _normalizar_instagram(valor: str) -> str:
    """'@juan.perez', 'https://instagram.com/juan.perez/' → 'juan.perez'."""
    valor = (valor or "").strip()
    valor = re.sub(r"^(https?://)?(www\.)?instagram\.com/", "", valor, flags=re.I)
    return valor.strip("/@ ")


def _validar_instagram(valor: str) -> None:
    if valor and not _INSTAGRAM_RE.match(valor):
        raise ValidationError("Usuario de Instagram inválido (letras, números, punto y guion bajo).")


# ===========================
# Membresía
# ===========================

class Membresia(models.Model):
    class Rol(models.TextChoices):
        PILOTO = "PILOTO", "Piloto"
        MODERADOR = "MODERADOR", "Moderador"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        SUSPENDIDA = "SUSPENDIDA", "Suspendida"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membresias")
    asociacion = models.ForeignKey(Asociacion, on_delete=models.PROTECT, related_name="membresias")
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.PILOTO)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, editable=False)
    motivo = models.TextField(blank=True, editable=False, help_text="Motivo del rechazo o la suspensión.")
    solicitada_el = models.DateTimeField(auto_now_add=True)
    resuelta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+", editable=False,
    )
    resuelta_el = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("asociacion", "rol", "-solicitada_el")
        constraints = [
            models.UniqueConstraint(
                fields=["usuario", "asociacion", "rol"], name="uq_membresia_usuario_asociacion_rol",
                violation_error_message="Esa persona ya tiene ese rol en la asociación.",
            ),
        ]
        indexes = [models.Index(fields=["asociacion", "rol", "estado"])]
        verbose_name = "membresía"
        verbose_name_plural = "membresías"

    def __str__(self) -> str:
        return f"{self.usuario} · {self.asociacion} · {self.get_rol_display()} ({self.get_estado_display()})"

    def clean(self):
        super().clean()
        if self.usuario_id and not self.usuario.es_portal:
            raise ValidationError({"usuario": "Sólo los usuarios del portal pueden ser miembros de una asociación."})

    def save(self, *args, **kwargs):
        if not kwargs.get("update_fields"):
            self.full_clean()
        super().save(*args, **kwargs)


# ===========================
# Perfil de piloto
# ===========================

def _ruta_foto(instance: "PerfilPiloto", filename: str) -> str:
    return f"pilotos/{instance.usuario_id}/perfil/{filename}"


class PerfilPiloto(models.Model):
    # Campos que se ven en la web: si cambian después de aprobados, el perfil se marca para revisión.
    CAMPOS_PUBLICOS = ("nombre_publico", "foto", "bio", "instagram", "sitio_web")

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_piloto")

    # --- Privados (el piloto, sus moderadores y el taller) ---
    licencia = models.CharField(max_length=40, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField("teléfono", max_length=40, blank=True)

    # --- Públicos ---
    nombre_publico = models.CharField("nombre público", max_length=80)
    slug = models.SlugField(max_length=70, unique=True, blank=True, help_text="Dirección del perfil: /pilotos/<slug>/.")
    foto = models.ImageField(
        upload_to=_ruta_foto, storage=almacenamiento_privado, null=True, blank=True,
        validators=[FileExtensionValidator(imagenes.EXTENSIONES), imagenes.validar_tamano],
    )
    foto_miniatura = models.ImageField(
        upload_to=_ruta_foto, storage=almacenamiento_privado, null=True, blank=True, editable=False,
    )
    bio = models.TextField("biografía", blank=True, validators=[MaxLengthValidator(3000)])
    # Acepta '@usuario' o el link completo; se guarda sólo el usuario (se valida en clean()).
    instagram = models.CharField(max_length=100, blank=True)
    sitio_web = models.URLField(blank=True)

    # --- Control ---
    perfil_publico = models.BooleanField(
        "mostrar en la web", default=False, help_text="Lo decide el piloto. Además necesita aprobación.",
    )
    aprobado = models.BooleanField(default=False, editable=False)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    aprobado_el = models.DateTimeField(null=True, blank=True, editable=False)
    cambio_tras_aprobacion = models.BooleanField(
        "cambió después de aprobado", default=False, editable=False,
        help_text="El piloto modificó datos públicos después de la aprobación.",
    )
    consentimiento_tutor = models.BooleanField(
        "consentimiento del tutor", default=False, editable=False,
        help_text="Obligatorio para publicar el perfil de un menor de edad.",
    )
    consentimiento_tutor_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    consentimiento_tutor_el = models.DateTimeField(null=True, blank=True, editable=False)
    cuota_mb = models.PositiveIntegerField(
        "cuota (MB)", null=True, blank=True, help_text="Vacío = la cuota de su asociación.",
    )

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("nombre_publico",)
        verbose_name = "perfil de piloto"
        verbose_name_plural = "perfiles de pilotos"

    def __str__(self) -> str:
        return self.nombre_publico

    # ------------ consultas ------------

    @property
    def edad(self) -> int | None:
        if not self.fecha_nacimiento:
            return None
        hoy = timezone.localdate()
        n = self.fecha_nacimiento
        return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))

    @property
    def es_menor(self) -> bool:
        edad = self.edad
        return edad is not None and edad < settings.PORTAL_EDAD_MAYORIA

    def asociaciones_aprobadas(self):
        return Asociacion.objects.filter(
            membresias__usuario_id=self.usuario_id,
            membresias__rol=Membresia.Rol.PILOTO,
            membresias__estado=Membresia.Estado.APROBADA,
            activa=True,
        ).distinct()

    @property
    def visible_en_web(self) -> bool:
        return (
            self.perfil_publico
            and self.aprobado
            and self.usuario.is_active
            and (not self.es_menor or self.consentimiento_tutor)
            and self.asociaciones_aprobadas().exists()
        )

    @property
    def cuota_efectiva_mb(self) -> int:
        if self.cuota_mb is not None:
            return self.cuota_mb
        cuotas = [c for c in self.asociaciones_aprobadas().values_list("cuota_mb", flat=True) if c is not None]
        return max(cuotas) if cuotas else settings.PORTAL_CUOTA_MB_POR_DEFECTO

    # ------------ guardado ------------

    def clean(self):
        super().clean()
        self.instagram = _normalizar_instagram(self.instagram)
        try:
            _validar_instagram(self.instagram)
        except ValidationError as e:
            raise ValidationError({"instagram": e.messages})
        if self.fecha_nacimiento and self.fecha_nacimiento > timezone.localdate():
            raise ValidationError({"fecha_nacimiento": "La fecha de nacimiento no puede ser futura."})
        if self.fecha_nacimiento and self.fecha_nacimiento < date(1900, 1, 1):
            raise ValidationError({"fecha_nacimiento": "Fecha de nacimiento inválida."})

    def _cambiaron_datos_publicos(self) -> bool:
        anterior = PerfilPiloto.objects.filter(pk=self.pk).values(*self.CAMPOS_PUBLICOS).first()
        if not anterior:
            return False
        return any(str(anterior[c] or "") != str(getattr(self, c) or "") for c in self.CAMPOS_PUBLICOS)

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields"):
            return super().save(*args, **kwargs)  # cambios internos (moderación)

        self.full_clean()
        if not self.slug:
            self.slug = _slug_unico(PerfilPiloto, self.nombre_publico, self.pk)

        # Foto nueva: se limpia (sin GPS), se achica y se genera la miniatura.
        if self.foto and not self.foto._committed:
            grande, mini = imagenes.procesar_imagen(self.foto.file, self.foto.name)
            self.foto.save(grande.name, grande, save=False)
            self.foto_miniatura.save(mini.name, mini, save=False)
        elif not self.foto and self.foto_miniatura:
            self.foto_miniatura = None

        if self.pk and self.aprobado and self._cambiaron_datos_publicos():
            self.cambio_tras_aprobacion = True
        super().save(*args, **kwargs)


# ===========================
# Historial de moderación
# ===========================

class RegistroModeracion(models.Model):
    class Accion(models.TextChoices):
        APROBAR = "APROBAR", "Aprobar"
        RECHAZAR = "RECHAZAR", "Rechazar"
        SUSPENDER = "SUSPENDER", "Suspender"
        REACTIVAR = "REACTIVAR", "Reactivar"
        RETIRAR = "RETIRAR", "Retirar aprobación"
        REVISADO = "REVISADO", "Marcar cambios como revisados"
        SPAM = "SPAM", "Marcar como spam"
        CONSENTIMIENTO = "CONSENTIMIENTO", "Registrar consentimiento del tutor"
        CUOTA = "CUOTA", "Cambiar cuota"
        REVOCAR = "REVOCAR", "Revocar acceso"
        VINCULAR = "VINCULAR", "Vincular con el taller"
        DESVINCULAR = "DESVINCULAR", "Desvincular del taller"

    fecha = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    accion = models.CharField("acción", max_length=15, choices=Accion.choices)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
    object_id = models.PositiveBigIntegerField(null=True)
    objeto = GenericForeignKey("content_type", "object_id")
    descripcion_objeto = models.CharField("objeto", max_length=200, help_text="Cómo se llamaba el objeto en ese momento.")
    asociacion = models.ForeignKey(Asociacion, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    motivo = models.TextField(blank=True)

    class Meta:
        ordering = ("-fecha", "-id")
        indexes = [models.Index(fields=["asociacion", "fecha"]), models.Index(fields=["content_type", "object_id"])]
        verbose_name = "registro de moderación"
        verbose_name_plural = "historial de moderación"

    def __str__(self) -> str:
        return f"{self.fecha:%d/%m/%Y %H:%M} · {self.actor} · {self.get_accion_display()} · {self.descripcion_objeto}"


# ===========================
# Acceso de cliente ("Mi taller")
# ===========================

class AccesoCliente(models.Model):
    """
    Une a un usuario del portal con un cliente del taller.
    - TITULAR: ve todo lo del cliente y puede aprobar presupuestos.
    - PILOTO: ve sólo los autos que maneja (por ejemplo, un piloto de un equipo).
    Mientras está PENDIENTE puede no tener cliente: el personal elige el correcto al aprobar.
    """

    class Rol(models.TextChoices):
        TITULAR = "TITULAR", "Titular"
        PILOTO = "PILOTO", "Piloto del equipo"

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        APROBADO = "APROBADO", "Aprobado"
        RECHAZADO = "RECHAZADO", "Rechazado"
        REVOCADO = "REVOCADO", "Revocado"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesos_cliente")
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, null=True, blank=True, related_name="accesos_portal",
    )
    rol = models.CharField(max_length=10, choices=Rol.choices, default=Rol.TITULAR)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, editable=False)

    # Lo que declaró la persona al pedir el acceso (para que el taller la identifique).
    nombre_declarado = models.CharField(max_length=150, blank=True)
    doc_declarado = models.CharField("documento declarado", max_length=15, blank=True)
    nota = models.TextField(blank=True, help_text="Ej.: 'Traje el Fiesta rojo en marzo'.")

    motivo = models.TextField(blank=True, editable=False)
    solicitado_el = models.DateTimeField(auto_now_add=True)
    resuelto_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    resuelto_el = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("estado", "-solicitado_el")
        permissions = [("gestionar_accesos_cliente", "Puede aprobar y revocar accesos de clientes al portal")]
        constraints = [
            models.CheckConstraint(
                condition=~Q(estado="APROBADO") | Q(cliente__isnull=False),
                name="ck_acceso_aprobado_con_cliente",
                violation_error_message="Un acceso aprobado tiene que tener cliente.",
            ),
            models.UniqueConstraint(
                fields=["usuario", "cliente"], condition=Q(cliente__isnull=False),
                name="uq_acceso_usuario_cliente",
                violation_error_message="Esa cuenta ya tiene acceso a ese cliente.",
            ),
        ]
        verbose_name = "acceso de cliente"
        verbose_name_plural = "accesos de clientes"

    def __str__(self) -> str:
        cliente = self.cliente or f"(declarado: {self.nombre_declarado or '—'})"
        return f"{self.usuario} → {cliente} · {self.get_estado_display()}"

    def clean(self):
        super().clean()
        if self.usuario_id and not self.usuario.es_portal:
            raise ValidationError({"usuario": "Sólo los usuarios del portal pueden tener acceso de cliente."})

    def save(self, *args, **kwargs):
        if not kwargs.get("update_fields"):
            self.full_clean()
        super().save(*args, **kwargs)


# Modelos de contenido (autos, palmarés, archivos) en un módulo aparte para no alargar este archivo.
from .models_contenido import Auto, Palmares, PilotoAuto, piloto_habilitado  # noqa: E402,F401
