"""Caja y PIN dentro del panel (/panel/caja/..., /panel/mi-pin/)."""
from django.urls import path

from . import views_caja as v

app_name = "core"

urlpatterns = [
    path("caja/", v.lista, name="caja"),
    path("caja/<int:pk>/", v.detalle_caja, name="caja_detalle"),
    path("caja/<int:pk>/abrir/", v.abrir, name="abrir"),
    path("caja/<int:pk>/movimiento/", v.movimiento, name="movimiento"),
    path("caja/sesion/<int:pk>/", v.sesion, name="sesion"),
    path("caja/sesion/<int:pk>/cerrar/", v.cerrar, name="cerrar"),
    path("mi-pin/", v.mi_pin, name="pin"),
]
