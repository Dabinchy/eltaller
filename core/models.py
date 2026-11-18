# core/models.py
"""
Modelos base (CORE) del sistema del taller.

Incluye:
- Empresa (una sola fila) y Sucursal
- Usuario (custom): tipo STAFF/PORTAL + PIN para acciones críticas (con bloqueo)
- Caja, SesionCaja, CajaMovimiento
- PuntoVenta (AFIP: opcional, sin uso por ahora)

Notas de diseño:
- Las fechas de apertura/cierre de sesión son automáticas e inmutables.
- Sólo puede existir una sesión ABIERTA por caja (constraint condicional).
- Los movimientos de caja no permiten montos negativos.
"""

from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse

from django.apps import apps
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Max, Q, UniqueConstraint
from django.utils import timezone


# ====================================================
# CONDICIÓN IVA (AFIP)
# ====================================================

class CondicionIVA(models.TextChoices):
    RESPONSABLE_INSCRIPTO = "RI", "Responsable Inscripto"
    MONOTRIBUTO = "MO", "Monotributo"
    EXENTO = "EX", "Exento"
    NO_RESPONSABLE = "NR", "No Responsable"
    CONSUMIDOR_FINAL = "CF", "Consumidor Final"


# ====================================================
# EMPRESA (UNA SOLA FILA) / SUCURSAL
# ====================================================

class Empresa(models.Model):
    """Datos del taller. El sistema trabaja con una única empresa."""

    # Identificación
    nombre = models.CharField(max_length=150)
    razon_social = models.CharField(max_length=255, blank=True)
    cuit = models.CharField(
        max_length=11,
        blank=True,
        help_text="CUIT (11 dígitos, sin guiones). Opcional.",
    )
    iibb_numero = models.CharField("Nº Ingresos Brutos", max_length=30, blank=True)
    domicilio_comercial = models.CharField(max_length=255, blank=True)

    COND_IVA_CHOICES = [
        ("RI", "Responsable Inscripto"),
        ("MO", "Monotributista"),
        ("EX", "Exento"),
        ("NR", "No responsable"),
        ("CF", "Consumidor final"),
    ]
    condicion_iva = models.CharField(max_length=2, choices=COND_IVA_CHOICES, default="RI")

    # Contacto
    direccion = models.CharField(max_length=255, blank=True)
    localidad = models.CharField(max_length=120, blank=True)
    provincia = models.CharField(max_length=120, blank=True)
    codigo_postal = models.CharField(max_length=20, blank=True)
    pais = models.CharField(max_length=100, blank=True, default="Argentina")
    telefono = models.CharField(max_length=50, blank=True)
    email_contacto = models.EmailField(blank=True)
    activa = models.BooleanField(default=True)

    # Para el sitio web público
    whatsapp = models.CharField(max_length=30, blank=True)
    horarios = models.TextField(blank=True, help_text="Horarios de atención, uno por línea.")
    logo = models.ImageField(upload_to="empresa/", blank=True, null=True)
    descripcion_web = models.TextField(blank=True, help_text="Texto de presentación del taller.")
    instagram = models.CharField(max_length=100, blank=True, help_text="'@usuario' o el link; se guarda el usuario.")
    facebook = models.URLField(blank=True, help_text="Link a la página de Facebook.")
    youtube = models.URLField(blank=True, help_text="Link al canal de YouTube.")
    mapa_url = models.URLField(
        "link de Google Maps", blank=True,
        help_text="En Google Maps: Compartir → Copiar vínculo (ej.: https://maps.app.goo.gl/...).",
    )

    # AFIP (opcional; sin uso por ahora)
    afip_modo = models.CharField(
        max_length=20,
        choices=[("HOMOLOGACION", "Homologación"), ("PRODUCCION", "Producción")],
        default="HOMOLOGACION",
    )
    afip_punto_venta_default = models.PositiveIntegerField(blank=True, null=True)
    afip_cert_alias = models.CharField(max_length=100, blank=True)
    inicio_actividades = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresa"

    def __str__(self) -> str:
        return self.nombre

    _HOSTS_REDES = {
        "facebook": ("facebook.com", "fb.com"),
        "youtube": ("youtube.com", "youtu.be"),
        "mapa_url": ("google.com", "google.com.ar", "goo.gl", "maps.app.goo.gl"),
    }

    def clean(self):
        super().clean()
        from portal.models import _normalizar_instagram, _validar_instagram  # evita import circular

        self.instagram = _normalizar_instagram(self.instagram)
        try:
            _validar_instagram(self.instagram)
        except ValidationError as e:
            raise ValidationError({"instagram": e.messages}) from e
        for campo, hosts in self._HOSTS_REDES.items():
            valor = getattr(self, campo)
            if not valor:
                continue
            host = (urlparse(valor).hostname or "").lower()
            if not any(host == h or host.endswith("." + h) for h in hosts):
                raise ValidationError({campo: "Ese link no es de " + (
                    "Google Maps" if campo == "mapa_url" else campo.capitalize()) + "."})

    def save(self, *args, **kwargs):
        # Una sola fila: no se puede crear una segunda empresa.
        if self.pk is None and Empresa.objects.exists():
            raise ValidationError("Ya existe la empresa. El sistema trabaja con una sola.")
        return super().save(*args, **kwargs)

    @classmethod
    def actual(cls):
        """Devuelve la única empresa (o None si todavía no se cargó)."""
        return cls.objects.first()


