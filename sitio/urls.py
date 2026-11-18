"""
Sitio público (se ve sin ingresar), en tres partes (ver partes.py):

- El Taller, en la portada: autos de calle.
- El Prepa, en /prepa/: competición, personalización y clásicos.
- Campeonatos: /campeonatos/, /pilotos/, /autos/ y /asociaciones/.

Las páginas que todavía no tienen contenido muestran "próximamente"; la estructura de
direcciones queda fija.
"""
from django.urls import path

from . import views

app_name = "sitio"

P = views.proximamente

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
    path("prepa/", views.portada, {"parte": "prepa"}, name="prepa"),
    path("prepa/competicion/", P, {"seccion": "Competición"}, name="prepa_competicion"),
    path("prepa/personalizacion/", P, {"seccion": "Personalización"}, name="prepa_personalizacion"),
    path("prepa/clasicos/", P, {"seccion": "Restauración de clásicos"}, name="prepa_clasicos"),
    path("prepa/proyectos/", P, {"seccion": "Proyectos"}, name="prepa_proyectos"),
    path("prepa/proyectos/<slug:slug>/", P, {"seccion": "Proyectos"}, name="prepa_proyecto"),
    path("prepa/consulta/", P, {"seccion": "Contanos tu proyecto"}, name="prepa_consulta"),

    # Campeonatos
    path("campeonatos/", views.campeonatos, name="campeonatos"),
    path("campeonatos/<slug:slug>/", views.campeonato, name="campeonato"),
    path("pilotos/", views.pilotos, name="pilotos"),
    path("pilotos/<slug:slug>/", views.piloto, name="piloto"),
    path("autos/<slug:slug>/", views.auto, name="auto"),
    path("asociaciones/", views.asociaciones, name="asociaciones"),
    path("asociaciones/<slug:slug>/", views.asociacion, name="asociacion"),

    # Compartido: cada publicación indicará a qué parte pertenece
    path("publicaciones/", P, {"seccion": "Novedades"}, name="publicaciones"),
    path("publicaciones/<slug:slug>/", P, {"seccion": "Novedades"}, name="publicacion"),
]
