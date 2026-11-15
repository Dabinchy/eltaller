"""
Admin de ventas (sólo lectura).

Las ventas se crean desde la caja y, más adelante, desde las órdenes del taller.
- Quien no es gerente sólo ve las ventas de su sucursal.
- Costo y utilidad sólo con productos.ver_costos.
- Acción "Anular" sólo con ventas.anular_venta.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from core.admin import _es_gerente, _filtrar_por_sucursal

from .models import Venta, VentaDetalle

CAMPOS_COSTO = ("costo_total", "utilidad_bruta")
CAMPOS_COSTO_DETALLE = ("costo_unitario", "costo_total")


def _puede_ver_costos(user) -> bool:
    return user.is_superuser or user.has_perm("productos.ver_costos")


class VentaDetalleInline(admin.TabularInline):
    model = VentaDetalle
    extra = 0
    can_delete = False

    def get_fields(self, request, obj=None):
        campos = ["producto", "cantidad", "precio_unitario", "alicuota_iva", "importe"]
        if _puede_ver_costos(request.user):
            campos += list(CAMPOS_COSTO_DETALLE)
        return campos

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.action(description="Anular ventas seleccionadas")
def anular_ventas(modeladmin, request, queryset):
    ok = 0
    for venta in queryset:
        try:
            venta.anular(user=request.user)
            ok += 1
        except (ValidationError, PermissionDenied) as e:
            texto = "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)
            modeladmin.message_user(request, f"Venta #{venta.pk}: {texto}", messages.ERROR)
    if ok:
        modeladmin.message_user(request, f"{ok} venta(s) anulada(s).", messages.SUCCESS)


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    search_fields = ("id", "cliente__nombre", "cliente__doc_numero")
    date_hierarchy = "creada_el"
    list_select_related = ("sucursal", "caja", "cliente")
    inlines = [VentaDetalleInline]
    actions = [anular_ventas]

    def get_list_display(self, request):
        cols = ["id", "creada_el", "sucursal", "caja", "cliente", "estado", "total_items", "total"]
        if _puede_ver_costos(request.user):
            cols += list(CAMPOS_COSTO)
        return cols

    def get_list_filter(self, request):
        if _es_gerente(request.user):
            return ("estado", "sucursal")
        return ("estado",)

    def get_fieldsets(self, request, obj=None):
        totales = ["total_items", "total", "importe_neto_gravado", "importe_iva"]
        if _puede_ver_costos(request.user):
            totales += list(CAMPOS_COSTO)
        return (
            (None, {"fields": ("estado", "sucursal", "caja", "sesion", "cliente", "observacion")}),
            ("Totales", {"fields": totales}),
            ("Medios de pago", {"fields": ("monto_efectivo", "monto_tarjeta", "monto_transferencia", "monto_ctacte")}),
            (
                "Seguimiento",
                {"fields": ("creada_el", "creada_por", "finalizada_el", "finalizada_por", "anulada_el", "anulada_por")},
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        return [f for fs in self.get_fieldsets(request, obj) for f in fs[1]["fields"]]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        if not (request.user.is_superuser or request.user.has_perm("ventas.anular_venta")):
            actions.pop("anular_ventas", None)
        return actions

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
