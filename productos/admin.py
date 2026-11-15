"""
Admin de productos.

- El catálogo (productos, categorías, listas y precios) es único para todo el taller.
- Stock y movimientos son por sucursal: quien no es gerente sólo ve su sucursal fija.
- Los costos sólo los ve quien tiene productos.ver_costos (gerente y jefe).
- El precio sólo lo cambia quien tiene productos.gestionar_precios (gerente).
- El stock no se edita "a mano": cada cambio desde el admin genera un MovimientoStock.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib import admin, messages

from core.admin import _es_gerente, _filtrar_por_sucursal, _verificar_sucursal_o_403
from core.models import Sucursal

from .models import (
    Categoria,
    ListaPrecio,
    MovimientoStock,
    PrecioProducto,
    Producto,
    StockSucursal,
    ajustar_stock,
)

PERM_VER_COSTOS = "productos.ver_costos"
PERM_GESTIONAR_PRECIOS = "productos.gestionar_precios"


def _puede_ver_costos(user) -> bool:
    return user.is_superuser or user.has_perm(PERM_VER_COSTOS)


def _puede_gestionar_precios(user) -> bool:
    return user.is_superuser or user.has_perm(PERM_GESTIONAR_PRECIOS)


class _SinBorradoMixin:
    """Borrado físico sólo para superusuario (lo normal es desactivar)."""

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================
# Categorías
# ============================================================

@admin.register(Categoria)
class CategoriaAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = ("nombre", "activo", "created_at")
    list_filter = ("activo",)
    search_fields = ("nombre",)
    readonly_fields = ("created_at", "updated_at")


# ============================================================
# Productos
# ============================================================

@admin.action(description="Desactivar productos seleccionados")
def desactivar_productos(modeladmin, request, queryset):
    n = queryset.update(activo=False)
    modeladmin.message_user(request, f"{n} producto(s) desactivado(s).", messages.SUCCESS)


@admin.action(description="Activar productos seleccionados")
def activar_productos(modeladmin, request, queryset):
    n = queryset.update(activo=True)
    modeladmin.message_user(request, f"{n} producto(s) activado(s).", messages.SUCCESS)


class PrecioProductoInline(admin.TabularInline):
    model = PrecioProducto
    extra = 0
    fields = ("lista", "tipo", "precio", "desde", "hasta")

    def _puede(self, request):
        return _puede_gestionar_precios(request.user)

    def has_add_permission(self, request, obj=None):
        return self._puede(request)

    def has_change_permission(self, request, obj=None):
        return self._puede(request)

    def has_delete_permission(self, request, obj=None):
        return self._puede(request)


class StockSucursalInline(admin.TabularInline):
    """Stock del producto (sólo lectura; se carga desde 'Stock por sucursal')."""

    model = StockSucursal
    extra = 0
    can_delete = False
    verbose_name_plural = "stock por sucursal"

    def get_fields(self, request, obj=None):
        campos = ["sucursal", "stock", "stock_minimo"]
        if _puede_ver_costos(request.user):
            campos.append("costo_promedio")
        return campos

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("sucursal")
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Producto)
class ProductoAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = (
        "nombre", "tipo", "codigo_barras", "sku", "marca", "categoria",
        "precio_base", "controla_stock", "activo",
    )
    list_filter = ("tipo", "controla_stock", "activo", "categoria")
    search_fields = ("nombre", "codigo_barras", "sku", "marca")
    list_select_related = ("categoria",)
    actions = [activar_productos, desactivar_productos]
    fieldsets = (
        (None, {"fields": ("tipo", "nombre", "categoria", "marca", "activo", "vendible")}),
        ("Códigos", {"fields": ("codigo_barras", "sku")}),
        ("Stock y unidad", {"fields": ("controla_stock", "unidad_medida", "cantidad_unidad")}),
        ("Precio e impuestos", {"fields": ("precio_base", "precio_incluye_impuestos", "iva_tasa")}),
        ("Imagen", {"fields": ("imagen", "imagen_url")}),
        (
            "Heredados del POS (sin uso)",
            {"classes": ("collapse",), "fields": ("es_pesable", "codigo_plu", "es_perecedero")},
        ),
        ("Auditoría", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        campos = ["created_at", "updated_at"]
        if not _puede_gestionar_precios(request.user):
            campos.append("precio_base")
        return campos

    def get_inlines(self, request, obj):
        inlines = [PrecioProductoInline]
        if obj and obj.controla_stock:
            inlines.append(StockSucursalInline)
        return inlines

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("delete_selected", None)
        if not self.has_change_permission(request):
            actions.pop("activar_productos", None)
            actions.pop("desactivar_productos", None)
        return actions


# ============================================================
# Listas de precios y precios
# ============================================================

@admin.register(ListaPrecio)
class ListaPrecioAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = ("nombre", "es_default", "created_at")
    list_filter = ("es_default",)
    search_fields = ("nombre",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(PrecioProducto)
class PrecioProductoAdmin(admin.ModelAdmin):
    list_display = ("producto", "lista", "tipo", "precio", "desde", "hasta", "esta_activo")
    list_filter = ("tipo", "lista")
    search_fields = ("producto__nombre", "producto__codigo_barras", "lista__nombre")
    list_select_related = ("producto", "lista")
    autocomplete_fields = ("producto",)
    date_hierarchy = "desde"
    ordering = ("-desde",)

    @admin.display(boolean=True, description="Vigente")
    def esta_activo(self, obj):
        return obj.esta_activo


# ============================================================
# Stock por sucursal
# ============================================================

class StockEnRojoFilter(admin.SimpleListFilter):
    title = "bajo el mínimo"
    parameter_name = "en_rojo"

    def lookups(self, request, model_admin):
        return (("si", "Sí"),)

    def queryset(self, request, queryset):
        from django.db.models import F

        if self.value() == "si":
            return queryset.filter(stock_minimo__gt=0, stock__lt=F("stock_minimo"))
        return queryset


@admin.register(StockSucursal)
class StockSucursalAdmin(_SinBorradoMixin, admin.ModelAdmin):
    search_fields = ("producto__nombre", "producto__codigo_barras", "producto__sku")
    autocomplete_fields = ("producto",)

    # --- Columnas y campos según permisos ---

    def get_list_display(self, request):
        cols = ["producto", "sucursal", "stock", "stock_minimo", "en_rojo"]
        if _puede_ver_costos(request.user):
            cols.append("costo_promedio")
        return cols

    def get_list_filter(self, request):
        if _es_gerente(request.user):
            return (StockEnRojoFilter, "sucursal", "producto__categoria")
        return (StockEnRojoFilter, "producto__categoria")

    def get_fields(self, request, obj=None):
        campos = ["producto", "sucursal", "stock", "stock_minimo"]
        if _puede_ver_costos(request.user):
            campos.append("costo_promedio")
        return campos

    def get_readonly_fields(self, request, obj=None):
        # El costo lo calcula compras; producto y sucursal no se cambian una vez creados.
        campos = ["costo_promedio"]
        if obj:
            campos += ["producto", "sucursal"]
        return campos

    @admin.display(boolean=True, description="Bajo mínimo")
    def en_rojo(self, obj):
        return obj.en_rojo

    # --- Alcance por sucursal ---

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("producto", "sucursal", "producto__categoria")
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal":
            kwargs["queryset"] = _filtrar_por_sucursal(Sucursal.objects.all(), request.user, "pk")
        elif db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(controla_stock=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # --- Guardado: el stock siempre pasa por ajustar_stock() ---

    def save_model(self, request, obj, form, change):
        _verificar_sucursal_o_403(request.user, obj.sucursal_id)

        nuevo = form.cleaned_data.get("stock")
        if nuevo is None:
            nuevo = obj.stock
        anterior = (
            StockSucursal.objects.filter(pk=obj.pk).values_list("stock", flat=True).first()
            if change else Decimal("0.000")
        )

        obj.stock = anterior  # se guarda sin tocar el stock...
        super().save_model(request, obj, form, change)

        delta = nuevo - anterior  # ...y la diferencia se registra como movimiento
        if delta:
            if not change:
                tipo = MovimientoStock.Tipo.INVENTARIO_INICIAL
            elif delta > 0:
                tipo = MovimientoStock.Tipo.AJUSTE_POSITIVO
            else:
                tipo = MovimientoStock.Tipo.AJUSTE_NEGATIVO
            ajustar_stock(
                sucursal=obj.sucursal,
                producto=obj.producto,
                delta=delta,
                tipo=tipo,
                usuario=request.user,
                descripcion="Ajuste manual desde el admin",
            )
            obj.refresh_from_db()


# ============================================================
# Movimientos de stock (sólo lectura)
# ============================================================

@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ("fecha", "sucursal", "producto", "tipo", "cantidad", "stock_anterior", "stock_nuevo", "creado_por")
    list_filter = ("tipo", "sucursal")
    search_fields = ("producto__nombre", "producto__codigo_barras", "descripcion")
    list_select_related = ("sucursal", "producto", "creado_por")
    date_hierarchy = "fecha"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields] + ["referencia"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
