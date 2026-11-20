"""Clientes: /panel/clientes/..."""
from django.urls import path

from . import views_accesos as acc
from . import views_clientes as v

app_name = "clientes"

urlpatterns = [
    path("", v.lista, name="lista"),
    path("nuevo/", v.cliente_form, name="nuevo"),
    path("<int:pk>/", v.detalle, name="detalle"),
    path("<int:pk>/editar/", v.cliente_form, name="editar"),
    path("<int:pk>/pago/", v.pago, name="pago"),
    # Accesos al portal (clientes que piden ver su taller): sólo gerencia
    path("accesos/", acc.lista, name="accesos"),
    path("accesos/<int:pk>/", acc.detalle, name="acceso"),
]
