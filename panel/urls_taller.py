"""Taller en el panel: /panel/taller/..."""
from django.urls import path

from . import views_taller as v

app_name = "taller"

urlpatterns = [
    path("ordenes/", v.ordenes, name="ordenes"),
    path("mis-ordenes/", v.ordenes, {"solo_mias": True}, name="mis_ordenes"),
    path("ordenes/nueva/", v.orden_nueva, name="orden_nueva"),
    path("ordenes/<int:pk>/", v.orden, name="orden"),
    path("ordenes/<int:pk>/editar/", v.orden_editar, name="orden_editar"),
    path("ordenes/<int:pk>/estado/", v.orden_estado, name="orden_estado"),
    path("ordenes/<int:pk>/aprobar-items/", v.orden_aprobar_items, name="orden_aprobar_items"),
    path("ordenes/<int:pk>/entregar/", v.orden_entregar, name="orden_entregar"),
    path("ordenes/<int:pk>/items/", v.item_agregar, name="item_agregar"),
    path("ordenes/<int:pk>/items/<int:item_pk>/borrar/", v.item_borrar, name="item_borrar"),
    path("ordenes/<int:pk>/comentar/", v.orden_comentar, name="orden_comentar"),
    path("ordenes/<int:pk>/archivos/", v.orden_subir_archivo, name="orden_archivo"),
    path("turnos/", v.turnos, name="turnos"),
    path("turnos/nuevo/", v.turno_form, name="turno_nuevo"),
    path("turnos/<int:pk>/editar/", v.turno_form, name="turno_editar"),
    path("turnos/<int:pk>/estado/", v.turno_estado, name="turno_estado"),
    path("vehiculos/", v.vehiculos, name="vehiculos"),
    path("vehiculos/nuevo/", v.vehiculo_form, name="vehiculo_nuevo"),
    path("vehiculos/<int:pk>/", v.vehiculo, name="vehiculo"),
    path("vehiculos/<int:pk>/editar/", v.vehiculo_form, name="vehiculo_editar"),
]
