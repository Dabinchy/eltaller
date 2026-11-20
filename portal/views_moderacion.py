"""
Moderación en el portal (/portal/moderacion/) para los moderadores de cada asociación.

Cada moderador ve sólo lo de las asociaciones que modera y nunca lo propio. Las reglas
(alcance, motivo obligatorio, historial) están en portal/servicios*.py: acá sólo se llaman.
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acceso import solo_portal
from panel.forms_sitio import NovedadAsociacionForm
from sitio.models import Publicacion

from . import permisos, servicios
from . import servicios_contenido as sc
from .models import Membresia, PerfilPiloto, RegistroModeracion
from .models_contenido import Archivo, Auto

M = Membresia


def moderador_requerido(vista):
    @solo_portal
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        asociaciones = permisos.asociaciones_moderadas(request.user)
        if not asociaciones.exists():
            raise PermissionDenied("No sos moderador de ninguna asociación.")
        request.asociaciones = asociaciones
        return vista(request, *args, **kwargs)

    return envoltura


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _ejecutar(request, funcion, *args, exito: str):
    try:
        funcion(*args)
        messages.success(request, exito)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))


def _volver(request, defecto="portal:moderacion"):
    destino = request.POST.get("volver") or ""
    if destino.startswith("/portal/moderacion/") and "//" not in destino:
        return redirect(destino)
    return redirect(defecto)


def _perfiles(asociaciones, excluir_usuario):
    """Perfiles de pilotos con membresía aprobada en alguna de esas asociaciones."""
    return PerfilPiloto.objects.filter(
        usuario__membresias__asociacion__in=asociaciones,
        usuario__membresias__rol=M.Rol.PILOTO,
        usuario__membresias__estado=M.Estado.APROBADA,
    ).exclude(usuario=excluir_usuario).distinct()


# ============================================================
# Cola de pendientes
# ============================================================

@moderador_requerido
def inicio(request):
    yo, asocs = request.user, request.asociaciones
    perfiles = _perfiles(asocs, yo)
    autos = Auto.objects.filter(
        pilotos__principal=True, pilotos__piloto__in=perfiles,
    ).exclude(pilotos__piloto__usuario=yo).distinct()
    return render(request, "portal/moderacion/inicio.html", {
        "titulo": "Moderación",
        "asociaciones": asocs,
        "cuentas": M.objects.filter(asociacion__in=asocs, rol=M.Rol.PILOTO, estado=M.Estado.PENDIENTE)
                   .exclude(usuario=yo).select_related("usuario", "asociacion", "usuario__perfil_piloto"),
        "perfiles_nuevos": perfiles.filter(perfil_publico=True, aprobado=False),
        "perfiles_cambios": perfiles.filter(aprobado=True, cambio_tras_aprobacion=True),
        "menores": [p for p in perfiles.filter(consentimiento_tutor=False, perfil_publico=True)
                    .exclude(fecha_nacimiento=None) if p.es_menor],
        "autos_nuevos": autos.filter(publicado=True, aprobado=False),
        "autos_cambios": autos.filter(aprobado=True, cambio_tras_aprobacion=True),
        "archivos": Archivo.objects.filter(
            visibilidad=Archivo.Visibilidad.PUBLICO, aprobado=False, subido_por__perfil_piloto__in=perfiles,
        ).exclude(subido_por=yo).exclude(auto__pilotos__piloto__usuario=yo).select_related("auto", "piloto", "subido_por"),
    })


@require_POST
@moderador_requerido
def membresia(request, pk):
    m = get_object_or_404(M, pk=pk, asociacion__in=request.asociaciones, rol=M.Rol.PILOTO)
    accion, motivo = request.POST.get("accion"), request.POST.get("motivo", "")
    if accion == "aprobar":
        _ejecutar(request, servicios.aprobar_membresia, m, request.user, exito=f"{m.usuario} aprobado en {m.asociacion}.")
    elif accion == "rechazar":
        _ejecutar(request, servicios.rechazar_membresia, m, request.user, motivo, exito="Solicitud rechazada.")
    elif accion == "suspender":
        _ejecutar(request, servicios.suspender_membresia, m, request.user, motivo, exito="Piloto suspendido.")
    elif accion == "spam":
        try:
            desactivada = servicios.marcar_spam(m, request.user)
            messages.success(request, "Marcado como spam" + (" y cuenta desactivada." if desactivada else "."))
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Acción desconocida.")
    return _volver(request)


@require_POST
@moderador_requerido
def perfil(request, pk):
    p = get_object_or_404(PerfilPiloto, pk=pk)
    accion, motivo = request.POST.get("accion"), request.POST.get("motivo", "")
    acciones = {
        "aprobar": (servicios.aprobar_perfil, (), "Perfil aprobado."),
        "retirar": (servicios.retirar_aprobacion_perfil, (motivo,), "Aprobación retirada."),
        "revisado": (servicios.marcar_perfil_revisado, (), "Cambios aceptados."),
        "consentimiento": (servicios.registrar_consentimiento_tutor, (), "Consentimiento del tutor registrado."),
    }
    if accion == "cuota":
        crudo = (request.POST.get("cuota_mb") or "").strip()
        try:
            cuota = int(crudo) if crudo else None
        except ValueError:
            messages.error(request, "La cuota tiene que ser un número de MB.")
        else:
            _ejecutar(request, servicios.cambiar_cuota, p, request.user, cuota, exito="Cuota actualizada.")
    elif accion in acciones:
        funcion, extra, exito = acciones[accion]
        _ejecutar(request, funcion, p, request.user, *extra, exito=exito)
    else:
        messages.error(request, "Acción desconocida.")
    return _volver(request)


@require_POST
@moderador_requerido
def auto(request, pk):
    a = get_object_or_404(Auto, pk=pk)
    accion, motivo = request.POST.get("accion"), request.POST.get("motivo", "")
    if accion == "aprobar":
        _ejecutar(request, sc.aprobar_auto, a, request.user, exito="Auto aprobado.")
    elif accion == "retirar":
        _ejecutar(request, sc.retirar_aprobacion_auto, a, request.user, motivo, exito="Aprobación retirada.")
    elif accion == "revisado":
        _ejecutar(request, sc.marcar_auto_revisado, a, request.user, exito="Cambios aceptados.")
    else:
        messages.error(request, "Acción desconocida.")
    return _volver(request)


@require_POST
@moderador_requerido
def archivo(request, pk):
    x = get_object_or_404(Archivo, pk=pk)
    accion, motivo = request.POST.get("accion"), request.POST.get("motivo", "")
    if accion == "aprobar":
        _ejecutar(request, sc.aprobar_archivo, x, request.user, exito="Archivo aprobado.")
    elif accion == "retirar":
        _ejecutar(request, sc.retirar_aprobacion_archivo, x, request.user, motivo, exito="Aprobación retirada.")
    else:
        messages.error(request, "Acción desconocida.")
    return _volver(request)


# ============================================================
# Miembros e historial
# ============================================================

@moderador_requerido
def miembros(request):
    asocs = request.asociaciones
    q = (request.GET.get("q") or "").strip()
    qs = M.objects.filter(asociacion__in=asocs, rol=M.Rol.PILOTO).exclude(estado=M.Estado.PENDIENTE).select_related(
        "usuario", "asociacion", "usuario__perfil_piloto"
    ).order_by("asociacion__nombre", "usuario__last_name")
    if q:
        qs = qs.filter(Q(usuario__first_name__icontains=q) | Q(usuario__last_name__icontains=q)
                       | Q(usuario__username__icontains=q) | Q(usuario__dni__icontains=q))
    return render(request, "portal/moderacion/miembros.html", {"titulo": "Pilotos", "membresias": qs[:300], "q": q})


@require_POST
@moderador_requerido
def reactivar(request, pk):
    m = get_object_or_404(M, pk=pk, asociacion__in=request.asociaciones, rol=M.Rol.PILOTO, estado=M.Estado.SUSPENDIDA)
    _ejecutar(request, servicios.aprobar_membresia, m, request.user, exito="Piloto reactivado.")
    return redirect("portal:moderacion_miembros")


@moderador_requerido
def historial(request):
    registros = RegistroModeracion.objects.filter(asociacion__in=request.asociaciones).select_related("actor", "asociacion")
    return render(request, "portal/moderacion/historial.html", {"titulo": "Historial", "registros": registros[:300]})


# ============================================================
# Novedades de la asociación (se ven en Campeonatos)
# ============================================================
# Cada moderador escribe y edita sólo novedades de las asociaciones que modera; nunca de
# El Taller ni de El Prepa (el formulario fija la parte en Campeonatos).

def _novedades_de(request):
    return (Publicacion.objects.filter(asociacion__in=request.asociaciones)
            .select_related("asociacion", "campeonato", "autor"))


@moderador_requerido
def novedades(request):
    return render(request, "portal/moderacion/novedades.html", {
        "titulo": "Novedades",
        "pagina": Paginator(_novedades_de(request), 20).get_page(request.GET.get("pagina")),
        "asociaciones": request.asociaciones, "ahora": timezone.now(),
    })


@moderador_requerido
def novedad_form(request, pk=None):
    obj = get_object_or_404(_novedades_de(request), pk=pk) if pk else None
    form = NovedadAsociacionForm(request.POST or None, request.FILES or None, instance=obj,
                                 asociaciones=request.asociaciones)
    if request.method == "POST" and form.is_valid():
        nueva = obj is None
        pub = form.save(commit=False)
        if nueva:
            pub.autor = request.user
        pub.save()
        servicios.registrar(request.user, RegistroModeracion.Accion.CREAR if nueva else RegistroModeracion.Accion.EDITAR,
                            pub, pub.asociacion)
        messages.success(request, f"«{pub}» guardada{' y publicada' if pub.publicada else ' como borrador'}.")
        return redirect("portal:moderacion_novedades")
    return render(request, "portal/moderacion/novedad_form.html", {
        "titulo": "Editar novedad" if obj else "Nueva novedad", "form": form, "objeto": obj,
        "url_web": reverse("sitio:publicacion", args=[obj.slug]) if obj else "",
    })


@require_POST
@moderador_requerido
def novedad_accion(request, pk):
    pub = get_object_or_404(_novedades_de(request), pk=pk)
    accion = request.POST.get("accion")
    A = RegistroModeracion.Accion
    if accion in ("publicar", "ocultar"):
        pub.publicada = accion == "publicar"
        pub.save(update_fields=["publicada"])
        servicios.registrar(request.user, A.PUBLICAR if pub.publicada else A.OCULTAR, pub, pub.asociacion)
        messages.success(request, f"«{pub}» {'publicada' if pub.publicada else 'ya no se ve en la web'}.")
    elif accion == "borrar":
        servicios.registrar(request.user, A.BORRAR, pub, pub.asociacion)
        titulo = str(pub)
        pub.delete()
        messages.success(request, f"«{titulo}» borrada.")
    else:
        raise PermissionDenied
    return redirect("portal:moderacion_novedades")
