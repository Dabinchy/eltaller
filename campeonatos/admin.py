"""
Admin de campeonatos (consulta para el gerente).
Los moderadores de cada asociación los gestionan desde el portal (paso 5).
"""
from __future__ import annotations

from django.contrib import admin

from .models import Campeonato, Carrera, Categoria, Fecha, Inscripcion, PuntajePosicion


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
