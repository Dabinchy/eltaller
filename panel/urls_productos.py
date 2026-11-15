"""Productos, stock y precios: /panel/productos/..."""
from django.urls import path

from . import views_productos as v

app_name = "productos"

urlpatterns = [
    path("", v.lista, name="lista"),
    path("nuevo/", v.producto_form, name="nuevo"),
    path("<int:pk>/", v.detalle, name="detalle"),
    path("<int:pk>/editar/", v.producto_form, name="editar"),
    path("<int:pk>/stock/", v.ajustar, name="ajustar"),
    path("stock/", v.stock, name="stock"),
    path("precios/", v.precios, name="precios"),
    path("precios/nuevo/", v.precio_nuevo, name="precio_nuevo"),
    path("precios/listas/nueva/", v.lista_precio_nueva, name="lista_precio_nueva"),
]
