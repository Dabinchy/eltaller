"""
Admin de compras.

- Proveedores: alta y edición; borrado físico sólo superusuario.
- Compras: editables con sus ítems mientras están en BORRADOR; después, sólo lectura.
  Acciones "Confirmar" (registrar_compras) y "Anular" (anular_compras).
- Quien no es gerente sólo ve y carga compras de su sucursal.
- El adjunto es privado: el admin muestra el nombre del archivo, nunca un link.
"""
from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from core.admin import _es_gerente, _filtrar_por_sucursal, _verificar_sucursal_o_403
from core.models import Sucursal

from .models import Compra, CompraDetalle, Proveedor


def _mensaje(e: Exception) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


# ============================================================
# Proveedores
# ============================================================

@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "documento", "telefono", "email", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "documento", "email", "telefono")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ============================================================
# Compras
# ============================================================

def _es_borrador(obj) -> bool:
    return obj is None or obj.estado == Compra.Estado.BORRADOR


class CompraDetalleInline(admin.TabularInline):
    model = CompraDetalle
    extra = 1
    fields = ("producto", "cantidad", "costo_unitario", "iva_tasa", "subtotal", "iva_total", "total")
    readonly_fields = ("subtotal", "iva_total", "total")
    autocomplete_fields = ("producto",)

    def has_add_permission(self, request, obj=None):
        return _es_borrador(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return _es_borrador(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return _es_borrador(obj) and super().has_delete_permission(request, obj)


class CompraAdminForm(forms.ModelForm):
    class Meta:
        model = Compra
        fields = ("proveedor", "sucursal", "fecha", "observaciones", "documento_adjunto")
        # FileInput simple: el ClearableFileInput intentaría armar un link al archivo privado.
        widgets = {"documento_adjunto": forms.FileInput}


@admin.action(description="Confirmar compras seleccionadas (suma stock)")
def confirmar_compras(modeladmin, request, queryset):
    ok = 0
    for compra in queryset:
        try:
            _verificar_sucursal_o_403(request.user, compra.sucursal_id)
            compra.confirmar(user=request.user)
            ok += 1
        except (ValidationError, PermissionDenied) as e:
            modeladmin.message_user(request, f"Compra #{compra.pk}: {_mensaje(e)}", messages.ERROR)
    if ok:
        modeladmin.message_user(request, f"{ok} compra(s) confirmada(s).", messages.SUCCESS)


@admin.action(description="Anular compras seleccionadas (devuelve stock)")
def anular_compras(modeladmin, request, queryset):
    ok = 0
    for compra in queryset:
        try:
            compra.anular(user=request.user)
            ok += 1
        except (ValidationError, PermissionDenied) as e:
            modeladmin.message_user(request, f"Compra #{compra.pk}: {_mensaje(e)}", messages.ERROR)
    if ok:
        modeladmin.message_user(request, f"{ok} compra(s) anulada(s).", messages.SUCCESS)


@admin.register(Compra)
class CompraAdmin(admin.ModelAdmin):
    form = CompraAdminForm
    list_display = ("id", "fecha", "proveedor", "sucursal", "estado", "total", "tiene_adjunto")
    search_fields = ("id", "proveedor__nombre", "proveedor__documento", "observaciones")
    list_select_related = ("proveedor", "sucursal")
    date_hierarchy = "fecha"
    autocomplete_fields = ("proveedor",)
    inlines = [CompraDetalleInline]
    actions = [confirmar_compras, anular_compras]

    SEGUIMIENTO = ("creada_por", "creado_el", "confirmada_por", "confirmada_el", "anulada_por", "anulada_el")

    def get_list_filter(self, request):
        return ("estado", "sucursal") if _es_gerente(request.user) else ("estado",)

    def get_fieldsets(self, request, obj=None):
        datos = ["proveedor", "sucursal", "fecha", "observaciones"]
        # En BORRADOR se sube el archivo; después sólo se muestra su nombre.
        datos.append("documento_adjunto" if _es_borrador(obj) and self.has_change_permission(request, obj) else "adjunto")
        return (
            (None, {"fields": ["estado"] + datos}),
            ("Totales", {"fields": ("subtotal", "iva_total", "total")}),
            ("Seguimiento", {"classes": ("collapse",), "fields": self.SEGUIMIENTO}),
        )

    def get_readonly_fields(self, request, obj=None):
        fijos = ["estado", "subtotal", "iva_total", "total", "adjunto", *self.SEGUIMIENTO]
        if not _es_borrador(obj):
            fijos += ["proveedor", "sucursal", "fecha", "observaciones"]
        return fijos

    @admin.display(description="Adjunto")
    def adjunto(self, obj):
        if obj and obj.documento_adjunto:
            return obj.documento_adjunto.name.rsplit("/", 1)[-1] + " (privado)"
        return "—"

    @admin.display(boolean=True, description="Adjunto")
    def tiene_adjunto(self, obj):
        return bool(obj.documento_adjunto)

    # --- Alcance por sucursal ---

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return _filtrar_por_sucursal(qs, request.user, "sucursal_id")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal":
            kwargs["queryset"] = _filtrar_por_sucursal(Sucursal.objects.all(), request.user, "pk")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        _verificar_sucursal_o_403(request.user, obj.sucursal_id)
        if not change:
            obj.creada_por = request.user
        super().save_model(request, obj, form, change)

    # --- Permisos ---

    def has_change_permission(self, request, obj=None):
        return _es_borrador(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Sólo borradores y sólo superusuario; lo normal es anular.
        return request.user.is_superuser and obj is not None and _es_borrador(obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        user = request.user
        if not (user.is_superuser or user.has_perm("compras.registrar_compras")):
            actions.pop("confirmar_compras", None)
        if not (user.is_superuser or user.has_perm("compras.anular_compras")):
            actions.pop("anular_compras", None)
        return actions
