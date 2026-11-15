"""Compras y proveedores: /panel/compras/..."""
from django.urls import path

from . import views_compras as v

app_name = "compras"

urlpatterns = [
    path("", v.lista, name="lista"),
    path("nueva/", v.nueva, name="nueva"),
    path("<int:pk>/", v.detalle, name="detalle"),
    path("<int:pk>/items/", v.item_agregar, name="item_agregar"),
    path("<int:pk>/items/<int:item_pk>/borrar/", v.item_borrar, name="item_borrar"),
    path("<int:pk>/confirmar/", v.confirmar, name="confirmar"),
    path("<int:pk>/anular/", v.anular, name="anular"),
    path("<int:pk>/factura/", v.adjunto, name="adjunto"),
    path("proveedores/", v.proveedores, name="proveedores"),
    path("proveedores/nuevo/", v.proveedor_form, name="proveedor_nuevo"),
    path("proveedores/<int:pk>/editar/", v.proveedor_form, name="proveedor_editar"),
]
