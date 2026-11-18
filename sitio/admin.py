"""
Admin del contenido del sitio público (portadas, servicios, trabajos, testimonios, novedades)
y de las consultas que mandan los visitantes.

Quién ve qué lo deciden los permisos de cada grupo (sitio/signals.py).
"""
from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Consulta, FotoTrabajo, Portada, Publicacion, Servicio, Testimonio, Trabajo


def _miniatura(archivo, alto: int = 48):
    if not archivo:
        return "—"
    return format_html(
        '<img src="{}" alt="" style="height:{}px;width:auto;max-width:120px;object-fit:cover;border-radius:6px">',
        archivo.url, alto,
    )


@admin.action(description="Publicar los elegidos", permissions=["change"])
def publicar(modeladmin, request, queryset):
    campo = "publicada" if queryset.model is Publicacion else "publicado"
    n = queryset.update(**{campo: True})
    modeladmin.message_user(request, f"Publicados: {n}.", messages.SUCCESS)


@admin.action(description="Despublicar los elegidos (dejan de verse en la web)", permissions=["change"])
def despublicar(modeladmin, request, queryset):
    campo = "publicada" if queryset.model is Publicacion else "publicado"
    n = queryset.update(**{campo: False})
    modeladmin.message_user(request, f"Despublicados: {n}.", messages.SUCCESS)


@admin.register(Portada)
class PortadaAdmin(admin.ModelAdmin):
    list_display = ("__str__", "titulo", "vista_foto", "actualizada")
    fields = ("parte", "titulo", "subtitulo", "imagen", "vista_foto", "video_url")
    readonly_fields = ("vista_foto",)

    @admin.display(description="Vista previa")
    def vista_foto(self, obj):
        return _miniatura(obj.imagen, 90)


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ("titulo", "parte", "seccion", "orden", "publicado", "vista_foto")
    list_editable = ("orden", "publicado")
    list_filter = ("parte", "seccion", "publicado")
    search_fields = ("titulo", "resumen", "descripcion")
    fields = ("parte", "seccion", "titulo", "icono", "resumen", "descripcion", "imagen", "vista_foto",
              "orden", "publicado")
    readonly_fields = ("vista_foto",)
    actions = (publicar, despublicar)

    @admin.display(description="Foto")
    def vista_foto(self, obj):
        return _miniatura(obj.miniatura or obj.imagen)


class FotoTrabajoInline(admin.TabularInline):
    model = FotoTrabajo
    extra = 3
    fields = ("imagen", "vista_foto", "epigrafe", "etapa", "orden")
    readonly_fields = ("vista_foto",)

    @admin.display(description="Vista previa")
    def vista_foto(self, obj):
        return _miniatura(obj.miniatura or obj.imagen, 60)


@admin.register(Trabajo)
class TrabajoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "tipo", "auto", "fecha", "destacado", "publicado", "vista_foto", "cant_fotos")
    list_editable = ("destacado", "publicado")
    list_filter = ("tipo", "publicado", "destacado")
    search_fields = ("titulo", "auto", "resumen", "descripcion")
    date_hierarchy = "fecha"
    readonly_fields = ("vista_foto",)
    fieldsets = (
        (None, {"fields": ("tipo", "titulo", "auto", "resumen", "descripcion")}),
        ("Fotos y video", {"fields": ("portada", "vista_foto", "video_url")}),
        ("Publicación", {"fields": ("fecha", "destacado", "publicado", "slug")}),
    )
    inlines = [FotoTrabajoInline]
    actions = (publicar, despublicar)

    def get_queryset(self, request):
        from django.db.models import Count

        return super().get_queryset(request).annotate(_fotos=Count("fotos"))

    @admin.display(description="Portada")
    def vista_foto(self, obj):
        return _miniatura(obj.portada_miniatura or obj.portada)

    @admin.display(description="Fotos", ordering="_fotos")
    def cant_fotos(self, obj):
        return getattr(obj, "_fotos", 0)


@admin.register(Testimonio)
class TestimonioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "parte", "detalle", "orden", "publicado", "creado")
    list_editable = ("orden", "publicado")
    list_filter = ("parte", "publicado")
    search_fields = ("nombre", "detalle", "texto")
    fields = ("parte", "nombre", "detalle", "texto", "orden", "publicado")
    actions = (publicar, despublicar)


@admin.register(Publicacion)
class PublicacionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "parte", "fecha", "publicada", "vista_foto")
    list_editable = ("publicada",)
    list_filter = ("parte", "publicada")
    search_fields = ("titulo", "resumen", "cuerpo")
    date_hierarchy = "fecha"
    readonly_fields = ("vista_foto",)
    fieldsets = (
        (None, {"fields": ("parte", "titulo", "resumen", "cuerpo")}),
        ("Foto y video", {"fields": ("portada", "vista_foto", "video_url")}),
        ("Publicación", {"fields": ("fecha", "publicada", "slug")}),
    )
    actions = (publicar, despublicar)

    @admin.display(description="Portada")
    def vista_foto(self, obj):
        return _miniatura(obj.portada_miniatura or obj.portada)


# ===========================
# Consultas
# ===========================

def _accion_estado(estado: str, descripcion: str):
    @admin.action(description=descripcion, permissions=["change"])
    def accion(modeladmin, request, queryset):
        for consulta in queryset:
            consulta.marcar(estado, request.user)
        modeladmin.message_user(request, f"Consultas actualizadas: {queryset.count()}.", messages.SUCCESS)

    accion.__name__ = f"marcar_{estado}"
    return accion


@admin.register(Consulta)
class ConsultaAdmin(admin.ModelAdmin):
    list_display = ("creada", "estado_badge", "tipo", "parte", "nombre", "telefono", "email", "vehiculo")
    list_filter = ("estado", "tipo", "parte")
    search_fields = ("nombre", "telefono", "email", "vehiculo", "mensaje")
    date_hierarchy = "creada"
    list_display_links = ("creada", "nombre")
    fields = ("tipo", "parte", "nombre", "telefono", "email", "vehiculo", "mensaje", "creada",
              "estado", "notas", "respondida_por", "respondida_el")
    readonly_fields = ("tipo", "parte", "nombre", "telefono", "email", "vehiculo", "mensaje", "creada",
                       "respondida_por", "respondida_el")
    actions = (
        _accion_estado(Consulta.Estado.RESPONDIDA, "Marcar como respondidas"),
        _accion_estado(Consulta.Estado.ARCHIVADA, "Archivar"),
        _accion_estado(Consulta.Estado.NUEVA, "Volver a marcar como nuevas"),
    )

    def has_add_permission(self, request):
        return False  # llegan sólo por los formularios del sitio

    @admin.display(description="Estado", ordering="estado")
    def estado_badge(self, obj):
        colores = {
            Consulta.Estado.NUEVA: "#d97706",
            Consulta.Estado.RESPONDIDA: "#16a34a",
            Consulta.Estado.ARCHIVADA: "#64748b",
        }
        return format_html(
            '<strong style="color:{}">{}</strong>', colores.get(obj.estado, "inherit"), obj.get_estado_display(),
        )

    def save_model(self, request, obj, form, change):
        # Si se cambia el estado a "respondida" desde el formulario, se guarda quién y cuándo.
        if change and "estado" in form.changed_data and obj.estado == Consulta.Estado.RESPONDIDA:
            from django.utils import timezone

            obj.respondida_por = request.user
            obj.respondida_el = timezone.now()
        super().save_model(request, obj, form, change)
