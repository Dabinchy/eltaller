"""
Taller: vehículos, técnicos, turnos y órdenes de trabajo.

Flujo de la orden:
    PRESUPUESTO → APROBADA → EN_PROCESO → TERMINADA → ENTREGADA
    (TERMINADA puede volver a EN_PROCESO; cualquiera antes de ENTREGADA → CANCELADA)

- Al aprobar el presupuesto se aprueban todos sus ítems; lo que se agregue después queda
  pendiente hasta que alguien con taller.aprobar_items lo apruebe.
- Al entregar se genera una Venta ABIERTA con los ítems aprobados; el cobro (y el descuento
  de stock) se hace al finalizar esa venta en caja.
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import Max, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import SesionCaja, Sucursal

from . import permisos

CERO = Decimal("0.00")


def _q2(valor) -> Decimal:
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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

    """
    Ficha OPERATIVA del vehículo en el taller (patente, VIN, km, dueño).
    La presentación pública del auto (número, categoría, fotos, descripción) vive en el
    portal (portal.Auto), que puede vincularse a esta ficha cuando el auto entra al taller.
    """

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="vehiculos",
        help_text="Dueño actual del vehículo.",
    )
    patente = models.CharField(
        max_length=15, blank=True, default="",
        help_text="Opcional (muchos autos de carrera no tienen). Mayúsculas, sin espacios ni guiones.",
    )
    marca = models.CharField(max_length=60)
    modelo = models.CharField(max_length=80)
    anio = models.PositiveSmallIntegerField("año", null=True, blank=True, validators=[MinValueValidator(1900)])
    vin = models.CharField("VIN / chasis", max_length=30, blank=True, default="")
    combustible = models.CharField(max_length=10, choices=Combustible.choices, default=Combustible.NAFTA)
    km_actual = models.PositiveIntegerField("km actual", default=0)

    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("patente",)
        indexes = [models.Index(fields=["cliente"]), models.Index(fields=["marca", "modelo"])]
        constraints = [
            models.UniqueConstraint(
                fields=["patente"],
                condition=~Q(patente=""),
                name="uq_vehiculo_patente_no_vacia",
                violation_error_message="Ya existe un vehículo con esta patente.",
            ),
            models.UniqueConstraint(
                fields=["vin"],
                condition=~Q(vin=""),
                name="uq_vehiculo_vin_no_vacio",
                violation_error_message="Ya existe un vehículo con este VIN.",
            ),
            models.CheckConstraint(
                condition=~Q(patente="") | ~Q(vin=""),
                name="ck_vehiculo_patente_o_vin",
                violation_error_message="Cargá la patente o el VIN / chasis.",
            ),
        ]
        verbose_name = "vehículo"
        verbose_name_plural = "vehículos"

    def __str__(self) -> str:
        return f"{self.identificacion} · {self.marca} {self.modelo}"

    @property
    def identificacion(self) -> str:
        """Patente, o el VIN si no tiene patente."""
        return self.patente or f"VIN {self.vin}"

    def _normalizar(self) -> None:
        self.patente = _normalizar_codigo(self.patente)
        self.vin = _normalizar_codigo(self.vin)

    def clean(self):
        super().clean()
        self._normalizar()
        if not self.patente and not self.vin:
            raise ValidationError("Cargá la patente o el VIN / chasis.")
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
        if self.usuario_id and getattr(self.usuario, "es_portal", False):
            raise ValidationError({"usuario": "Un usuario del portal no puede ser técnico."})

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


# ===========================
# Orden de trabajo
# ===========================

class OrdenTrabajo(models.Model):
    class Estado(models.TextChoices):
        PRESUPUESTO = "PRESUPUESTO", "Presupuesto"
        APROBADA = "APROBADA", "Aprobada"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        TERMINADA = "TERMINADA", "Terminada"
        ENTREGADA = "ENTREGADA", "Entregada"
        CANCELADA = "CANCELADA", "Cancelada"

    E = Estado
    # Pasos permitidos con cambiar_estado(). ENTREGADA sólo se alcanza con entregar().
    TRANSICIONES = {
        E.PRESUPUESTO: {E.APROBADA, E.CANCELADA},
        E.APROBADA: {E.EN_PROCESO, E.CANCELADA},
        E.EN_PROCESO: {E.TERMINADA, E.CANCELADA},
        E.TERMINADA: {E.EN_PROCESO, E.CANCELADA},
        E.ENTREGADA: set(),
        E.CANCELADA: set(),
    }
    # Pasos que puede dar el mecánico asignado (empezar y terminar su trabajo).
    PASOS_MECANICO = {(E.APROBADA, E.EN_PROCESO), (E.EN_PROCESO, E.TERMINADA)}
    ESTADOS_FINALES = (E.ENTREGADA, E.CANCELADA)
    # Estados en los que se pueden cargar o cambiar ítems.
    ESTADOS_EDITABLES = (E.PRESUPUESTO, E.APROBADA, E.EN_PROCESO)

    sucursal = models.ForeignKey(Sucursal, on_delete=models.PROTECT, related_name="ordenes")
    numero = models.PositiveIntegerField("número", unique=True, editable=False)
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.PROTECT, related_name="ordenes", blank=True,
        help_text="Titular al ingreso. Si se deja vacío, se toma el dueño del vehículo.",
    )
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name="ordenes")
    tecnico = models.ForeignKey(
        Tecnico, on_delete=models.PROTECT, null=True, blank=True, related_name="ordenes",
        help_text="Técnico asignado (ve la orden desde su usuario).",
    )
    turno = models.OneToOneField(
        Turno, on_delete=models.PROTECT, null=True, blank=True, related_name="orden",
    )
    venta = models.OneToOneField(
        "ventas.Venta", on_delete=models.PROTECT, null=True, blank=True, related_name="orden", editable=False,
    )
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PRESUPUESTO, editable=False)

    km_ingreso = models.PositiveIntegerField("km al ingreso", null=True, blank=True)
    fecha_ingreso = models.DateTimeField(default=timezone.now)
    fecha_prometida = models.DateTimeField(null=True, blank=True)
    fecha_egreso = models.DateTimeField(null=True, blank=True, editable=False)
    motivo_cliente = models.TextField("motivo del cliente", blank=True)
    diagnostico = models.TextField("diagnóstico", blank=True)

    # Totales de los ítems APROBADOS
    total_repuestos = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    total_mano_obra = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)

    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="ordenes_creadas", editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("-numero",)
        indexes = [models.Index(fields=["sucursal", "estado"]), models.Index(fields=["vehiculo"])]
        permissions = [
            ("aprobar_items", "Puede aprobar ítems de órdenes"),
            ("cambiar_estado_orden", "Puede cambiar cualquier estado de una orden"),
            ("trabajar_orden", "Puede empezar y terminar el trabajo de sus órdenes asignadas"),
            ("entregar_orden", "Puede entregar órdenes (genera la venta)"),
            ("cancelar_orden", "Puede cancelar órdenes"),
        ]
        verbose_name = "orden de trabajo"
        verbose_name_plural = "órdenes de trabajo"

    def __str__(self) -> str:
        return f"OT #{self.numero} · {self.vehiculo.identificacion} · {self.get_estado_display()}"

    @property
    def total_presupuestado(self) -> Decimal:
        """Suma de TODOS los ítems (aprobados o no)."""
        return _q2(self.items.aggregate(t=Coalesce(Sum("importe"), CERO))["t"])

    def clean(self):
        super().clean()
        if self.vehiculo_id and not self.cliente_id:
            self.cliente_id = self.vehiculo.cliente_id
        if self.turno_id:
            if self.turno.vehiculo_id != self.vehiculo_id:
                raise ValidationError({"turno": "El turno es de otro vehículo."})
            if self.turno.sucursal_id != self.sucursal_id:
                raise ValidationError({"turno": "El turno es de otra sucursal."})
        if self.tecnico_id and not self.tecnico.activo:
            anterior = OrdenTrabajo.objects.filter(pk=self.pk).values_list("tecnico_id", flat=True).first()
            if anterior != self.tecnico_id:
                raise ValidationError({"tecnico": "El técnico está inactivo."})

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields"):
            return super().save(*args, **kwargs)  # cambios internos (estado, totales, venta)

        nueva = self.pk is None
        if not nueva:
            estado = OrdenTrabajo.objects.filter(pk=self.pk).values_list("estado", flat=True).first()
            if estado in self.ESTADOS_FINALES:
                raise ValidationError("Una orden entregada o cancelada no se puede modificar.")

        self.full_clean(exclude=["numero"])
        if nueva:
            self._crear_con_numero(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
        self.vehiculo.registrar_km(self.km_ingreso)

    def _crear_con_numero(self, *args, **kwargs) -> None:
        """Número correlativo global; reintenta si otro proceso tomó el mismo número."""
        for _ in range(5):
            try:
                with transaction.atomic():
                    self.numero = (OrdenTrabajo.objects.aggregate(m=Max("numero"))["m"] or 0) + 1
                    super().save(*args, **kwargs)
                    OrdenEstadoLog.objects.create(
                        orden=self, estado_anterior="", estado_nuevo=self.estado, usuario=self.creada_por
                    )
                    if self.turno_id:
                        Turno.objects.filter(pk=self.turno_id).update(estado=Turno.Estado.EN_TALLER)
                return
            except IntegrityError:
                self.pk = None
                continue
        raise ValidationError("No se pudo asignar un número de orden. Reintentá.")

    def recalcular_totales(self) -> None:
        aprobados = self.items.filter(aprobado=True)
        rep = aprobados.filter(producto__tipo="PRODUCTO").aggregate(t=Coalesce(Sum("importe"), CERO))["t"]
        mo = aprobados.filter(producto__tipo="SERVICIO").aggregate(t=Coalesce(Sum("importe"), CERO))["t"]
        self.total_repuestos, self.total_mano_obra = _q2(rep), _q2(mo)
        self.total = _q2(self.total_repuestos + self.total_mano_obra)
        OrdenTrabajo.objects.filter(pk=self.pk).update(
            total_repuestos=self.total_repuestos, total_mano_obra=self.total_mano_obra,
            total=self.total, updated_at=timezone.now(),
        )

    # ------------ operaciones de negocio ------------

    def _verificar_alcance(self, user) -> None:
        if not permisos.puede_operar(user, self):
            raise PermissionDenied("Esta orden no está dentro de su alcance.")

    def _registrar_estado(self, nuevo: str, user, campos=()) -> None:
        anterior = self.estado
        self.estado = nuevo
        self.save(update_fields=["estado", "updated_at", *campos])
        OrdenEstadoLog.objects.create(orden=self, estado_anterior=anterior, estado_nuevo=nuevo, usuario=user)

    def cambiar_estado(self, nuevo: str, *, user) -> "OrdenTrabajo":
        """Cambia el estado respetando TRANSICIONES y los permisos de cada paso."""
        with transaction.atomic():
            orden = OrdenTrabajo.objects.select_for_update().get(pk=self.pk)
            orden._verificar_alcance(user)

            if nuevo == self.E.ENTREGADA:
                raise ValidationError("Para entregar usá 'Entregar' (genera la venta).")
            if nuevo not in self.TRANSICIONES[orden.estado]:
                raise ValidationError(
                    f"No se puede pasar de {orden.get_estado_display()} a {self.Estado(nuevo).label}."
                )

            if nuevo == self.E.CANCELADA:
                permitido = user.has_perm(permisos.PERM_CANCELAR)
            elif (orden.estado, nuevo) in self.PASOS_MECANICO:
                permitido = user.has_perm(permisos.PERM_CAMBIAR_ESTADO) or user.has_perm(permisos.PERM_TRABAJAR)
            else:
                permitido = user.has_perm(permisos.PERM_CAMBIAR_ESTADO)
            if not (user.is_superuser or permitido):
                raise PermissionDenied("No tiene permiso para ese cambio de estado.")

            if nuevo == self.E.APROBADA:
                if not orden.items.exists():
                    raise ValidationError("El presupuesto no tiene ítems.")
                orden.items.update(aprobado=True)
                orden.recalcular_totales()

            orden._registrar_estado(nuevo, user)

        self.refresh_from_db()
        return self

    def aprobar_items(self, *, user) -> int:
        """Aprueba los ítems pendientes (agregados después del presupuesto)."""
        if not (user.is_superuser or user.has_perm(permisos.PERM_APROBAR_ITEMS)):
            raise PermissionDenied("No tiene permiso para aprobar ítems.")
        self._verificar_alcance(user)
        if self.estado not in self.ESTADOS_EDITABLES:
            raise ValidationError("La orden ya no admite cambios en sus ítems.")
        n = self.items.filter(aprobado=False).update(aprobado=True)
        self.recalcular_totales()
        return n

    def entregar(self, *, user, sesion: SesionCaja):
        """
        TERMINADA → ENTREGADA: genera una Venta ABIERTA en la sesión de caja indicada,
        con los ítems aprobados (respetando precio y costo de cada uno).
        """
        from ventas.models import Venta, VentaDetalle  # taller → ventas (nunca al revés)

        if not (user.is_superuser or user.has_perm(permisos.PERM_ENTREGAR)):
            raise PermissionDenied("No tiene permiso para entregar órdenes.")

        with transaction.atomic():
            orden = OrdenTrabajo.objects.select_for_update().select_related("sucursal", "cliente").get(pk=self.pk)
            orden._verificar_alcance(user)
            if orden.estado != self.E.TERMINADA:
                raise ValidationError("Sólo se pueden entregar órdenes TERMINADAS.")
            sesion = SesionCaja.objects.select_related("caja").get(pk=sesion.pk)
            if sesion.estado != SesionCaja.Estado.ABIERTA:
                raise ValidationError("La sesión de caja no está abierta.")
            if sesion.caja.sucursal_id != orden.sucursal_id:
                raise ValidationError("La caja es de otra sucursal.")
            aprobados = list(orden.items.filter(aprobado=True).select_related("producto"))
            if not aprobados:
                raise ValidationError("La orden no tiene ítems aprobados para facturar.")

            venta = Venta.objects.create(
                sucursal=orden.sucursal, caja=sesion.caja, sesion=sesion, cliente=orden.cliente,
                creada_por=user, observacion=f"Orden de trabajo #{orden.numero}",
            )
            for item in aprobados:
                VentaDetalle.objects.create(
                    venta=venta, producto=item.producto, cantidad=item.cantidad,
                    precio_unitario=item.precio_unitario, costo_unitario=item.costo_unitario,
                    descripcion_afip=item.descripcion[:200],
                )

            orden.venta = venta
            orden.fecha_egreso = timezone.now()
            orden._registrar_estado(self.E.ENTREGADA, user, campos=("venta", "fecha_egreso"))

        self.refresh_from_db()
        return venta


class OrdenItem(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey("productos.Producto", on_delete=models.PROTECT, related_name="items_orden")
    tecnico = models.ForeignKey(Tecnico, on_delete=models.PROTECT, null=True, blank=True, related_name="items")
    descripcion = models.CharField("descripción", max_length=200, blank=True, help_text="Vacío = nombre del producto.")
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1.000"))
    precio_unitario = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text="Vacío = precio vigente del producto. 0 = sin cargo.",
    )
    costo_unitario = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
        help_text="Vacío = costo promedio de la sucursal.",
    )
    importe = models.DecimalField(max_digits=14, decimal_places=2, default=CERO, editable=False)
    aprobado = models.BooleanField(default=False, editable=False)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("orden", "id")
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ordenitem_cantidad_positiva"),
            models.CheckConstraint(condition=Q(precio_unitario__gte=0), name="ordenitem_precio_no_negativo"),
        ]
        verbose_name = "ítem de orden"
        verbose_name_plural = "ítems de orden"

    def __str__(self) -> str:
        return f"OT #{self.orden.numero} · {self.descripcion or self.producto} x {self.cantidad}"

    @property
    def stock_disponible(self) -> Decimal | None:
        """Stock del producto en la sucursal de la orden (None si no controla stock)."""
        if not self.producto.controla_stock:
            return None
        from productos.models import StockSucursal

        return StockSucursal.disponible(self.orden.sucursal, self.producto)

    @property
    def falta_stock(self) -> bool:
        disponible = self.stock_disponible
        return disponible is not None and disponible < self.cantidad

    def _verificar_orden_editable(self) -> None:
        estado = OrdenTrabajo.objects.filter(pk=self.orden_id).values_list("estado", flat=True).first()
        if estado and estado not in OrdenTrabajo.ESTADOS_EDITABLES:
            raise ValidationError("La orden ya no admite cambios en sus ítems.")

    def clean(self):
        super().clean()
        if not self.producto_id:
            return
        producto = self.producto
        if not producto.activo:
            raise ValidationError({"producto": "El producto está inactivo."})
        if self.cantidad is not None and self.cantidad <= 0:
            raise ValidationError({"cantidad": "La cantidad debe ser mayor que 0."})

        self.descripcion = (self.descripcion or "").strip() or producto.nombre[:200]
        if self.precio_unitario is None:
            self.precio_unitario = _q2(producto.precio_vigente)
        if self.costo_unitario is None:
            costo = Decimal("0")
            if producto.controla_stock and self.orden_id:
                from productos.models import StockSucursal

                costo = (
                    StockSucursal.objects.filter(sucursal_id=self.orden.sucursal_id, producto=producto)
                    .values_list("costo_promedio", flat=True).first() or Decimal("0")
                )
            self.costo_unitario = costo
        self.importe = _q2((self.precio_unitario or 0) * (self.cantidad or 0))

    def save(self, *args, **kwargs):
        self._verificar_orden_editable()
        if self.pk and self.aprobado:
            # Si cambia lo que se aprobó, vuelve a quedar pendiente de aprobación.
            antes = OrdenItem.objects.filter(pk=self.pk).values("producto_id", "cantidad", "precio_unitario").first()
            if antes and (antes["producto_id"], antes["cantidad"], antes["precio_unitario"]) != (
                self.producto_id, self.cantidad, self.precio_unitario
            ):
                self.aprobado = False
        self.full_clean()
        super().save(*args, **kwargs)
        self.orden.recalcular_totales()

    def delete(self, *args, **kwargs):
        self._verificar_orden_editable()
        orden = self.orden
        resultado = super().delete(*args, **kwargs)
        orden.recalcular_totales()
        return resultado


class OrdenEstadoLog(models.Model):
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="historial")
    estado_anterior = models.CharField(max_length=12, blank=True)
    estado_nuevo = models.CharField(max_length=12)
    fecha = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ("fecha", "id")
        verbose_name = "cambio de estado"
        verbose_name_plural = "historial de estados"

    def __str__(self) -> str:
        return f"OT #{self.orden.numero}: {self.estado_anterior or '-'} -> {self.estado_nuevo}"
