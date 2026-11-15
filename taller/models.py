"""
Taller: vehículos, técnicos y turnos.

(Las órdenes de trabajo se agregan en una segunda etapa.)
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Sucursal


def _normalizar_codigo(valor: str) -> str:
    """Mayúsculas, sin espacios, guiones ni puntos: 'ab 123-cd' → 'AB123CD'."""
    return re.sub(r"[\s\-\.]+", "", (valor or "").upper())


def _anio_maximo() -> int:
    return timezone.now().year + 1


# ===========================
# Vehículo
# ===========================

class Vehiculo(models.Model):
    class Combustible(models.TextChoices):
        NAFTA = "NAFTA", "Nafta"
        DIESEL = "DIESEL", "Diésel"
        GNC = "GNC", "GNC"
        ETANOL = "ETANOL", "Etanol / E85"
        ELECTRICO = "ELECTRICO", "Eléctrico"
        HIBRIDO = "HIBRIDO", "Híbrido"
        OTRO = "OTRO", "Otro"

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="vehiculos",
        help_text="Dueño actual del vehículo.",
    )
    patente = models.CharField(max_length=15, unique=True, help_text="Se guarda en mayúsculas, sin espacios ni guiones.")
    marca = models.CharField(max_length=60)
    modelo = models.CharField(max_length=80)
    anio = models.PositiveSmallIntegerField("año", null=True, blank=True, validators=[MinValueValidator(1900)])
    vin = models.CharField("VIN / chasis", max_length=30, blank=True, default="")
    combustible = models.CharField(max_length=10, choices=Combustible.choices, default=Combustible.NAFTA)
    km_actual = models.PositiveIntegerField("km actual", default=0)

    # Competición
    numero_competicion = models.CharField("número de competición", max_length=10, blank=True)
    categoria = models.CharField("categoría", max_length=80, blank=True)

    # Presentación web (la edita el piloto desde el portal; la aprueba el taller)
    descripcion_web = models.TextField("descripción para la web", blank=True)
    publicado_web = models.BooleanField(
        "publicado en la web", default=False, help_text="Lo decide el piloto principal."
    )
    aprobado_por_taller = models.BooleanField(
        default=False, help_text="Nada sale a la web sin aprobación del taller."
    )

    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("patente",)
        indexes = [models.Index(fields=["cliente"]), models.Index(fields=["marca", "modelo"])]
        constraints = [
            models.UniqueConstraint(
                fields=["vin"],
                condition=~Q(vin=""),
                name="uq_vehiculo_vin_no_vacio",
                violation_error_message="Ya existe un vehículo con este VIN.",
            ),
        ]
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"

    def __str__(self) -> str:
        return f"{self.patente} · {self.marca} {self.modelo}"

    @property
    def esta_en_la_web(self) -> bool:
        return self.activo and self.publicado_web and self.aprobado_por_taller

    def _normalizar(self) -> None:
        self.patente = _normalizar_codigo(self.patente)
        self.vin = _normalizar_codigo(self.vin)

    def clean(self):
        super().clean()
        self._normalizar()
        if self.anio and self.anio > _anio_maximo():
            raise ValidationError({"anio": f"El año no puede ser mayor que {_anio_maximo()}."})

    def save(self, *args, **kwargs):
        self._normalizar()
        self.full_clean()
        super().save(*args, **kwargs)

    def registrar_km(self, km: int | None) -> None:
        """Actualiza km_actual si el valor informado es mayor (nunca baja)."""
        if km and km > self.km_actual:
            Vehiculo.objects.filter(pk=self.pk, km_actual__lt=km).update(km_actual=km)
            self.km_actual = km


# ===========================
# Técnico
# ===========================

class Tecnico(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="tecnico",
        help_text="Usuario con el que entra al panel (para ver sus órdenes asignadas).",
    )
    nombre = models.CharField(max_length=120)
    comision_pct = models.DecimalField(
        "comisión %", max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ("nombre",)
        verbose_name = "técnico"
        verbose_name_plural = "técnicos"

    def __str__(self) -> str:
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = (self.nombre or "").strip()
        if self.usuario_id and getattr(self.usuario, "es_piloto", False):
            raise ValidationError({"usuario": "Un piloto no puede ser técnico."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================
# Turno
# ===========================

class Turno(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        EN_TALLER = "EN_TALLER", "En taller"
        CANCELADO = "CANCELADO", "Cancelado"
        AUSENTE = "AUSENTE", "Ausente"

    # Estados que ocupan lugar en el cupo de la sucursal.
    ESTADOS_ACTIVOS = (Estado.PENDIENTE, Estado.CONFIRMADO, Estado.EN_TALLER)
    DURACION_MAXIMA_MIN = 24 * 60

    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="turnos")
    cliente = models.ForeignKey("clientes.Cliente", on_delete=models.PROTECT, related_name="turnos")
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name="turnos")
    inicio = models.DateTimeField()
    duracion_min = models.PositiveSmallIntegerField(
        "duración (min)", default=60,
        validators=[MinValueValidator(1), MaxValueValidator(DURACION_MAXIMA_MIN)],
    )
    motivo = models.CharField(max_length=255, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="turnos_creados", editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("inicio",)
        indexes = [models.Index(fields=["sucursal", "inicio"]), models.Index(fields=["estado"])]
        verbose_name = "turno"
        verbose_name_plural = "turnos"

    def __str__(self) -> str:
        return f"{timezone.localtime(self.inicio):%d/%m %H:%M} · {self.vehiculo} · {self.get_estado_display()}"

    @property
    def fin(self):
        return self.inicio + timedelta(minutes=self.duracion_min or 0)

    def clean(self):
        super().clean()
        if self.vehiculo_id and self.cliente_id and self.vehiculo.cliente_id != self.cliente_id:
            raise ValidationError({"vehiculo": "El vehículo no pertenece a ese cliente."})
        # Aviso temprano (formularios); en save() se vuelve a verificar con bloqueo.
        self._verificar_cupo()

    # ------------ cupo por sucursal ------------

    def _pico_superpuestos(self) -> int:
        """
        Máxima cantidad de turnos activos de la sucursal que coinciden al mismo tiempo
        dentro del horario de este turno (sin contarlo a él).
        """
        desde, hasta = self.inicio, self.fin
        candidatos = (
            Turno.objects.filter(
                sucursal_id=self.sucursal_id,
                estado__in=self.ESTADOS_ACTIVOS,
                inicio__lt=hasta,
                inicio__gt=desde - timedelta(minutes=self.DURACION_MAXIMA_MIN),
            )
            .exclude(pk=self.pk)
            .only("inicio", "duracion_min")
        )
        eventos = []
        for t in candidatos:
            if t.fin > desde:  # se superpone
                eventos.append((max(t.inicio, desde), 1))
                eventos.append((min(t.fin, hasta), -1))
        # A igual hora, primero los que terminan (-1) y después los que empiezan (+1).
        eventos.sort(key=lambda e: (e[0], e[1]))
        actual = pico = 0
        for _, delta in eventos:
            actual += delta
            pico = max(pico, actual)
        return pico

    def _verificar_cupo(self, bloquear: bool = False) -> None:
        if self.estado not in self.ESTADOS_ACTIVOS or not (self.sucursal_id and self.inicio):
            return
        qs = Sucursal.objects.all()
        if bloquear:
            # Bloquea la sucursal: dos altas simultáneas no pueden tomar el mismo último lugar.
            qs = qs.select_for_update()
        sucursal = qs.get(pk=self.sucursal_id)
        if sucursal.cupo_turnos is None:
            return  # sin límite
        ocupados = self._pico_superpuestos()
        if ocupados >= sucursal.cupo_turnos:
            desde, hasta = timezone.localtime(self.inicio), timezone.localtime(self.fin)
            raise ValidationError(
                f"La sucursal {sucursal} ya tiene {ocupados} turno(s) al mismo tiempo entre "
                f"{desde:%H:%M} y {hasta:%H:%M} (cupo {sucursal.cupo_turnos})."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            self._verificar_cupo(bloquear=True)
            super().save(*args, **kwargs)
