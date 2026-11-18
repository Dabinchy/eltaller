"""Gestión de campeonatos por moderadores: /portal/moderacion/campeonatos/..."""
from django.urls import path

from . import views_moderacion as v

app_name = "campeonatos_mod"

urlpatterns = [
    path("", v.lista, name="lista"),
    path("<int:pk>/", v.detalle, name="detalle"),
    path("<int:pk>/editar/", v.editar, name="editar"),
    path("<int:pk>/estado/", v.estado, name="estado"),
    path("<int:pk>/categorias/", v.categoria, name="categoria"),
    path("<int:pk>/puntos/", v.puntos, name="puntos"),
    path("<int:pk>/fechas/", v.fecha, name="fecha"),
    path("fechas/<int:fecha_pk>/carreras/", v.carrera, name="carrera"),
    path("fechas/<int:fecha_pk>/resultados/", v.resultados, name="resultados"),
    path("inscripciones/<int:pk>/baja/", v.baja, name="baja"),
    path("resultados/<int:pk>/", v.resultado, name="resultado"),
    path("carreras/<int:carrera_pk>/categorias/<int:categoria_pk>/validar/", v.validar_todos, name="validar_todos"),
]
