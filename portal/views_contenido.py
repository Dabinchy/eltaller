"""
Autos del piloto, invitaciones y archivos (fotos, videos, setups, telemetría, documentos).
Las reglas están en portal/servicios_contenido.py.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import servicios_contenido as sc
from .acceso import piloto_requerido
from .forms import ArchivoForm, AutoForm, InvitarForm
from .models import PerfilPiloto
from .models_contenido import Archivo, Auto, PilotoAuto, piloto_habilitado


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _mi_auto(request, pk) -> tuple[Auto, PilotoAuto]:
    """El auto, sólo si soy piloto aceptado (si no, 404: no revela que existe)."""
    pa = get_object_or_404(
        PilotoAuto.objects.select_related("auto"), auto_id=pk, piloto=request.perfil, estado=PilotoAuto.Estado.ACEPTADA,
    )
    return pa.auto, pa


def _volver(pk, ancla=""):
    return redirect(reverse("portal:auto", args=[pk]) + (f"#{ancla}" if ancla else ""))


# ============================================================
# Autos
# ============================================================

@piloto_requerido
def autos(request):
    perfil = request.perfil
    mios = PilotoAuto.objects.filter(piloto=perfil, estado=PilotoAuto.Estado.ACEPTADA).select_related("auto")
    invitaciones = PilotoAuto.objects.filter(piloto=perfil, estado=PilotoAuto.Estado.PENDIENTE).select_related(
        "auto", "invitado_por"
    )
    return render(request, "portal/autos.html", {"titulo": "Mis autos", "mios": mios, "invitaciones": invitaciones})


@piloto_requerido
def auto_nuevo(request):
    form = AutoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            auto = sc.crear_auto(request.perfil, **form.cleaned_data)
        except (ValidationError, PermissionDenied) as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Auto creado. Sumale fotos y, cuando quieras, publicalo.")
            return redirect("portal:auto", auto.pk)
    return render(request, "panel/form_pagina.html", {
        "titulo": "Nuevo auto", "form": form, "volver": reverse("portal:autos"),
    })


@piloto_requerido
def auto(request, pk):
    a, pa = _mi_auto(request, pk)
    es_principal = pa.principal
    archivos = a.archivos.all()
    return render(request, "portal/auto.html", {
        "titulo": str(a), "auto": a, "es_principal": es_principal,
        "pilotos": a.pilotos.select_related("piloto").order_by("-principal", "created_at"),
        "fotos": [x for x in archivos if x.tipo == Archivo.Tipo.FOTO],
        "archivos": archivos,
        "form_auto": AutoForm(instance=a) if es_principal else None,
        "form_invitar": InvitarForm() if es_principal else None,
        "form_archivo": ArchivoForm(),
    })


@require_POST
@piloto_requerido
def auto_editar(request, pk):
    a, pa = _mi_auto(request, pk)
    if not pa.principal:
        raise PermissionDenied
    form = AutoForm(request.POST, instance=a)
    if form.is_valid():
        try:
            form.save()
            if a.aprobado and a.cambio_tras_aprobacion:
                messages.info(request, "Guardado. Los cambios quedan marcados para revisión de tu asociación.")
            else:
                messages.success(request, "Presentación guardada.")
        except ValidationError as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Revisá los datos: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return _volver(a.pk)


@require_POST
@piloto_requerido
def auto_publicar(request, pk):
    a, _ = _mi_auto(request, pk)
    try:
        sc.publicar_auto(a, request.perfil, request.POST.get("publicar") == "1")
        messages.success(request, "Publicado (se verá cuando esté aprobado)." if a.publicado else "Auto oculto de la web.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return _volver(a.pk)


@require_POST
@piloto_requerido
def auto_invitar(request, pk):
    a, _ = _mi_auto(request, pk)
    form = InvitarForm(request.POST)
    if form.is_valid():
        buscado = form.cleaned_data["piloto"].strip().lstrip("@")
        candidatos = list(PerfilPiloto.objects.filter(
            Q(usuario__username__iexact=buscado) | Q(nombre_publico__iexact=buscado), usuario__is_active=True,
        ).exclude(pk=request.perfil.pk)[:2])
        candidatos = [c for c in candidatos if piloto_habilitado(c)]
        if not candidatos:
            messages.error(request, "No encontramos un piloto aprobado con ese usuario o nombre.")
        elif len(candidatos) > 1:
            messages.error(request, "Hay más de un piloto con ese nombre: escribí su usuario.")
        else:
            try:
                sc.invitar_piloto(a, request.perfil, candidatos[0])
                messages.success(request, f"Invitación enviada a {candidatos[0]}. Tiene que aceptarla.")
            except (ValidationError, PermissionDenied) as e:
                messages.error(request, _texto(e))
    return _volver(a.pk, "pilotos")


@require_POST
@piloto_requerido
def invitacion_responder(request, pk):
    inv = get_object_or_404(PilotoAuto, pk=pk, piloto=request.perfil)
    aceptar = request.POST.get("aceptar") == "1"
    try:
        sc.responder_invitacion(inv, request.perfil, aceptar)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
        return redirect("portal:autos")
    if aceptar:
        messages.success(request, f"Ahora sos piloto de {inv.auto}.")
        return redirect("portal:auto", inv.auto_id)
    messages.info(request, "Invitación rechazada.")
    return redirect("portal:autos")


@require_POST
@piloto_requerido
def auto_quitar(request, pk, perfil_pk):
    a, _ = _mi_auto(request, pk)
    quitado = get_object_or_404(PerfilPiloto, pk=perfil_pk)
    try:
        sc.quitar_piloto(a, request.perfil, quitado)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
        return _volver(a.pk, "pilotos")
    if quitado.pk == request.perfil.pk:
        messages.info(request, f"Saliste de {a}.")
        return redirect("portal:autos")
    messages.success(request, f"{quitado} ya no es piloto de este auto.")
    return _volver(a.pk, "pilotos")


@require_POST
@piloto_requerido
def auto_transferir(request, pk, perfil_pk):
    a, _ = _mi_auto(request, pk)
    try:
        sc.transferir_principal(a, request.perfil, get_object_or_404(PerfilPiloto, pk=perfil_pk))
        messages.success(request, "Listo: el auto tiene un nuevo piloto principal.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return _volver(a.pk, "pilotos")


@require_POST
@piloto_requerido
def auto_portada(request, pk):
    a, _ = _mi_auto(request, pk)
    foto = a.archivos.filter(pk=request.POST.get("archivo") or 0, tipo=Archivo.Tipo.FOTO).first()
    try:
        sc.elegir_portada(a, request.perfil, foto)
        messages.success(request, "Portada actualizada.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return _volver(a.pk, "archivos")


# ============================================================
# Archivos
# ============================================================

@piloto_requerido
def archivos(request):
    perfil = request.perfil
    usados, total = sc.uso_cuota(perfil)
    subidos = Archivo.objects.filter(subido_por=request.user).select_related("auto")
    return render(request, "portal/archivos.html", {
        "titulo": "Mis archivos", "archivos": subidos, "form_archivo": ArchivoForm(),
        "usados_mb": usados / (1024 * 1024), "total_mb": total / (1024 * 1024),
        "porcentaje": min(100, round(usados * 100 / total)) if total else 0,
    })


@require_POST
@piloto_requerido
def archivo_subir(request, auto_pk=None):
    auto = _mi_auto(request, auto_pk)[0] if auto_pk else None
    form = ArchivoForm(request.POST, request.FILES)
    if form.is_valid():
        d = form.cleaned_data
        try:
            sc.subir_archivo_piloto(
                request.perfil, tipo=d["tipo"], titulo=d["titulo"], descripcion=d["descripcion"],
                visibilidad=d["visibilidad"], archivo=d["archivo"], url_video=d["url_video"], auto=auto,
            )
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
        else:
            if d["visibilidad"] == Archivo.Visibilidad.PUBLICO:
                messages.info(request, "Subido. Se va a ver en la web cuando tu asociación lo apruebe.")
            else:
                messages.success(request, "Subido.")
    else:
        messages.error(request, "Revisá el archivo: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return _volver(auto.pk, "archivos") if auto else redirect("portal:archivos")


def _mi_archivo(request, pk) -> Archivo:
    return get_object_or_404(Archivo, pk=pk, subido_por=request.user)


@require_POST
@piloto_requerido
def archivo_visibilidad(request, pk):
    archivo = _mi_archivo(request, pk)
    try:
        sc.cambiar_visibilidad(archivo, request.perfil, request.POST.get("visibilidad", ""))
        messages.success(request, "Visibilidad actualizada.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    volver = request.POST.get("volver")
    return redirect(volver) if _seguro(volver) else redirect("portal:archivos")


@require_POST
@piloto_requerido
def archivo_borrar(request, pk):
    archivo = get_object_or_404(Archivo, pk=pk)
    try:
        sc.eliminar_archivo(archivo, request.user)
        messages.success(request, "Archivo borrado.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    volver = request.POST.get("volver")
    return redirect(volver) if _seguro(volver) else redirect("portal:archivos")


def _seguro(url: str | None) -> bool:
    """Sólo se vuelve a direcciones internas del portal (evita redirecciones abiertas)."""
    return bool(url) and url.startswith("/portal/") and "//" not in url
