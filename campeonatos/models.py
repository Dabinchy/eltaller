"""
Campeonatos de cada asociación.

    Asociación → Campeonato → Categorías
                            → Fechas → Carreras (Final, Series...)
                            → Tabla de puntos (por tipo de carrera)
                            → Inscripciones (piloto + categoría + número)
                            → Resultados (los carga cada piloto; los puntos los calcula el sistema)

Las reglas (quién crea, inscribe, carga o valida) están en campeonatos/servicios.py.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from portal.models import Asociacion, PerfilPiloto, _slug_unico


class TipoCarrera(models.TextChoices):
    FINAL = "FINAL", "Final"
    SERIE = "SERIE", "Serie"


# ===========================
# Campeonato
# ===========================

class Campeonato(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador (no se ve en la web)"
        EN_CURSO = "EN_CURSO", "En curso"
        FINALIZADO = "FINALIZADO", "Finalizado"

    asociacion = models.ForeignKey(Asociacion, on_delete=models.PROTECT, related_name="campeonatos")
    nombre = models.CharField(max_length=120)
    temporada = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    descripcion = models.TextField("descripción", blank=True)
    reglamento_url = models.URLField("link al reglamento", blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.BORRADOR)

    plazo_carga_dias = models.PositiveSmallIntegerField(
        "plazo de carga (días)", default=7, validators=[MaxValueValidator(60)],
        help_text="Días después de cada fecha para que los pilotos carguen o corrijan su resultado.",
    )
    puntos_pole = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    puntos_vuelta_rapida = models.DecimalField("puntos vuelta rápida", max_digits=5, decimal_places=2, default=0)
    abandonos_suman = models.BooleanField(
        "los abandonos clasificados suman", default=False,
        help_text="Si un piloto abandona pero queda clasificado, suma según su posición.",
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        ordering = ("-temporada", "nombre")
        constraints = [
            models.UniqueConstraint(
                fields=["asociacion", "nombre", "temporada"], name="uq_campeonato_asociacion_nombre_temporada",
                violation_error_message="Esa asociación ya tiene un campeonato con ese nombre en esa temporada.",
            ),
        ]
        verbose_name = "campeonato"
        verbose_name_plural = "campeonatos"

    def __str__(self) -> str:
        return f"{self.nombre} {self.temporada}"

    @property
    def visible_en_web(self) -> bool:
        return self.estado != self.Estado.BORRADOR and self.asociacion.activa

    def puntos_por_posicion(self, tipo: str, posicion: int | None) -> Decimal:
        if not posicion:
            return Decimal("0")
        fila = self.tabla_puntos.filter(tipo_carrera=tipo, posicion=posicion).first()
        return fila.puntos if fila else Decimal("0")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slug_unico(Campeonato, f"{self.nombre} {self.temporada}", self.pk)
        self.full_clean()
        super().save(*args, **kwargs)


class PuntajePosicion(models.Model):
    """Una fila de la tabla de puntos: en una carrera de tal tipo, tal posición suma tantos puntos."""

    campeonato = models.ForeignKey(Campeonato, on_delete=models.CASCADE, related_name="tabla_puntos")
    tipo_carrera = models.CharField(max_length=10, choices=TipoCarrera.choices, default=TipoCarrera.FINAL)
    posicion = models.PositiveSmallIntegerField("posición", validators=[MinValueValidator(1)])
    puntos = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ("campeonato", "tipo_carrera", "posicion")
        constraints = [
            models.UniqueConstraint(
                fields=["campeonato", "tipo_carrera", "posicion"], name="uq_puntaje_campeonato_tipo_posicion",
            ),
        ]
        verbose_name = "puntaje por posición"
        verbose_name_plural = "tabla de puntos"

    def __str__(self) -> str:
        return f"{self.get_tipo_carrera_display()} {self.posicion}° = {self.puntos}"


class Categoria(models.Model):
    campeonato = models.ForeignKey(Campeonato, on_delete=models.CASCADE, related_name="categorias")
    nombre = models.CharField(max_length=80)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("campeonato", "orden", "nombre")
        constraints = [
            models.UniqueConstraint(fields=["campeonato", "nombre"], name="uq_categoria_campeonato_nombre"),
        ]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self) -> str:
        return f"{self.campeonato} · {self.nombre}"


# ===========================
# Fechas y carreras
# ===========================

class Fecha(models.Model):
    class Estado(models.TextChoices):
        PROGRAMADA = "PROGRAMADA", "Programada"
        DISPUTADA = "DISPUTADA", "Disputada"
        SUSPENDIDA = "SUSPENDIDA", "Suspendida"

    campeonato = models.ForeignKey(Campeonato, on_delete=models.CASCADE, related_name="fechas")
    numero = models.PositiveSmallIntegerField("número", validators=[MinValueValidator(1)])
    nombre = models.CharField(max_length=120, blank=True, help_text="Ej.: 'GP Rafaela'.")
    circuito = models.CharField(max_length=120)
    dia = models.DateField("día")
    categorias = models.ManyToManyField(
        Categoria, blank=True, related_name="fechas", help_text="Vacío = corren todas las categorías.",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PROGRAMADA)
    multiplicador = models.DecimalField(
        max_digits=3, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("3"))],
        help_text="Ej.: 2.00 para una fecha con doble puntaje.",
    )

    class Meta:
        ordering = ("campeonato", "numero")
        constraints = [models.UniqueConstraint(fields=["campeonato", "numero"], name="uq_fecha_campeonato_numero")]
        verbose_name = "fecha"
        verbose_name_plural = "fechas"

    def __str__(self) -> str:
        return f"{self.campeonato} · Fecha {self.numero}" + (f" ({self.nombre})" if self.nombre else "")

    def corre_categoria(self, categoria: Categoria) -> bool:
        return categoria.campeonato_id == self.campeonato_id and (
            not self.categorias.exists() or self.categorias.filter(pk=categoria.pk).exists()
        )

    @property
    def cierre_carga(self) -> datetime:
        """Último momento en que un piloto puede cargar o corregir su resultado."""
        ultimo_dia = self.dia + timedelta(days=self.campeonato.plazo_carga_dias)
        return timezone.make_aware(datetime.combine(ultimo_dia, time.max))

    @property
    def carga_abierta(self) -> bool:
        ahora = timezone.now()
        return (
            self.estado != self.Estado.SUSPENDIDA
            and timezone.localdate() >= self.dia
            and ahora <= self.cierre_carga
        )

    def save(self, *args, **kwargs):
        nueva = self.pk is None
        self.full_clean()
        super().save(*args, **kwargs)
        if nueva:  # cada fecha nace con su Final
            Carrera.objects.create(fecha=self, nombre="Final", tipo=TipoCarrera.FINAL, orden=99, otorga_bonus=True)


class Carrera(models.Model):
    fecha = models.ForeignKey(Fecha, on_delete=models.CASCADE, related_name="carreras")
    nombre = models.CharField(max_length=60)
    tipo = models.CharField(max_length=10, choices=TipoCarrera.choices, default=TipoCarrera.FINAL)
    orden = models.PositiveSmallIntegerField(default=0)
    otorga_bonus = models.BooleanField(
        "suma pole y vuelta rápida", default=False, help_text="Normalmente sólo la Final.",
    )

    class Meta:
        ordering = ("fecha", "orden", "id")
        constraints = [models.UniqueConstraint(fields=["fecha", "nombre"], name="uq_carrera_fecha_nombre")]
        verbose_name = "carrera"
        verbose_name_plural = "carreras"

    def __str__(self) -> str:
        return f"{self.fecha} · {self.nombre}"


# ===========================
# Inscripción
# ===========================

class Inscripcion(models.Model):
    class Estado(models.TextChoices):
        ACTIVA = "ACTIVA", "Activa"
        BAJA = "BAJA", "Baja"

    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="inscripciones")
    piloto = models.ForeignKey(PerfilPiloto, on_delete=models.PROTECT, related_name="inscripciones")
    numero = models.CharField("número", max_length=5)
    auto = models.ForeignKey(
        "portal.Auto", on_delete=models.SET_NULL, null=True, blank=True, related_name="inscripciones",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ACTIVA, editable=False)
    motivo_baja = models.CharField(max_length=255, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("categoria", "numero")
        constraints = [
            models.UniqueConstraint(
                fields=["categoria", "piloto"], name="uq_inscripcion_categoria_piloto",
                violation_error_message="Ya estás inscripto en esa categoría.",
            ),
            models.UniqueConstraint(
                fields=["categoria", "numero"], condition=Q(estado="ACTIVA"),
                name="uq_inscripcion_categoria_numero_activo",
                violation_error_message="Ese número ya lo usa otro piloto en la categoría.",
            ),
        ]
        verbose_name = "inscripción"
        verbose_name_plural = "inscripciones"

    def __str__(self) -> str:
        return f"#{self.numero} {self.piloto} · {self.categoria}"

    @property
    def campeonato(self) -> Campeonato:
        return self.categoria.campeonato

    @property
    def nombre_mostrado(self) -> str:
        """Nombre para la tabla pública: un menor sin consentimiento aparece sólo con su número."""
        if self.piloto.es_menor and not self.piloto.consentimiento_tutor:
            return f"Piloto #{self.numero}"
        return self.piloto.nombre_publico

    def clean(self):
        super().clean()
        self.numero = (self.numero or "").strip().lstrip("#")
        if not self.numero:
            raise ValidationError({"numero": "Indicá tu número."})

    def save(self, *args, **kwargs):
        if not kwargs.get("update_fields"):
            self.full_clean()
        super().save(*args, **kwargs)


# ===========================
# Resultado
# ===========================

class Resultado(models.Model):
    """
    Lo carga cada piloto (sólo el suyo). Los puntos los calcula el sistema.
    - PROVISORIO: suma en la tabla al instante.
    - VALIDADO: lo confirmó un moderador o venció el plazo sin conflictos.
    - OBSERVADO: no suma hasta que se resuelva (conflicto automático o un moderador).
    - ANULADO: no suma.
    """

    class Condicion(models.TextChoices):
        FINALIZO = "FINALIZO", "Finalizó"
        ABANDONO = "ABANDONO", "Abandonó"
        NO_LARGO = "NO_LARGO", "No largó"
        DESCALIFICADO = "DESCALIFICADO", "Descalificado"

    class Estado(models.TextChoices):
        PROVISORIO = "PROVISORIO", "Provisorio"
        VALIDADO = "VALIDADO", "Validado"
        OBSERVADO = "OBSERVADO", "Observado"
        ANULADO = "ANULADO", "Anulado"

    ESTADOS_QUE_SUMAN = (Estado.PROVISORIO, Estado.VALIDADO)

    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, related_name="resultados")
    inscripcion = models.ForeignKey(Inscripcion, on_delete=models.PROTECT, related_name="resultados")
    posicion = models.PositiveSmallIntegerField("posición", null=True, blank=True, validators=[MinValueValidator(1)])
    condicion = models.CharField("condición", max_length=14, choices=Condicion.choices, default=Condicion.FINALIZO)
    pole = models.BooleanField(default=False)
    vuelta_rapida = models.BooleanField("vuelta rápida", default=False)

    puntos = models.DecimalField(max_digits=6, decimal_places=2, default=0, editable=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PROVISORIO, editable=False)
    observado_por_conflicto = models.BooleanField(default=False, editable=False)
    motivo = models.CharField(max_length=255, blank=True, editable=False, help_text="Por qué está observado o anulado.")

    cargado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+", editable=False,
    )
    cargado_el = models.DateTimeField(auto_now_add=True)
    modificado_el = models.DateTimeField(auto_now=True)
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False,
    )
    validado_el = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ("carrera", "posicion", "id")
        constraints = [
            models.UniqueConstraint(
                fields=["carrera", "inscripcion"], name="uq_resultado_carrera_inscripcion",
                violation_error_message="Ya cargaste tu resultado en esta carrera.",
            ),
        ]
        indexes = [models.Index(fields=["carrera", "estado"])]
        verbose_name = "resultado"
        verbose_name_plural = "resultados"

    def __str__(self) -> str:
        pos = f"{self.posicion}°" if self.posicion else self.get_condicion_display()
        return f"{self.carrera} · #{self.inscripcion.numero} {self.inscripcion.piloto} · {pos}"

    @property
    def clasificado(self) -> bool:
        """Ocupa una posición en el orden de llegada (y por eso puede chocar con otro piloto)."""
        return bool(self.posicion) and self.condicion in (self.Condicion.FINALIZO, self.Condicion.ABANDONO)

    def calcular_puntos(self) -> Decimal:
        fecha = self.carrera.fecha
        campeonato = fecha.campeonato
        C = self.Condicion
        base = Decimal("0")
        if self.condicion == C.FINALIZO or (self.condicion == C.ABANDONO and campeonato.abandonos_suman):
            base = campeonato.puntos_por_posicion(self.carrera.tipo, self.posicion)
        bonus = Decimal("0")
        if self.carrera.otorga_bonus and self.condicion != C.DESCALIFICADO:
            if self.pole:
                bonus += campeonato.puntos_pole
            if self.vuelta_rapida:
                bonus += campeonato.puntos_vuelta_rapida
        return ((base + bonus) * fecha.multiplicador).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        C = self.Condicion
        if self.condicion == C.FINALIZO and not self.posicion:
            raise ValidationError({"posicion": "Indicá en qué posición terminaste."})
        if self.condicion in (C.NO_LARGO, C.DESCALIFICADO):
            self.posicion = None
        if self.condicion == C.NO_LARGO and (self.pole or self.vuelta_rapida):
            raise ValidationError("Si no largaste no podés tener vuelta rápida ni pole en carrera.")
        if self.carrera_id and self.inscripcion_id:
            if not self.carrera.fecha.corre_categoria(self.inscripcion.categoria):
                raise ValidationError("Tu categoría no corre en esta fecha.")
            if self.inscripcion.estado != Inscripcion.Estado.ACTIVA:
                raise ValidationError("La inscripción está dada de baja.")
            if (self.pole or self.vuelta_rapida) and not self.carrera.otorga_bonus:
                raise ValidationError("Esta carrera no otorga pole ni vuelta rápida.")

    def save(self, *args, **kwargs):
        if not kwargs.get("update_fields"):
            self.full_clean()
            self.puntos = self.calcular_puntos()
        super().save(*args, **kwargs)
