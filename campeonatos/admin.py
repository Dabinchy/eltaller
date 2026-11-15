"""
Admin de campeonatos (consulta para el gerente).
Los moderadores de cada asociación los gestionan desde el portal (paso 5).
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError

from . import servicios
from .models import Campeonato, Carrera, Categoria, Fecha, Inscripcion, PuntajePosicion, Resultado


class CategoriaInline(admin.TabularInline):
    model = Categoria
    extra = 0


class PuntajeInline(admin.TabularInline):
    model = PuntajePosicion
    extra = 0


@admin.register(Campeonato)
class CampeonatoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "temporada", "asociacion", "estado")
    list_filter = ("asociacion", "estado", "temporada")
    search_fields = ("nombre",)
    inlines = [CategoriaInline, PuntajeInline]
    readonly_fields = ("slug", "creado_por", "created_at")


class CarreraInline(admin.TabularInline):
    model = Carrera
    extra = 0


@admin.register(Fecha)
class FechaAdmin(admin.ModelAdmin):
    list_display = ("campeonato", "numero", "nombre", "circuito", "dia", "estado", "multiplicador")
    list_filter = ("campeonato__asociacion", "campeonato", "estado")
    search_fields = ("nombre", "circuito")
    inlines = [CarreraInline]


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ("numero", "piloto", "categoria", "auto", "estado")
    list_filter = ("categoria__campeonato", "estado")
    search_fields = ("numero", "piloto__nombre_publico")
    list_select_related = ("piloto", "categoria__campeonato", "auto")
    readonly_fields = ("estado", "motivo_baja", "created_at")


def _accion(funcion, descripcion, con_motivo=False):
    @admin.action(description=descripcion)
    def accion(modeladmin, request, queryset):
        for r in queryset:
            try:
                if con_motivo:
                    funcion(r, request.user, "Resuelto desde el administrador")
                else:
                    funcion(r, request.user)
            except (ValidationError, PermissionDenied) as e:
                texto = "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)
                modeladmin.message_user(request, f"{r}: {texto}", messages.ERROR)

    accion.__name__ = funcion.__name__
    return accion


@admin.register(Resultado)
class ResultadoAdmin(admin.ModelAdmin):
    list_display = ("carrera", "inscripcion", "posicion", "condicion", "pole", "vuelta_rapida", "puntos", "estado")
    list_filter = ("estado", "carrera__fecha__campeonato", "condicion")
    search_fields = ("inscripcion__numero", "inscripcion__piloto__nombre_publico")
    list_select_related = ("carrera__fecha__campeonato", "inscripcion__piloto")
    actions = [
        _accion(servicios.validar_resultado, "Validar"),
        _accion(servicios.anular_resultado, "Anular", con_motivo=True),
    ]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
