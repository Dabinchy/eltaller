"""
Admin del taller.

- Vehículos y técnicos: de todo el taller.
- Turnos: quien no es gerente sólo ve y carga turnos de su sucursal.
"""
from __future__ import annotations

from django.contrib import admin

from core.admin import _es_gerente, _filtrar_por_sucursal, _verificar_sucursal_o_403
from core.models import Sucursal, Usuario

from .models import Tecnico, Turno, Vehiculo


class _SinBorradoMixin:
    """Borrado físico sólo para superusuario (lo normal es desactivar o cancelar)."""

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("delete_selected", None)
        return actions


# ============================================================
# Vehículos
# ============================================================

@admin.register(Vehiculo)
class VehiculoAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = ("patente", "marca", "modelo", "anio", "cliente", "numero_competicion", "km_actual", "en_la_web", "activo")
    list_filter = ("activo", "combustible", "publicado_web", "aprobado_por_taller")
    search_fields = ("patente", "vin", "marca", "modelo", "numero_competicion", "cliente__nombre")
    list_select_related = ("cliente",)
    autocomplete_fields = ("cliente",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("cliente", "patente", "marca", "modelo", "anio", "vin", "combustible", "km_actual", "activo")}),
        ("Competición", {"fields": ("numero_competicion", "categoria")}),
        ("Web", {"fields": ("descripcion_web", "publicado_web", "aprobado_por_taller")}),
        ("Auditoría", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    @admin.display(boolean=True, description="En la web")
    def en_la_web(self, obj):
        return obj.esta_en_la_web


# ============================================================
# Técnicos
# ============================================================

@admin.register(Tecnico)
class TecnicoAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = ("nombre", "usuario", "comision_pct", "activo")
    list_filter = ("activo",)
    search_fields = ("nombre", "usuario__username", "usuario__first_name", "usuario__last_name")
    list_select_related = ("usuario",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "usuario":
            kwargs["queryset"] = Usuario.objects.filter(tipo=Usuario.Tipo.STAFF, is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ============================================================
# Turnos
# ============================================================

@admin.register(Turno)
class TurnoAdmin(_SinBorradoMixin, admin.ModelAdmin):
    list_display = ("inicio", "duracion_min", "sucursal", "cliente", "vehiculo", "motivo", "estado")
    search_fields = ("vehiculo__patente", "cliente__nombre", "motivo")
    list_select_related = ("sucursal", "cliente", "vehiculo")
    autocomplete_fields = ("cliente", "vehiculo")
    date_hierarchy = "inicio"
    readonly_fields = ("creado_por", "created_at", "updated_at")
    fields = ("sucursal", "cliente", "vehiculo", "inicio", "duracion_min", "motivo", "estado",
              "creado_por", "created_at", "updated_at")

    def get_list_filter(self, request):
        return ("estado", "sucursal") if _es_gerente(request.user) else ("estado",)

    def get_queryset(self, request):
        return _filtrar_por_sucursal(super().get_queryset(request), request.user, "sucursal_id")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal":
            kwargs["queryset"] = _filtrar_por_sucursal(Sucursal.objects.filter(activa=True), request.user, "pk")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        _verificar_sucursal_o_403(request.user, obj.sucursal_id)
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)
