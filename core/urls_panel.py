from django.contrib.auth.decorators import login_required
from django.urls import path

from portal.views_cuenta import CambiarClave

from . import views

app_name = "panel"

urlpatterns = [
    path("", views.panel_inicio, name="inicio"),
    path("clave/", login_required(CambiarClave.as_view()), name="clave"),
]
