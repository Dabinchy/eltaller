from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core import views as core_views
from portal import views as portal_views

urlpatterns = [
    # Sitio público (portada mínima hasta el paso 6)
    path("", core_views.portada, name="portada"),

    # Ingreso único para personal, pilotos y clientes
    path("ingresar/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("ingresar/redireccion/", core_views.redireccion, name="redireccion"),

    # Áreas
    path("panel/", include("core.urls_panel")),
    path("portal/", include("portal.urls")),

    # Archivos privados (cada pedido verifica permisos)
    path("archivos/<int:pk>/", portal_views.descargar_archivo, name="archivo"),
    path("archivos/pilotos/<slug:slug>/foto/", portal_views.foto_perfil, name="foto_perfil"),

    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
