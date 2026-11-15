"""
Vistas del portal (por ahora: inicio) y entrega de archivos privados con control de permisos.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.http import content_disposition_header

from core.acceso import solo_portal

from . import permisos
from .models import PerfilPiloto
from .models_contenido import Archivo
from .servicios import estado_de_cuenta


@solo_portal
def inicio(request):
    return render(request, "portal/inicio.html", {"titulo": "Inicio", "estado": estado_de_cuenta(request.user)})


# ============================================================
# Archivos privados
# ============================================================

def _servir(campo, *, adjunto: bool, publico: bool, nombre: str | None = None) -> HttpResponse:
    """
    Entrega un archivo del almacenamiento privado.
    - En producción (PRIVATE_X_ACCEL_PREFIX) Django sólo autoriza y nginx envía el archivo.
    - Imágenes ya procesadas se muestran; todo lo demás se DESCARGA (nunca se abre en el navegador).
    """
    nombre = nombre or Path(campo.name).name
    tipo = "application/octet-stream" if adjunto else (mimetypes.guess_type(nombre)[0] or "application/octet-stream")
    prefijo = settings.PRIVATE_X_ACCEL_PREFIX
    if prefijo:
        respuesta = HttpResponse(content_type=tipo)
        respuesta["X-Accel-Redirect"] = prefijo.rstrip("/") + "/" + quote(campo.name)
    else:
        try:
            respuesta = FileResponse(campo.open("rb"), content_type=tipo)
        except FileNotFoundError:
            raise Http404("Archivo no encontrado.")
    respuesta["Content-Disposition"] = content_disposition_header(adjunto, nombre)
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "public, max-age=3600" if publico else "private, no-store"
    return respuesta


def descargar_archivo(request, pk: int):
    archivo = get_object_or_404(Archivo, pk=pk)
    # 404 (y no 403) para no revelar que el archivo existe.
    if not archivo.archivo or not permisos.puede_ver_archivo(request.user, archivo):
        raise Http404()
    publico = archivo.visibilidad == Archivo.Visibilidad.PUBLICO and archivo.aprobado
    if request.GET.get("mini") and archivo.miniatura:
        return _servir(archivo.miniatura, adjunto=False, publico=publico)
    return _servir(archivo.archivo, adjunto=not archivo.es_imagen, publico=publico, nombre=archivo.nombre_archivo)


def foto_perfil(request, slug: str):
    perfil = get_object_or_404(PerfilPiloto, slug=slug)
    user = request.user
    permitido = perfil.visible_en_web or (
        user.is_authenticated and user.is_active and (
            perfil.usuario_id == user.pk
            or not user.es_portal  # personal del taller
            or permisos.asociaciones_moderadas(user).filter(pk__in=perfil.asociaciones_aprobadas()).exists()
        )
    )
    if not perfil.foto or not permitido:
        raise Http404()
    campo = perfil.foto_miniatura if request.GET.get("mini") and perfil.foto_miniatura else perfil.foto
    return _servir(campo, adjunto=False, publico=perfil.visible_en_web)
