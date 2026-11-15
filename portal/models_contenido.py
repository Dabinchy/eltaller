"""
Portal de pilotos: contenido (autos, pilotos por auto, palmarés).

Las reglas (quién publica, invita o aprueba) están en portal/servicios_contenido.py.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .models import Membresia, PerfilPiloto, _slug_unico


def _anio_maximo() -> int:
    return timezone.now().year + 1


# ===========================
# Auto (presentación del piloto)
# ===========================

class Auto(models.Model):
    # Si cambian después de aprobado, el auto se marca para revisión.
    CAMPOS_PUBLICOS = ("marca", "modelo", "anio", "numero_competicion", "categoria", "descripcion")

    marca = models.CharField(max_length=60)
    modelo = models.CharField(max_length=80)
    anio = models.PositiveSmallIntegerField("año", null=True, blank=True, validators=[MinValueValidator(1900)])
    numero_competicion = models.CharField("número", max_length=10, blank=True)
    categoria = models.CharField("categoría", max_length=80, blank=True)
    descripcion = models.TextField("descripción", blank=True, validators=[MaxLengthValidator(3000)])
    slug = models.SlugField(max_length=70, unique=True, blank=True)

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


def piloto_habilitado(perfil: PerfilPiloto) -> bool:
    """Puede subir y editar contenido: cuenta activa y al menos una membresía de piloto aprobada."""
    return perfil.usuario.is_active and perfil.usuario.membresias.filter(
        rol=Membresia.Rol.PILOTO, estado=Membresia.Estado.APROBADA, asociacion__activa=True
    ).exists()
