"""Ventas en el panel: /panel/ventas/..."""
from django.urls import path

from . import views_ventas as v

app_name = "ventas"

urlpatterns = [
    path("", v.listado, name="listado"),
    path("por-cobrar/", v.por_cobrar, name="por_cobrar"),
    path("mostrador/", v.mostrador, name="mostrador"),
    path("<int:pk>/", v.venta, name="venta"),
    path("<int:pk>/items/", v.item_agregar, name="item_agregar"),
    path("<int:pk>/items/<int:item_pk>/borrar/", v.item_borrar, name="item_borrar"),
    path("<int:pk>/cliente/", v.cliente, name="cliente"),
    path("<int:pk>/cobrar/", v.cobrar, name="cobrar"),
    path("<int:pk>/descartar/", v.descartar, name="descartar"),
    path("<int:pk>/anular/", v.anular, name="anular"),
    path("<int:pk>/comprobante/", v.comprobante, name="comprobante"),
]
