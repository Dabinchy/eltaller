"""
Sitio público del taller (se ve sin ingresar).

Por ahora las páginas son provisorias: la estructura de direcciones queda fija y el contenido
se completa en el paso 6 (home publicitaria, servicios, pilotos, autos, campeonatos, publicaciones).
"""
from django.urls import path

from . import views

app_name = "sitio"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("servicios/", views.proximamente, {"seccion": "Servicios"}, name="servicios"),
    path("contacto/", views.proximamente, {"seccion": "Contacto"}, name="contacto"),
    path("pilotos/", views.proximamente, {"seccion": "Pilotos"}, name="pilotos"),
    path("pilotos/<slug:slug>/", views.proximamente, {"seccion": "Pilotos"}, name="piloto"),
    path("autos/<slug:slug>/", views.proximamente, {"seccion": "Autos"}, name="auto"),
    path("campeonatos/", views.proximamente, {"seccion": "Campeonatos"}, name="campeonatos"),
    path("campeonatos/<slug:slug>/", views.proximamente, {"seccion": "Campeonatos"}, name="campeonato"),
    path("asociaciones/<slug:slug>/", views.proximamente, {"seccion": "Asociaciones"}, name="asociacion"),
    path("publicaciones/", views.proximamente, {"seccion": "Publicaciones"}, name="publicaciones"),
    path("publicaciones/<slug:slug>/", views.proximamente, {"seccion": "Publicaciones"}, name="publicacion"),
]
