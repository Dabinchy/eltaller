from django.contrib.auth.decorators import login_required
from django.urls import path

from . import views, views_contenido as vc, views_cuenta, views_moderacion as vm, views_taller as vt

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

    # Mi taller (clientes)
    path("taller/", vt.mi_taller, name="mi_taller"),
    path("taller/ordenes/<int:pk>/", vt.orden, name="taller_orden"),
    path("taller/ordenes/<int:pk>/aprobar/", vt.orden_aprobar, name="taller_orden_aprobar"),
    path("taller/ordenes/<int:pk>/comentar/", vt.orden_comentar, name="taller_orden_comentar"),
    path("taller/turnos/", vt.turnos, name="turnos"),

    # Moderación (moderadores de cada asociación)
    path("moderacion/", vm.inicio, name="moderacion"),
    path("moderacion/membresias/<int:pk>/", vm.membresia, name="moderacion_membresia"),
    path("moderacion/perfiles/<int:pk>/", vm.perfil, name="moderacion_perfil"),
    path("moderacion/autos/<int:pk>/", vm.auto, name="moderacion_auto"),
    path("moderacion/archivos/<int:pk>/", vm.archivo, name="moderacion_archivo"),
    path("moderacion/pilotos/", vm.miembros, name="moderacion_miembros"),
    path("moderacion/pilotos/<int:pk>/reactivar/", vm.reactivar, name="moderacion_reactivar"),
    path("moderacion/historial/", vm.historial, name="moderacion_historial"),
]