class Sucursal(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    direccion = models.CharField(max_length=255, blank=True)
    activa = models.BooleanField(default=True)
    cupo_turnos = models.PositiveSmallIntegerField(
        "cupo de turnos",
        null=True,
        blank=True,
        help_text="Turnos que la sucursal atiende al mismo tiempo. Vacío = sin límite.",
    )

    class Meta:
        verbose_name = "sucursal"
        verbose_name_plural = "sucursales"
        ordering = ("nombre",)

    def __str__(self) -> str:
        return self.nombre


# ====================================================
# USUARIO
# ====================================================

def _pin_fingerprint(pin: str) -> str:
    """
    Huella determinística del PIN usando SECRET_KEY como 'pepper'.
    NO es reversible. Sirve sólo para forzar que dos usuarios no tengan el mismo PIN.
    """
    base = (settings.SECRET_KEY or "") + "|" + (pin or "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class Usuario(AbstractUser):
    """
    Usuario único del sistema.

    - tipo STAFF: personal del taller (mecánicos, jefes, gerentes). Sus roles son Grupos de Django.
    - tipo PORTAL: pilotos, clientes y moderadores que entran al portal. Lo que pueden hacer
      depende de lo que tengan asociado (perfil de piloto, acceso de cliente, membresía).
    - sucursal: sucursal fija opcional (para cajeros/encargados).
    """

    class Tipo(models.TextChoices):
        STAFF = "STAFF", "Personal del taller"
        PORTAL = "PORTAL", "Usuario del portal"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.STAFF)

    # Dato PRIVADO: obligatorio al registrarse en el portal; nunca se muestra en la web.
    # Lo ven el propio usuario, el personal del taller y los moderadores de su asociación.
    dni = models.CharField(
        "DNI / documento", max_length=15, blank=True, default="",
        help_text="Sólo dígitos y letras, sin puntos ni espacios. Privado.",
    )

    sucursal = models.ForeignKey(
        "core.Sucursal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="usuarios",
        help_text="Sucursal fija (cajeros/encargados). Gerentes pueden quedar sin sucursal.",
    )

    # PIN para acciones críticas (no reversible)
    action_pin_hash = models.CharField(max_length=128, blank=True, default="")
    action_pin_fingerprint = models.CharField(max_length=64, blank=True, default="")
    pin_failed_attempts = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # Dos usuarios no pueden tener el mismo PIN (si está seteado)
            UniqueConstraint(
                fields=["action_pin_fingerprint"],
                condition=~Q(action_pin_fingerprint=""),
                name="uq_usuario_pin_fingerprint",
            ),
            # Un DNI no puede estar en dos cuentas (evita duplicados y registros falsos).
            UniqueConstraint(
                fields=["dni"],
                condition=~Q(dni=""),
                name="uq_usuario_dni_no_vacio",
                violation_error_message="Ya existe una cuenta con este DNI / documento.",
            ),
        ]

    @property
    def es_portal(self) -> bool:
        return self.tipo == self.Tipo.PORTAL

    @property
    def es_personal(self) -> bool:
        return self.tipo == self.Tipo.STAFF

    @staticmethod
    def normalizar_dni(valor: str) -> str:
        """'20.123.456' → '20123456'; 'aa 123456' → 'AA123456'."""
        return re.sub(r"[^0-9A-Za-z]", "", valor or "").upper()

    def save(self, *args, **kwargs):
        self.dni = self.normalizar_dni(self.dni)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.dni = self.normalizar_dni(self.dni)
        if self.dni and not 6 <= len(self.dni) <= 15:
            raise ValidationError({"dni": "El documento debe tener entre 6 y 15 caracteres."})
        if self.es_portal and self.sucursal_id is not None:
            raise ValidationError({"sucursal": "Un usuario del portal no puede tener sucursal fija."})

    # --- Gestión de PIN y bloqueo ---
    PIN_MIN_LEN = 4
    PIN_MAX_ATTEMPTS = 5
    PIN_LOCK_MINUTES = 15

    def set_action_pin(self, pin: str) -> None:
        if self.es_portal:
            raise ValidationError("Los usuarios del portal no usan PIN.")
        if not pin or len(pin) < self.PIN_MIN_LEN or not pin.isdigit():
            raise ValidationError(
                f"El PIN debe tener sólo dígitos y al menos {self.PIN_MIN_LEN} de largo."
            )
        self.action_pin_hash = make_password(pin)
        self.action_pin_fingerprint = _pin_fingerprint(pin)

    def check_action_pin(self, pin: str) -> bool:
        if not self.action_pin_hash:
            return False
        return check_password(pin, self.action_pin_hash)

    def pin_is_locked(self) -> bool:
        return self.pin_locked_until is not None and self.pin_locked_until > timezone.now()

    def register_pin_failure(self) -> None:
        self.pin_failed_attempts += 1
        if self.pin_failed_attempts >= self.PIN_MAX_ATTEMPTS:
            self.pin_locked_until = timezone.now() + timedelta(minutes=self.PIN_LOCK_MINUTES)
        self.save(update_fields=["pin_failed_attempts", "pin_locked_until"])

    def reset_pin_failures(self) -> None:
        self.pin_failed_attempts = 0
        self.pin_locked_until = None
        self.save(update_fields=["pin_failed_attempts", "pin_locked_until"])

    def verify_action_pin_or_raise(self, pin: str) -> None:
        if self.pin_is_locked():
            raise PermissionDenied("PIN bloqueado temporalmente. Intente más tarde.")

        if not self.check_action_pin(pin):
            self.register_pin_failure()
            raise PermissionDenied("PIN inválido.")

        self.reset_pin_failures()


