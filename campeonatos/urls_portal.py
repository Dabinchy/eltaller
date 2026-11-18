"""Campeonatos del piloto: /portal/campeonatos/..."""
from django.urls import path

from . import views_portal as v

app_name = "campeonatos_portal"

urlpatterns = [
    path("", v.inicio, name="inicio"),
    path("<slug:slug>/", v.campeonato, name="campeonato"),
    path("<slug:slug>/inscribirse/", v.inscribirse, name="inscribirse"),
    path("inscripciones/<int:pk>/baja/", v.baja, name="baja"),
    path("carreras/<int:carrera_pk>/inscripciones/<int:inscripcion_pk>/resultado/", v.cargar_resultado,
         name="cargar_resultado"),
]
