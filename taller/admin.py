"""
Admin del taller.

- Vehículos y técnicos: de todo el taller.
- Turnos: quien no es gerente sólo ve y carga turnos de su sucursal.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from core.admin import _es_gerente, _filtrar_por_sucursal, _verificar_sucursal_o_403
from core.models import SesionCaja, Sucursal, Usuario

from . import permisos
from .models import OrdenEstadoLog, OrdenItem, OrdenTrabajo, Tecnico, Turno, Vehiculo


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
    list_display = ("patente", "vin", "marca", "modelo", "anio", "cliente", "km_actual", "activo")
    list_filter = ("activo", "combustible")
    search_fields = ("patente", "vin", "marca", "modelo", "cliente__nombre")
    list_select_related = ("cliente",)
    autocomplete_fields = ("cliente",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("cliente", "patente", "vin", "marca", "modelo", "anio", "combustible", "km_actual", "activo"),
            "description": "Cargá la patente o el VIN / chasis (al menos uno).",
        }),
        ("Auditoría", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )


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


# ============================================================
# Órdenes de trabajo
# ============================================================

def _puede_ver_costos(user) -> bool:
    return user.is_superuser or user.has_perm("productos.ver_costos")


def _editable(orden) -> bool:
    return orden is None or orden.estado in OrdenTrabajo.ESTADOS_EDITABLES


class OrdenItemInline(admin.TabularInline):
    model = OrdenItem
    extra = 1
    autocomplete_fields = ("producto",)

    def get_fields(self, request, obj=None):
        campos = ["producto", "descripcion", "tecnico", "cantidad", "precio_unitario"]
        if _puede_ver_costos(request.user):
            campos.append("costo_unitario")
        return campos + ["importe", "aprobado", "aviso_stock"]

    def get_readonly_fields(self, request, obj=None):
        fijos = ["importe", "aprobado", "aviso_stock"]
        if permisos.es_solo_mecanico(request.user):
            fijos.append("precio_unitario")  # el mecánico carga ítems; el precio sale de la lista
        return fijos

    @admin.display(description="Stock")
    def aviso_stock(self, obj):
        if not obj or not obj.pk:
            return ""
        disponible = obj.stock_disponible
        if disponible is None:
            return "—"
        return f"⚠ faltan ({disponible} disp.)" if obj.falta_stock else f"{disponible} disp."

    def has_add_permission(self, request, obj=None):
        return _editable(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return _editable(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return _editable(obj) and super().has_delete_permission(request, obj)


class OrdenEstadoLogInline(admin.TabularInline):
    model = OrdenEstadoLog
    extra = 0
    can_delete = False
    fields = ("fecha", "estado_anterior", "estado_nuevo", "usuario")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


def _accion_estado(nuevo, descripcion):
    @admin.action(description=descripcion)
    def accion(modeladmin, request, queryset):
        ok = 0
        for orden in queryset:
            try:
                orden.cambiar_estado(nuevo, user=request.user)
                ok += 1
            except (ValidationError, PermissionDenied) as e:
                modeladmin.message_user(request, f"OT #{orden.numero}: {_mensaje(e)}", messages.ERROR)
        if ok:
            modeladmin.message_user(request, f"{ok} orden(es) actualizada(s).", messages.SUCCESS)

    accion.__name__ = f"pasar_a_{nuevo.lower()}"
    return accion


def _mensaje(e: Exception) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


@admin.action(description="Aprobar ítems pendientes")
def aprobar_items_pendientes(modeladmin, request, queryset):
    for orden in queryset:
        try:
            n = orden.aprobar_items(user=request.user)
            modeladmin.message_user(request, f"OT #{orden.numero}: {n} ítem(s) aprobado(s).", messages.SUCCESS)
        except (ValidationError, PermissionDenied) as e:
            modeladmin.message_user(request, f"OT #{orden.numero}: {_mensaje(e)}", messages.ERROR)


@admin.action(description="Entregar (genera la venta en la caja abierta de la sucursal)")
def entregar_ordenes(modeladmin, request, queryset):
    for orden in queryset:
        sesiones = list(SesionCaja.objects.filter(caja__sucursal=orden.sucursal_id, estado=SesionCaja.Estado.ABIERTA)[:2])
        if len(sesiones) != 1:
            texto = "no hay ninguna caja abierta en la sucursal" if not sesiones else \
                "hay más de una caja abierta; entregala desde la pantalla de caja"
            modeladmin.message_user(request, f"OT #{orden.numero}: {texto}.", messages.ERROR)
            continue
        try:
            venta = orden.entregar(user=request.user, sesion=sesiones[0])
            modeladmin.message_user(
                request, f"OT #{orden.numero} entregada: venta #{venta.pk} lista para cobrar.", messages.SUCCESS
            )
        except (ValidationError, PermissionDenied) as e:
            modeladmin.message_user(request, f"OT #{orden.numero}: {_mensaje(e)}", messages.ERROR)


ACCIONES_ORDEN = {
    # nombre de la acción: permisos que la habilitan (alcanza con uno)
    "pasar_a_aprobada": (permisos.PERM_CAMBIAR_ESTADO,),
    "pasar_a_en_proceso": (permisos.PERM_CAMBIAR_ESTADO, permisos.PERM_TRABAJAR),
    "pasar_a_terminada": (permisos.PERM_CAMBIAR_ESTADO, permisos.PERM_TRABAJAR),
    "pasar_a_cancelada": (permisos.PERM_CANCELAR,),
    "aprobar_items_pendientes": (permisos.PERM_APROBAR_ITEMS,),
    "entregar_ordenes": (permisos.PERM_ENTREGAR,),
}


@admin.register(OrdenTrabajo)
class OrdenTrabajoAdmin(admin.ModelAdmin):
    list_display = ("numero", "fecha_ingreso", "sucursal", "vehiculo", "cliente", "tecnico", "estado", "total")
    search_fields = ("numero", "vehiculo__patente", "cliente__nombre", "motivo_cliente")
    list_select_related = ("sucursal", "vehiculo", "cliente", "tecnico")
    autocomplete_fields = ("vehiculo", "cliente", "turno")
    date_hierarchy = "fecha_ingreso"
    inlines = [OrdenItemInline, OrdenEstadoLogInline]
    actions = [
        _accion_estado(OrdenTrabajo.Estado.APROBADA, "Aprobar presupuesto"),
        _accion_estado(OrdenTrabajo.Estado.EN_PROCESO, "Empezar trabajo / reabrir"),
        _accion_estado(OrdenTrabajo.Estado.TERMINADA, "Terminar trabajo"),
        _accion_estado(OrdenTrabajo.Estado.CANCELADA, "Cancelar orden"),
        aprobar_items_pendientes,
        entregar_ordenes,
    ]

    CAMPOS_FIJOS = ("numero", "estado", "total_repuestos", "total_mano_obra", "total",
                    "total_presupuestado", "venta", "fecha_egreso", "creada_por")

    fieldsets = (
        (None, {"fields": ("numero", "estado", "sucursal", "vehiculo", "cliente", "tecnico", "turno")}),
        ("Ingreso", {"fields": ("km_ingreso", "fecha_ingreso", "fecha_prometida", "motivo_cliente", "diagnostico")}),
        ("Totales (ítems aprobados)", {"fields": ("total_repuestos", "total_mano_obra", "total", "total_presupuestado")}),
        ("Entrega", {"fields": ("venta", "fecha_egreso", "creada_por")}),
    )

    @admin.display(description="Total presupuestado (todos los ítems)")
    def total_presupuestado(self, obj):
        return obj.total_presupuestado if obj and obj.pk else "—"

    def get_list_filter(self, request):
        return ("estado", "sucursal", "tecnico") if _es_gerente(request.user) else ("estado", "tecnico")

    def get_readonly_fields(self, request, obj=None):
        if permisos.es_solo_mecanico(request.user):
            # El mecánico sólo escribe el diagnóstico (y carga ítems).
            todos = [f for _, opts in self.fieldsets for f in opts["fields"]]
            return [f for f in todos if f != "diagnostico"]
        fijos = list(self.CAMPOS_FIJOS)
        if obj:
            fijos += ["sucursal", "vehiculo", "turno"]  # no se mueven una vez creada
        return fijos

    def get_queryset(self, request):
        return permisos.ordenes_visibles(super().get_queryset(request), request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal":
            kwargs["queryset"] = _filtrar_por_sucursal(Sucursal.objects.filter(activa=True), request.user, "pk")
        elif db_field.name == "tecnico":
            kwargs["queryset"] = Tecnico.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not permisos.es_solo_mecanico(request.user):
            _verificar_sucursal_o_403(request.user, obj.sucursal_id)
        if not change:
            obj.creada_por = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        if formset.model is OrdenItem:
            tecnico_propio = Tecnico.objects.filter(usuario=request.user).first()
            for item in formset.save(commit=False):
                if not item.tecnico_id and tecnico_propio:
                    item.tecnico = tecnico_propio
                item.save()
                if item.falta_stock:
                    self.message_user(
                        request,
                        f"Atención: no hay stock suficiente de {item.producto} "
                        f"({item.stock_disponible} disponible). Se puede cargar igual; la venta lo va a pedir.",
                        messages.WARNING,
                    )
            for item in formset.deleted_objects:
                item.delete()
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.estado in OrdenTrabajo.ESTADOS_FINALES:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False  # las órdenes se cancelan, no se borran

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        user = request.user
        for nombre, perms in ACCIONES_ORDEN.items():
            if not (user.is_superuser or any(user.has_perm(p) for p in perms)):
                actions.pop(nombre, None)
        return actions
