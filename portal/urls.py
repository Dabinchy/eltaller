from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views, views_contenido as vc, views_cuenta

app_name = "portal"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("registro/", views_cuenta.registro, name="registro"),
    path("clave/", login_required(views_cuenta.CambiarClave.as_view()), name="clave"),
    path("perfil/", views_cuenta.perfil, name="perfil"),
    path("perfil/palmares/", views_cuenta.palmares_agregar, name="palmares_agregar"),
    path("perfil/palmares/<int:pk>/borrar/", views_cuenta.palmares_borrar, name="palmares_borrar"),

    # Autos e invitaciones
    path("autos/", vc.autos, name="autos"),
    path("autos/nuevo/", vc.auto_nuevo, name="auto_nuevo"),
    path("autos/<int:pk>/", vc.auto, name="auto"),
    path("autos/<int:pk>/editar/", vc.auto_editar, name="auto_editar"),
    path("autos/<int:pk>/publicar/", vc.auto_publicar, name="auto_publicar"),
    path("autos/<int:pk>/invitar/", vc.auto_invitar, name="auto_invitar"),
    path("autos/<int:pk>/pilotos/<int:perfil_pk>/quitar/", vc.auto_quitar, name="auto_quitar"),
    path("autos/<int:pk>/pilotos/<int:perfil_pk>/principal/", vc.auto_transferir, name="auto_transferir"),
    path("autos/<int:pk>/portada/", vc.auto_portada, name="auto_portada"),
    path("autos/<int:auto_pk>/archivos/", vc.archivo_subir, name="auto_archivo_subir"),
    path("invitaciones/<int:pk>/", vc.invitacion_responder, name="invitacion_responder"),

    # Archivos
    path("archivos/", vc.archivos, name="archivos"),
    path("archivos/subir/", vc.archivo_subir, name="archivo_subir"),
    path("archivos/<int:pk>/visibilidad/", vc.archivo_visibilidad, name="archivo_visibilidad"),
    path("archivos/<int:pk>/borrar/", vc.archivo_borrar, name="archivo_borrar"),
]
