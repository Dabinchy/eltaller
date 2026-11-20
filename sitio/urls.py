"""
Sitio público (se ve sin ingresar), en tres partes (ver partes.py):

- El Taller, en la portada: autos de calle.
- El Prepa, en /prepa/: competición, personalización y clásicos.
- Campeonatos: /campeonatos/, /pilotos/, /autos/ y /asociaciones/.
- Novedades: /publicaciones/ (?parte= para las de una parte).
"""
from django.urls import path

from . import views

app_name = "sitio"


urlpatterns = [
    # El Taller
    path("", views.inicio, name="inicio"),
    path("servicios/", views.servicios, name="servicios"),
    path("trabajos/", views.trabajos, name="trabajos"),
    path("trabajos/<slug:slug>/", views.trabajo, name="trabajo"),
    path("presupuesto/", views.presupuesto, name="presupuesto"),
    path("contacto/", views.contacto, name="contacto"),
    path("consulta-enviada/<str:tipo>/", views.consulta_enviada, name="consulta_enviada"),

    # El Prepa
    path("prepa/", views.prepa_inicio, name="prepa"),
    path("prepa/competicion/", views.prepa_seccion, {"seccion": "competicion"}, name="prepa_competicion"),
    path("prepa/personalizacion/", views.prepa_seccion, {"seccion": "personalizacion"}, name="prepa_personalizacion"),
    path("prepa/clasicos/", views.prepa_seccion, {"seccion": "clasicos"}, name="prepa_clasicos"),
    path("prepa/proyectos/", views.prepa_proyectos, name="prepa_proyectos"),
    path("prepa/proyectos/<slug:slug>/", views.prepa_proyecto, name="prepa_proyecto"),
    path("prepa/consulta/", views.prepa_consulta, name="prepa_consulta"),

    # Campeonatos
    path("campeonatos/", views.campeonatos, name="campeonatos"),
    path("campeonatos/<slug:slug>/", views.campeonato, name="campeonato"),
    path("pilotos/", views.pilotos, name="pilotos"),
    path("pilotos/<slug:slug>/", views.piloto, name="piloto"),
    path("autos/<slug:slug>/", views.auto, name="auto"),
    path("asociaciones/", views.asociaciones, name="asociaciones"),
    path("asociaciones/<slug:slug>/", views.asociacion, name="asociacion"),

    # Compartido: cada novedad se ve con el encabezado de su parte
    path("publicaciones/", views.publicaciones, name="publicaciones"),
    path("publicaciones/<slug:slug>/", views.publicacion, name="publicacion"),
]
