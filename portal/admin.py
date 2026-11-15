"""
Admin del portal (sólo personal del taller).

- Gerente: asociaciones, membresías (incluido nombrar moderadores) y perfiles.
- Los moderadores de cada asociación NO usan el admin: tienen /portal/moderacion/ (paso 5).
- Toda decisión pasa por portal/servicios.py, así queda en el historial.
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from . import servicios
from .models import Asociacion, Membresia, PerfilPiloto, RegistroModeracion

MOTIVO_ADMIN = "Resuelto desde el administrador"


def _mensaje(e: Exception) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _accion(funcion, descripcion, *, con_motivo=False):
    """Arma una acción de admin que aplica un servicio a cada objeto seleccionado."""

    @admin.action(description=descripcion)
    def accion(modeladmin, request, queryset):
        ok = 0
        for obj in queryset:
            try:
                if con_motivo:
                    funcion(obj, request.user, MOTIVO_ADMIN)
                else:
                    funcion(obj, request.user)
                ok += 1
            except (ValidationError, PermissionDenied) as e:
                modeladmin.message_user(request, f"{obj}: {_mensaje(e)}", messages.ERROR)
        if ok:
            modeladmin.message_user(request, f"{ok} actualizado(s).", messages.SUCCESS)

    accion.__name__ = funcion.__name__
    return accion


@admin.register(Asociacion)
class AsociacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "slug", "cuota_mb", "activa")
    list_filter = ("activa",)
    search_fields = ("nombre",)
    readonly_fields = ("created_at",)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "asociacion", "rol", "estado", "solicitada_el", "resuelta_por")
    list_filter = ("asociacion", "rol", "estado")
    search_fields = ("usuario__username", "usuario__first_name", "usuario__last_name", "usuario__dni")
    list_select_related = ("usuario", "asociacion", "resuelta_por")
    autocomplete_fields = ("usuario",)
    readonly_fields = ("estado", "motivo", "solicitada_el", "resuelta_por", "resuelta_el")
    actions = [
        _accion(servicios.aprobar_membresia, "Aprobar / reactivar"),
        _accion(servicios.rechazar_membresia, "Rechazar", con_motivo=True),
        _accion(servicios.suspender_membresia, "Suspender", con_motivo=True),
        _accion(servicios.marcar_spam, "Marcar como spam (desactiva la cuenta si no tiene otro vínculo)"),
    ]

    def get_readonly_fields(self, request, obj=None):
        fijos = list(self.readonly_fields)
        if obj:
            fijos += ["usuario", "asociacion", "rol"]
        return fijos

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(PerfilPiloto)
class PerfilPilotoAdmin(admin.ModelAdmin):
    list_display = ("nombre_publico", "usuario", "perfil_publico", "aprobado", "cambio_tras_aprobacion", "menor")
    list_filter = ("aprobado", "perfil_publico", "cambio_tras_aprobacion")
    search_fields = ("nombre_publico", "usuario__username", "usuario__dni", "licencia")
    list_select_related = ("usuario",)
    actions = [
        _accion(servicios.aprobar_perfil, "Aprobar perfil"),
        _accion(servicios.retirar_aprobacion_perfil, "Retirar aprobación", con_motivo=True),
        _accion(servicios.marcar_perfil_revisado, "Marcar cambios como revisados"),
        _accion(servicios.registrar_consentimiento_tutor, "Registrar consentimiento del tutor"),
    ]
    fieldsets = (
        ("Privado", {"fields": ("usuario", "dni", "licencia", "fecha_nacimiento", "telefono")}),
        ("Público", {"fields": ("nombre_publico", "slug", "bio", "instagram", "sitio_web", "perfil_publico")}),
        ("Control", {"fields": (
            "aprobado", "aprobado_por", "aprobado_el", "cambio_tras_aprobacion",
            "consentimiento_tutor", "consentimiento_tutor_por", "consentimiento_tutor_el",
            "cuota_mb", "cuota_efectiva_mb",
        )}),
    )

    @admin.display(description="DNI")
    def dni(self, obj):
        return obj.usuario.dni or "—"

    @admin.display(boolean=True, description="Menor")
    def menor(self, obj):
        return obj.es_menor

    @admin.display(description="Cuota efectiva (MB)")
    def cuota_efectiva_mb(self, obj):
        return obj.cuota_efectiva_mb

    def get_readonly_fields(self, request, obj=None):
        # El contenido es del piloto: el personal lo ve y lo modera, no lo edita.
        return [f for _, opts in self.fieldsets for f in opts["fields"]]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(RegistroModeracion)
class RegistroModeracionAdmin(admin.ModelAdmin):
    list_display = ("fecha", "actor", "accion", "descripcion_objeto", "asociacion", "motivo")
    list_filter = ("accion", "asociacion")
    search_fields = ("descripcion_objeto", "actor__username", "motivo")
    date_hierarchy = "fecha"

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