# ====================================================
# PUNTO DE VENTA (AFIP, opcional)
# ====================================================

class PuntoVenta(models.Model):
    class TipoEmision(models.TextChoices):
        WSFE = "WSFE", "WSFEv1 (A/B/C sin detalle)"
        WSMTXCA = "WSMTXCA", "WSMTXCA (con detalle de ítems)"
        CONTROLADOR_FISCAL = "CFIS", "Controlador fiscal"
        MANUAL = "MAN", "Manual / Comprobantes en línea"

    sucursal = models.ForeignKey(
        "core.Sucursal",
        on_delete=models.PROTECT,
        related_name="puntos_venta",
        null=True,
        blank=True,
        help_text="Sucursal física asociada a este punto de venta AFIP.",
    )
    numero = models.PositiveIntegerField(
        unique=True,
        help_text="Número de punto de venta AFIP (ej: 1, 3, 10).",
    )
    descripcion = models.CharField(max_length=120, blank=True)
    tipo_emision = models.CharField(
        max_length=8,
        choices=TipoEmision.choices,
        default=TipoEmision.WSFE,
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ("numero",)

    def __str__(self) -> str:
        return f"PV {self.numero}"


# ====================================================
# CAJA / SESIÓN / MOVIMIENTOS
# ====================================================

class Caja(models.Model):
    sucursal = models.ForeignKey(
        "core.Sucursal",
        on_delete=models.PROTECT,
        related_name="cajas",
    )
    numero = models.PositiveIntegerField(
        help_text="Número correlativo por sucursal. Se auto-asigna si no se indica."
    )
    nombre = models.CharField(max_length=120, blank=True)
    activa = models.BooleanField(default=True)
    punto_venta = models.ForeignKey(
        "core.PuntoVenta",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cajas",
        help_text="Opcional: punto de venta AFIP asociado a esta caja.",
    )

    class Meta:
        unique_together = [("sucursal", "numero")]
        ordering = ("sucursal", "numero")

    def __str__(self) -> str:
        base = f"Caja {self.numero}"
        if self.nombre:
            base += f" ({self.nombre})"
        return f"{self.sucursal} · {base}"

    def clean(self):
        super().clean()
        if self.punto_venta_id and self.punto_venta.sucursal_id:
            if self.punto_venta.sucursal_id != self.sucursal_id:
                raise ValidationError({
                    "punto_venta": "El punto de venta está asociado a otra sucursal."
                })

    def save(self, *args, **kwargs):
        """Autoasigna el número correlativo por sucursal si viene vacío o 0."""
        creating = self.pk is None

        if creating and (not self.numero or self.numero <= 0):
            for _ in range(5):  # reintentos por concurrencia
                with transaction.atomic():
                    max_num = (
                        Caja.objects.filter(sucursal=self.sucursal)
                        .aggregate(m=Max("numero"))
                        .get("m") or 0
                    )
                    self.numero = max_num + 1
                    self.full_clean()
                    try:
                        return super().save(*args, **kwargs)
                    except IntegrityError:
                        continue  # otro proceso tomó el mismo número
            raise ValidationError("No se pudo asignar un número único de caja. Reintentá.")

        if not creating:
            original = Caja.objects.only("numero").get(pk=self.pk)
            if self.numero != original.numero:
                raise ValidationError("El número de la caja no puede modificarse.")

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        if self.sesiones.exists() or self.movimientos.exists():
            raise ValidationError("No se puede eliminar una caja con sesiones o movimientos asociados.")
        return super().delete(using=using, keep_parents=keep_parents)


class TipoMovCaja(models.TextChoices):
    APERTURA = "apertura", "Apertura"
    CIERRE = "cierre", "Cierre"
    INGRESO = "ingreso", "Ingreso"
    EGRESO = "egreso", "Egreso"
    AJUSTE = "ajuste", "Ajuste"


class CajaMovimiento(models.Model):
    """
    Movimiento de efectivo ligado a una sesión de caja.
    Los de APERTURA y CIERRE se generan automáticamente al abrir/cerrar la sesión.
    """
    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="movimientos")
    sesion = models.ForeignKey(
        "SesionCaja",
        on_delete=models.PROTECT,
        related_name="movimientos",
        null=True,
        blank=True,
    )
    tipo = models.CharField(max_length=20, choices=TipoMovCaja.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.CharField(max_length=255, blank=True)
    es_sistema = models.BooleanField(
        default=False,
        editable=False,
        help_text="Marca interna: movimientos generados por el sistema (apertura/cierre).",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento de caja"
        verbose_name_plural = "movimientos de caja"
        constraints = [
            models.CheckConstraint(condition=Q(monto__gte=0), name="ck_mov_monto_no_negativo"),
        ]

    def __str__(self):
        return f"[{self.caja}] {self.tipo} {self.monto} ({self.creado_el:%Y-%m-%d %H:%M})"

    def clean(self):
        super().clean()

        # APERTURA/CIERRE sólo los genera el sistema.
        if self.tipo in (TipoMovCaja.APERTURA, TipoMovCaja.CIERRE) and not self.es_sistema:
            raise ValidationError("Los movimientos de APERTURA/CIERRE se generan automáticamente.")

        # Normalización y validación del monto.
        try:
            self.monto = (self.monto or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            raise ValidationError({"monto": "Monto inválido."})

        if self.monto < 0:
            raise ValidationError({"monto": "El monto no puede ser negativo."})

        # Coherencia caja-sesión
        if self.sesion_id:
            if self.sesion.caja_id != self.caja_id:
                raise ValidationError({"sesion": "La sesión seleccionada no corresponde a la misma caja."})

            # Sólo con sesión ABIERTA (excepto el movimiento de CIERRE del sistema).
            if self.sesion.estado != SesionCaja.Estado.ABIERTA:
                if not (
                    self.es_sistema
                    and self.tipo == TipoMovCaja.CIERRE
                    and self.sesion.estado == SesionCaja.Estado.CERRADA
                ):
                    raise ValidationError({"sesion": "No se pueden registrar movimientos en una sesión CERRADA."})

        # Alcance del usuario que registra
        if self.creado_por_id and not self.creado_por.is_superuser:
            if self.creado_por.es_portal:
                raise ValidationError({"creado_por": "Un usuario del portal no puede registrar movimientos de caja."})
            if self.creado_por.sucursal_id and self.caja.sucursal_id != self.creado_por.sucursal_id:
                raise ValidationError({"creado_por": "No puede registrar movimientos en una caja de otra sucursal."})

    def save(self, *args, **kwargs):
        # Auditoría: un movimiento es un evento inmutable.
        if self.pk:
            raise ValidationError("Los movimientos de caja son inmutables y no pueden modificarse.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("Los movimientos de caja no pueden eliminarse (auditoría).")


class SesionCaja(models.Model):
    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        CERRADA = "CERRADA", "Cerrada"

    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="sesiones")
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.ABIERTA,
        editable=False,
    )

    # Fechas automáticas e inmutables
    abierta_el = models.DateTimeField("Apertura", null=True, editable=False)
    cerrada_el = models.DateTimeField("Cierre", null=True, editable=False)

    # Responsables y metadatos
    abierta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sesiones_abiertas",
        null=True,
        editable=False,
    )
    cerrada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sesiones_cerradas",
        null=True,
        blank=True,
        editable=False,
    )
    ip_apertura = models.GenericIPAddressField(null=True, blank=True, editable=False)
    ip_cierre = models.GenericIPAddressField(null=True, blank=True, editable=False)
    terminal = models.CharField(max_length=100, blank=True, editable=False)

    # Saldos
    saldo_inicial = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    saldo_estimado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    saldo_cierre = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    observacion_cierre = models.CharField(max_length=255, blank=True)
    total_efectivo_contado = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Importe de efectivo contado al cerrar la sesión.",
    )
    diferencia = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Diferencia entre saldo estimado y efectivo contado.",
    )

    class Meta:
        constraints = [
            # A lo sumo UNA sesión ABIERTA por caja
            models.UniqueConstraint(
                fields=["caja"],
                condition=Q(estado="ABIERTA"),
                name="uq_sesion_abierta_por_caja",
            ),
            # Coherencia estado ↔ fechas / responsables / efectivo contado
            models.CheckConstraint(
                condition=(
                    Q(
                        estado="ABIERTA",
                        abierta_el__isnull=False,
                        abierta_por__isnull=False,
                        cerrada_el__isnull=True,
                        cerrada_por__isnull=True,
                        total_efectivo_contado__isnull=True,
                    )
                    | Q(
                        estado="CERRADA",
                        abierta_el__isnull=False,
                        abierta_por__isnull=False,
                        cerrada_el__isnull=False,
                        cerrada_por__isnull=False,
                        total_efectivo_contado__isnull=False,
                    )
                ),
                name="ck_sesion_estado_timestamps",
            ),
            # Saldos no negativos (la diferencia sí puede ser negativa)
            models.CheckConstraint(
                condition=(
                    Q(saldo_inicial__gte=0)
                    & Q(saldo_estimado__gte=0)
                    & (Q(saldo_cierre__isnull=True) | Q(saldo_cierre__gte=0))
                    & (Q(total_efectivo_contado__isnull=True) | Q(total_efectivo_contado__gte=0))
                ),
                name="ck_sesion_saldos_no_negativos",
            ),
        ]
        permissions = [
            ("abrir_caja", "Puede abrir caja"),
            ("cerrar_caja", "Puede cerrar caja"),
            ("movimientos_caja", "Puede registrar ingresos/egresos/ajustes de caja"),
            ("administrar_core", "Puede administrar entidades CORE"),
        ]

    def __str__(self):
        return f"Sesión {self.id or ''} · {self.caja} · {self.estado}"

    def clean(self):
        super().clean()

        caja_sucursal_id = self.caja.sucursal_id if self.caja_id else None

        def _check_usuario_scope(user, field_name: str):
            if not user or getattr(user, "is_superuser", False):
                return
            if user.es_portal:
                raise ValidationError({field_name: "Un usuario del portal no puede operar cajas."})
            # Si el usuario tiene sucursal fija (cajero/encargado), debe coincidir.
            if user.sucursal_id and caja_sucursal_id is not None and user.sucursal_id != caja_sucursal_id:
                raise ValidationError({field_name: "El usuario pertenece a otra sucursal."})

        _check_usuario_scope(self.abierta_por, "abierta_por")
        _check_usuario_scope(self.cerrada_por, "cerrada_por")

        # Coherencia estado ↔ fechas / responsables
        if self.estado == self.Estado.ABIERTA:
            if not self.abierta_el:
                raise ValidationError({"abierta_el": "La apertura debe registrar fecha/hora."})
            if not self.abierta_por_id:
                raise ValidationError({"abierta_por": "Debe quedar registrado el usuario que abrió la caja."})
            if self.cerrada_el is not None or self.cerrada_por_id is not None:
                raise ValidationError("Una sesión ABIERTA no puede tener datos de cierre.")
            if self.total_efectivo_contado is not None:
                raise ValidationError({"total_efectivo_contado": "El efectivo contado sólo se informa al cerrar."})

        elif self.estado == self.Estado.CERRADA:
            if not self.abierta_el:
                raise ValidationError({"abierta_el": "La sesión debe conservar la fecha/hora de apertura."})
            if not self.abierta_por_id:
                raise ValidationError({"abierta_por": "Debe quedar registrado el usuario que abrió la caja."})
            if not self.cerrada_el:
                raise ValidationError({"cerrada_el": "La sesión CERRADA debe registrar fecha/hora de cierre."})
            if not self.cerrada_por_id:
                raise ValidationError({"cerrada_por": "Debe quedar registrado el usuario que cerró la caja."})
            if self.total_efectivo_contado is None:
                raise ValidationError({"total_efectivo_contado": "Debe informar el efectivo contado al cierre."})

        # Normalización de saldos (2 decimales)
        for field in ("saldo_inicial", "saldo_estimado", "saldo_cierre", "total_efectivo_contado"):
            val = getattr(self, field, None)
            if val is None:
                continue
            try:
                setattr(self, field, Decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            except Exception:
                raise ValidationError({field: "Monto inválido."})

        # Saldos no negativos (la diferencia sí puede ser negativa)
        if self.saldo_inicial is not None and self.saldo_inicial < 0:
            raise ValidationError({"saldo_inicial": "El saldo inicial no puede ser negativo."})
        if self.saldo_estimado is not None and self.saldo_estimado < 0:
            raise ValidationError({"saldo_estimado": "El saldo estimado no puede ser negativo."})
        if self.saldo_cierre is not None and self.saldo_cierre < 0:
            raise ValidationError({"saldo_cierre": "El saldo de cierre no puede ser negativo."})
        if self.total_efectivo_contado is not None and self.total_efectivo_contado < 0:
            raise ValidationError({"total_efectivo_contado": "El efectivo contado no puede ser negativo."})

    # --------- LÓGICA DE NEGOCIO ---------

    @classmethod
    def abrir(
        cls,
        *,
        caja,
        usuario,
        pin,
        ip=None,
        terminal: str = "",
        saldo_inicial: Decimal = Decimal("0.00"),
    ) -> "SesionCaja":
        # Permisos
        if not (usuario.is_superuser or usuario.has_perm("core.abrir_caja")):
            raise PermissionDenied("No tiene permisos para abrir caja.")
        if usuario.es_portal:
            raise PermissionDenied("Los usuarios del portal no pueden operar cajas.")
        if not usuario.is_superuser:
            if usuario.sucursal_id and caja.sucursal_id != usuario.sucursal_id:
                raise PermissionDenied("No puede abrir cajas de otra sucursal.")

        # Siempre exige un PIN válido
        usuario.verify_action_pin_or_raise(pin)

        try:
            saldo_inicial = (saldo_inicial or Decimal("0")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except Exception:
            saldo_inicial = Decimal("0.00")
        if saldo_inicial < 0:
            raise ValidationError("El monto inicial no puede ser negativo.")

        with transaction.atomic():
            if cls.objects.select_for_update().filter(caja=caja, estado=cls.Estado.ABIERTA).exists():
                raise ValidationError("La caja ya tiene una sesión ABIERTA.")

            try:
                sesion = cls.objects.create(
                    caja=caja,
                    estado=cls.Estado.ABIERTA,
                    abierta_el=timezone.now(),
                    abierta_por=usuario,
                    ip_apertura=ip,
                    terminal=terminal[:100],
                    saldo_inicial=saldo_inicial,
                    saldo_estimado=saldo_inicial,
                )
            except IntegrityError:
                raise ValidationError("La caja ya tiene una sesión ABIERTA.")

            CajaMovimiento.objects.create(
                caja=caja,
                sesion=sesion,
                tipo=TipoMovCaja.APERTURA,
                monto=saldo_inicial,
                motivo="Apertura de caja",
                creado_por=usuario,
                es_sistema=True,
            )
            return sesion

    def _tiene_ventas_pendientes(self) -> bool:
        """Si existe la app 'ventas', valida que no haya ventas ABIERTAS en esta sesión."""
        if apps.is_installed("ventas"):
            Venta = apps.get_model("ventas", "Venta")
            try:
                return Venta.objects.filter(sesion=self, estado="ABIERTA").exists()
            except Exception:
                return False
        return False

    def cerrar(self, usuario, total_efectivo_contado: Decimal, observacion: str = "", ip: str | None = None):
        """
        Cierra la sesión: guarda el efectivo contado, calcula la diferencia contra el
        saldo estimado y registra el movimiento de cierre.
        Se bloquea si hay ventas ABIERTAS en la sesión (cuando la app ventas está instalada).
        """
        if not (usuario.is_superuser or usuario.has_perm("core.cerrar_caja")):
            raise PermissionDenied("No tiene permisos para cerrar caja.")
        if usuario.es_portal:
            raise PermissionDenied("Los usuarios del portal no pueden operar cajas.")
        if not usuario.is_superuser:
            if usuario.sucursal_id and self.caja.sucursal_id != usuario.sucursal_id:
                raise PermissionDenied("No puede cerrar cajas de otra sucursal.")

        with transaction.atomic():
            sesion = type(self).objects.select_for_update().get(pk=self.pk)

            if sesion.estado != self.Estado.ABIERTA:
                raise ValidationError("La sesión ya está cerrada.")

            if sesion._tiene_ventas_pendientes():
                raise ValidationError("No se puede cerrar la caja: hay ventas pendientes ABIERTAS en esta sesión.")

            total_efectivo_contado = Decimal(total_efectivo_contado).quantize(Decimal("0.01"))
            esperado = (sesion.saldo_estimado or Decimal("0.00")).quantize(Decimal("0.01"))

            sesion.total_efectivo_contado = total_efectivo_contado
            sesion.saldo_cierre = total_efectivo_contado
            sesion.diferencia = total_efectivo_contado - esperado
            sesion.cerrada_el = timezone.now()
            sesion.cerrada_por = usuario
            sesion.ip_cierre = ip
            sesion.observacion_cierre = observacion or ""
            sesion.estado = self.Estado.CERRADA
            sesion.save(update_fields=[
                "total_efectivo_contado", "saldo_cierre", "diferencia",
                "cerrada_el", "cerrada_por", "ip_cierre", "observacion_cierre", "estado",
            ])
            CajaMovimiento.objects.create(
                caja=sesion.caja,
                sesion=sesion,
                tipo=TipoMovCaja.CIERRE,
                monto=total_efectivo_contado,
                motivo="Cierre de caja",
                creado_por=usuario,
                es_sistema=True,
            )

    # Blindaje: las fechas y relaciones clave no se pueden modificar
    def save(self, *args, **kwargs):
        creating = self.pk is None

        if creating and not self.abierta_el:
            self.abierta_el = timezone.now()

        if not creating:
            original = type(self).objects.only(
                "caja_id", "estado", "abierta_el", "abierta_por_id", "cerrada_el", "cerrada_por_id",
            ).get(pk=self.pk)

            if self.caja_id != original.caja_id:
                raise ValidationError("No se puede cambiar la caja de una sesión existente.")
            if self.abierta_el != original.abierta_el:
                raise ValidationError("La fecha de apertura es automática e inmutable.")
            if self.abierta_por_id != original.abierta_por_id:
                raise ValidationError("El usuario de apertura es inmutable.")

            # No se puede reabrir
            if original.estado == self.Estado.CERRADA and self.estado != self.Estado.CERRADA:
                raise ValidationError("No se puede reabrir una sesión ya cerrada.")

            # Si ya estaba cerrada, no se tocan los datos de cierre
            if original.cerrada_el is not None and self.cerrada_el != original.cerrada_el:
                raise ValidationError("La fecha de cierre es automática e inmutable una vez asignada.")
            if original.cerrada_por_id is not None and self.cerrada_por_id != original.cerrada_por_id:
                raise ValidationError("El usuario de cierre es inmutable una vez asignado.")

        # Defensa adicional cuando viene update_fields desde admin/forms
        if not creating and "update_fields" in kwargs:
            u = set(kwargs.get("update_fields") or [])
            if "abierta_el" in u:
                raise ValidationError("La fecha de apertura es automática e inmutable.")
            if "cerrada_el" in u:
                ya_cerrada = type(self).objects.filter(pk=self.pk, cerrada_el__isnull=False).exists()
                if ya_cerrada:
                    raise ValidationError(
                        "La fecha de cierre es automática e inmutable una vez asignada."
                    )

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        raise ValidationError("Las sesiones de caja no pueden eliminarse (auditoría).")