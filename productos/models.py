"""
Catálogo, stock por sucursal y listas de precios del taller.

Portado del POS original sin la FK a Empresa (el taller es una sola empresa).
Cambios respecto del original:
- Producto.tipo (PRODUCTO / SERVICIO): la mano de obra es un SERVICIO, sin stock.
- Producto.controla_stock: si es False, ajustar_stock() no hace nada.
- codigo_barras opcional (único sólo cuando tiene valor).
- Se eliminó StockLote (y el campo controla_lote): no se manejan vencimientos.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

IMAGEN_MAX_MB = 5


def validar_tamano_imagen(archivo) -> None:
    if archivo and archivo.size > IMAGEN_MAX_MB * 1024 * 1024:
        raise ValidationError(f"La imagen no puede superar {IMAGEN_MAX_MB} MB.")


# ===========================
# Catálogo
# ===========================

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        ordering = ("nombre",)
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self) -> str:
        return self.nombre


class UnidadMedida(models.TextChoices):
    UN = "UN", "Unidad"
    KG = "KG", "Kilogramo"
    G = "G", "Gramo"
    LT = "LT", "Litro"
    ML = "ML", "Mililitro"
    M = "M", "Metro"
    CM = "CM", "Centímetro"
    PACK = "PACK", "Pack"
    HS = "HS", "Hora"


def ruta_imagen_producto(instance: "Producto", filename: str) -> str:
    """Ej: productos/imagenes/7791234567890.jpg o productos/imagenes/producto_15.jpg"""
    ext = (Path(filename).suffix or ".jpg").lower()
    codigo = (instance.codigo_barras or "").strip()
    codigo = "".join(c for c in codigo if c.isalnum() or c in ("-", "_"))
    if not codigo:
        codigo = f"producto_{instance.pk or 'nuevo'}"
    return f"productos/imagenes/{codigo}{ext}"


class Producto(models.Model):
    class Tipo(models.TextChoices):
        PRODUCTO = "PRODUCTO", "Producto / repuesto"
        SERVICIO = "SERVICIO", "Servicio / mano de obra"

    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PRODUCTO)
    controla_stock = models.BooleanField(
        default=True,
        help_text="Si está desactivado no se descuenta stock. Los servicios nunca controlan stock.",
    )

    categoria = models.ForeignKey(
        "Categoria",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="productos",
    )
    nombre = models.CharField(max_length=200)

    # SKU interno opcional (único si tiene valor)
    sku = models.CharField(max_length=60, blank=True, null=True)

    # Código de barras opcional (único si tiene valor)
    codigo_barras = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="EAN/UPC/GTIN. Opcional.",
    )

    unidad_medida = models.CharField(
        max_length=10,
        choices=UnidadMedida.choices,
        default=UnidadMedida.UN,
    )
    cantidad_unidad = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("1.000"),
        help_text="Cantidad/peso por unidad (para mostrar). Ej: 1.000, 0.500, 1.500",
    )

    precio_incluye_impuestos = models.BooleanField(default=True)
    iva_tasa = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("21.00"),
        help_text="IVA % (ej: 21.00, 10.50, 0.00)",
    )
    # Heredados del POS: se conservan sin uso en el taller.
    es_pesable = models.BooleanField(default=False)
    codigo_plu = models.CharField(max_length=20, blank=True, null=True)
    es_perecedero = models.BooleanField(default=False)

    vendible = models.BooleanField(default=True)
    marca = models.CharField(max_length=120, blank=True, null=True)

    imagen_url = models.URLField(blank=True, null=True)
    imagen = models.ImageField(
        upload_to=ruta_imagen_producto,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validar_tamano_imagen,
        ],
    )

    precio_base = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    activo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        permissions = [
            ("gestionar_productos", "Puede gestionar productos"),
            ("gestionar_precios", "Puede gestionar precios"),
            ("ver_costos", "Puede ver costos"),
        ]
        indexes = [
            models.Index(fields=["nombre"]),
            models.Index(fields=["tipo", "activo"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["codigo_barras"],
                condition=Q(codigo_barras__isnull=False) & ~Q(codigo_barras=""),
                name="uq_producto_codigo_barras",
            ),
            models.UniqueConstraint(
                fields=["sku"],
                condition=Q(sku__isnull=False) & ~Q(sku=""),
                name="uq_producto_sku",
            ),
            models.CheckConstraint(condition=Q(precio_base__gte=0), name="producto_precio_no_negativo"),
            models.CheckConstraint(condition=Q(iva_tasa__gte=0), name="producto_iva_no_negativo"),
            # Un servicio nunca controla stock.
            models.CheckConstraint(
                condition=~Q(tipo="SERVICIO") | Q(controla_stock=False),
                name="producto_servicio_sin_stock",
            ),
        ]
        ordering = ("nombre",)
        verbose_name = "producto"
        verbose_name_plural = "productos"

    def __str__(self) -> str:
        return self.nombre

    @property
    def es_servicio(self) -> bool:
        return self.tipo == self.Tipo.SERVICIO

    @property
    def presentacion(self) -> str:
        """Texto: '1.500 LT', '0.500 KG', '6.000 UN', etc."""
        if self.cantidad_unidad:
            return f"{self.cantidad_unidad} {self.unidad_medida}".strip()
        return self.unidad_medida or ""

    def _normalizar(self) -> None:
        """Vacíos → None (evita choques de unicidad con ''), servicio → sin stock."""
        self.codigo_barras = (self.codigo_barras or "").strip() or None
        self.sku = (self.sku or "").strip() or None
        if self.tipo == self.Tipo.SERVICIO:
            self.controla_stock = False
        if self.precio_base is None:
            self.precio_base = Decimal("0.00")

    def clean(self):
        super().clean()
        self._normalizar()

        qs = Producto.objects.exclude(pk=self.pk) if self.pk else Producto.objects.all()
        if self.codigo_barras and qs.filter(codigo_barras=self.codigo_barras).exists():
            raise ValidationError({"codigo_barras": "Ya existe un producto con este código de barras."})
        if self.sku and qs.filter(sku=self.sku).exists():
            raise ValidationError({"sku": "Ya existe un producto con este SKU."})

    def save(self, *args, **kwargs):
        self._normalizar()
        super().save(*args, **kwargs)

    @property
    def precio_vigente(self) -> Decimal:
        """
        Precio vigente:
        - Promo vigente en la lista por defecto.
        - Si no hay promo, precio NORMAL vigente de la lista por defecto.
        - Si no, precio_base.
        Si el queryset anotó `precio_vigente_anotado`, se usa sin hacer queries.
        """
        anotado = getattr(self, "precio_vigente_anotado", None)
        if anotado is not None:
            return anotado

        lista_default = ListaPrecio.objects.filter(es_default=True).order_by("id").first()
        if not lista_default:
            return self.precio_base

        ahora = timezone.now()
        precios = PrecioProducto.objects.filter(lista=lista_default, producto=self, desde__lte=ahora)

        promo = (
            precios.filter(tipo=PrecioProducto.Tipo.PROMO, hasta__isnull=False, hasta__gte=ahora)
            .order_by("-desde", "-id")
            .first()
        )
        if promo:
            return promo.precio

        normal = (
            precios.filter(tipo=PrecioProducto.Tipo.NORMAL)
            .filter(Q(hasta__isnull=True) | Q(hasta__gte=ahora))
            .order_by("-desde", "-id")
            .first()
        )
        if normal:
            return normal.precio

        return self.precio_base

    @property
    def image_src(self) -> str:
        """Imagen local si existe; si no, imagen_url; si no, '' (placeholder en el template)."""
        try:
            if self.imagen and getattr(self.imagen, "url", None):
                return self.imagen.url
        except Exception:
            pass
        return self.imagen_url or ""


# ===========================
# Stock
# ===========================

class StockSucursal(models.Model):
    producto = models.ForeignKey("productos.Producto", on_delete=models.PROTECT, related_name="stocks")
    sucursal = models.ForeignKey("core.Sucursal", on_delete=models.PROTECT, related_name="stocks_producto")

    stock = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    costo_promedio = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Costo promedio ponderado (por sucursal).",
    )

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["producto", "sucursal"], name="uq_stock_producto_sucursal"),
            models.CheckConstraint(condition=Q(stock__gte=0), name="ck_stock_no_negativo"),
            models.CheckConstraint(condition=Q(stock_minimo__gte=0), name="ck_stock_minimo_no_negativo"),
        ]
        verbose_name = "stock por sucursal"
        verbose_name_plural = "stock por sucursal"

    def __str__(self) -> str:
        return f"{self.producto} @ {self.sucursal}: {self.stock}"

    @property
    def en_rojo(self) -> bool:
        """True si está por debajo del mínimo configurado (si mínimo > 0)."""
        return self.stock_minimo > 0 and self.stock < self.stock_minimo

    def clean(self):
        super().clean()
        if self.producto_id and not self.producto.controla_stock:
            raise ValidationError({"producto": "Este producto no controla stock (o es un servicio)."})

    # ===== Helpers usados por ventas/compras =====

    @staticmethod
    def disponible(sucursal, producto) -> Decimal:
        """Stock disponible (>= 0) de un producto en una sucursal."""
        if not sucursal or not producto:
            return Decimal("0.000")
        obj = StockSucursal.objects.filter(sucursal=sucursal, producto=producto).only("stock").first()
        stock = obj.stock if (obj and obj.stock is not None) else Decimal("0.000")
        return Decimal(stock).quantize(Decimal("0.001"))

    @staticmethod
    def actualizar_costo_promedio(*, stock_obj: "StockSucursal", cantidad: Decimal, costo_unitario: Decimal) -> None:
        """Costo promedio ponderado."""
        if cantidad <= 0:
            return

        stock_viejo = stock_obj.stock
        costo_viejo = stock_obj.costo_promedio

        if stock_viejo <= 0:
            costo_nuevo = costo_unitario
        else:
            costo_nuevo = (stock_viejo * costo_viejo + cantidad * costo_unitario) / (stock_viejo + cantidad)

        stock_obj.costo_promedio = costo_nuevo.quantize(Decimal("0.0001"))
        stock_obj.save(update_fields=["costo_promedio", "updated_at"])

    @staticmethod
    def actualizar_costo_promedio_por_compra(*, sucursal, producto, cantidad, costo_unitario) -> None:
        """Wrapper para compras: asegura StockSucursal y actualiza costo con locking."""
        if cantidad is None or not producto.controla_stock:
            return

        cantidad = Decimal(str(cantidad)).quantize(Decimal("0.001"))
        costo_unitario = Decimal(str(costo_unitario)).quantize(Decimal("0.0001"))
        if cantidad <= 0:
            return

        with transaction.atomic():
            stock_obj, _ = StockSucursal.objects.select_for_update().get_or_create(
                sucursal=sucursal, producto=producto
            )
            StockSucursal.actualizar_costo_promedio(
                stock_obj=stock_obj, cantidad=cantidad, costo_unitario=costo_unitario
            )


class MovimientoStock(models.Model):
    class Tipo(models.TextChoices):
        COMPRA = "COMPRA", "Compra"
        VENTA = "VENTA", "Venta"
        AJUSTE_POSITIVO = "AJUSTE_POS", "Ajuste positivo"
        AJUSTE_NEGATIVO = "AJUSTE_NEG", "Ajuste negativo"
        DEVOLUCION_VENTA = "DEV_VENTA", "Devolución de venta"
        DEVOLUCION_COMPRA = "DEV_COMPRA", "Devolución de compra"
        INVENTARIO_INICIAL = "INV_INICIAL", "Inventario inicial"

    sucursal = models.ForeignKey("core.Sucursal", on_delete=models.PROTECT, related_name="movimientos_stock")
    producto = models.ForeignKey("productos.Producto", on_delete=models.PROTECT, related_name="movimientos_stock")

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    # Se guarda la magnitud; el tipo indica si suma o resta.
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    stock_anterior = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    stock_nuevo = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))

    referencia_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    referencia_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    referencia = GenericForeignKey("referencia_content_type", "referencia_object_id")

    descripcion = models.CharField(max_length=255, blank=True, default="")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_stock_creados",
    )
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["sucursal", "producto", "fecha"])]
        ordering = ("-fecha", "-id")
        verbose_name = "movimiento de stock"
        verbose_name_plural = "movimientos de stock"

    def __str__(self) -> str:
        return (
            f"[{self.fecha:%Y-%m-%d %H:%M}] {self.sucursal} / {self.producto} | "
            f"{self.tipo} | {self.cantidad} ({self.stock_anterior} → {self.stock_nuevo})"
        )


def ajustar_stock(*, sucursal, producto, delta, tipo: str, referencia=None, usuario=None, descripcion: str = ""):
    """
    Ajusta el stock de (sucursal, producto) en `delta` y registra un MovimientoStock.

    - delta > 0 suma, delta < 0 resta. Nunca deja stock negativo.
    - Si el producto no controla stock (o es servicio) no hace nada y devuelve None.
    - Concurrencia segura con select_for_update().
    Devuelve el MovimientoStock creado (o None).
    """
    if not producto.controla_stock:
        return None

    delta = Decimal(str(delta)).quantize(Decimal("0.001"))
    if delta == 0:
        return None

    with transaction.atomic():
        stock_obj, _ = StockSucursal.objects.select_for_update().get_or_create(
            sucursal=sucursal, producto=producto
        )

        stock_anterior = stock_obj.stock
        stock_nuevo = (stock_anterior + delta).quantize(Decimal("0.001"))
        if stock_nuevo < 0:
            raise ValidationError(
                f"El stock de {producto} en {sucursal} quedaría negativo ({stock_anterior} → {stock_nuevo})."
            )

        stock_obj.stock = stock_nuevo
        stock_obj.save(update_fields=["stock", "updated_at"])

        ref_ct = ref_id = None
        if referencia is not None:
            ref_ct = ContentType.objects.get_for_model(referencia.__class__)
            ref_id = referencia.pk

        return MovimientoStock.objects.create(
            sucursal=sucursal,
            producto=producto,
            tipo=tipo,
            cantidad=abs(delta),
            stock_anterior=stock_anterior,
            stock_nuevo=stock_nuevo,
            referencia_content_type=ref_ct,
            referencia_object_id=ref_id,
            descripcion=(descripcion or "")[:255],
            creado_por=usuario,
        )


# ===========================
# Listas de precios
# ===========================

class ListaPrecio(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    es_default = models.BooleanField(
        default=False,
        help_text="Lista por defecto para ventas si no hay otra configurada.",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["es_default"],
                condition=Q(es_default=True),
                name="uq_lista_precio_default_unica",
            )
        ]
        ordering = ("nombre",)
        verbose_name = "lista de precio"
        verbose_name_plural = "listas de precios"

    def __str__(self) -> str:
        return self.nombre

    def save(self, *args, **kwargs):
        """Si esta lista pasa a ser la default, las demás dejan de serlo."""
        with transaction.atomic():
            if self.es_default:
                ListaPrecio.objects.filter(es_default=True).exclude(pk=self.pk).update(es_default=False)
            super().save(*args, **kwargs)


class PrecioProducto(models.Model):
    class Tipo(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        PROMO = "PROMO", "Promoción"

    lista = models.ForeignKey("productos.ListaPrecio", on_delete=models.CASCADE, related_name="precios")
    producto = models.ForeignKey("productos.Producto", on_delete=models.PROTECT, related_name="precios")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.NORMAL)
    precio = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    desde = models.DateTimeField(default=timezone.now, help_text="Desde cuándo rige el precio.")
    hasta = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fin de vigencia. Vacío = vigente hasta nuevo aviso (las PROMO deben tener fin).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-desde", "-id")
        indexes = [models.Index(fields=["lista", "producto", "desde"])]
        constraints = [
            models.CheckConstraint(condition=Q(precio__gte=0), name="precio_producto_no_negativo"),
        ]
        verbose_name = "precio de producto"
        verbose_name_plural = "precios de productos"

    def __str__(self):
        return f"{self.producto} [{self.lista}] = {self.precio} desde {self.desde}"

    def clean(self):
        super().clean()

        if not self.lista_id:
            raise ValidationError("Debe seleccionar una lista.")
        if not self.producto_id or not self.desde:
            return

        if self.hasta and self.hasta < self.desde:
            raise ValidationError("La fecha de fin no puede ser anterior a la fecha de inicio.")

        if self.tipo == self.Tipo.PROMO and not self.hasta:
            raise ValidationError("Las promociones deben tener fecha de fin.")

        if self.tipo == self.Tipo.NORMAL and self.lista.es_default and self.hasta is not None:
            raise ValidationError("El precio NORMAL de la lista base no puede tener fecha de fin.")

        # Solapamientos
        if self.tipo == self.Tipo.NORMAL:
            qs = PrecioProducto.objects.filter(
                lista=self.lista, producto=self.producto, tipo=self.Tipo.NORMAL
            ).exclude(pk=self.pk)
            qs = qs.filter(Q(hasta__isnull=True) | Q(hasta__gte=self.desde))
            if self.hasta:
                qs = qs.filter(desde__lte=self.hasta)
            if qs.exists():
                raise ValidationError(
                    "Ya existe otro precio NORMAL para este producto en un rango de fechas que se solapa."
                )

        if self.tipo == self.Tipo.PROMO:
            qs = PrecioProducto.objects.filter(producto=self.producto, tipo=self.Tipo.PROMO).exclude(pk=self.pk)
            qs = qs.filter(Q(hasta__isnull=True) | Q(hasta__gte=self.desde), desde__lte=self.hasta)
            if qs.exists():
                raise ValidationError("Ya existe otra PROMO para este producto en un rango de fechas que se solapa.")

    @property
    def esta_activo(self) -> bool:
        ahora = timezone.now()
        if self.hasta:
            return self.desde <= ahora <= self.hasta
        return self.desde <= ahora
