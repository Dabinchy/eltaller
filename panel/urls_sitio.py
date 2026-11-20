"""Contenido del sitio público y consultas: /panel/sitio/..."""
from django.urls import path

from . import views_sitio as v

app_name = "sitio_panel"

urlpatterns = [
    path("", v.inicio, name="inicio"),

    path("novedades/", v.novedades, name="novedades"),
    path("novedades/nueva/", v.novedad_form, name="novedad_nueva"),
    path("novedades/<int:pk>/", v.novedad_form, name="novedad"),

    path("trabajos/", v.trabajos, name="trabajos"),
    path("trabajos/nuevo/", v.trabajo_form, name="trabajo_nuevo"),
    path("trabajos/<int:pk>/", v.trabajo, name="trabajo"),
    path("trabajos/<int:pk>/editar/", v.trabajo_form, name="trabajo_editar"),
    path("trabajos/<int:pk>/destacar/", v.destacar, name="trabajo_destacar"),
    path("trabajos/<int:pk>/fotos/", v.fotos_subir, name="fotos_subir"),
    path("fotos/<int:pk>/", v.foto_accion, name="foto"),

    path("servicios/", v.servicios, name="servicios"),
    path("servicios/nuevo/", v.servicio_form, name="servicio_nuevo"),
    path("servicios/<int:pk>/", v.servicio_form, name="servicio"),

    path("testimonios/", v.testimonios, name="testimonios"),
    path("testimonios/nuevo/", v.testimonio_form, name="testimonio_nuevo"),
    path("testimonios/<int:pk>/", v.testimonio_form, name="testimonio"),

    path("portadas/", v.portadas, name="portadas"),
    path("portadas/<str:parte>/", v.portada_form, name="portada"),

    path("consultas/", v.consultas, name="consultas"),
    path("consultas/<int:pk>/", v.consulta, name="consulta"),
    path("consultas/<int:pk>/borrar/", v.consulta_borrar, name="consulta_borrar"),

    # Acciones comunes: tipo = novedades | trabajos | servicios | testimonios
    path("<str:tipo>/<int:pk>/publicar/", v.publicar, name="publicar"),
    path("<str:tipo>/<int:pk>/mover/", v.mover, name="mover"),
    path("<str:tipo>/<int:pk>/borrar/", v.borrar, name="borrar"),
]
