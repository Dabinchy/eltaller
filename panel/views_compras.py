"""
Compras y proveedores en el panel.
- registrar_compras (gerente, jefe): cargar y confirmar compras de su sucursal.
- anular_compras (gerente).
- La factura adjunta es privada: se descarga por esta vista (con permisos), nunca por /media/.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from compras.models import Compra, CompraDetalle, Proveedor
from core.acceso import solo_personal
from portal.views import _servir
from taller.permisos import es_gerente

from .forms_gestion import CompraForm, CompraItemForm, ProveedorForm


def _puede(user, perm) -> bool:
    return user.is_superuser or user.has_perm(perm)


def _exigir(user, perm):
    if not _puede(user, perm):
        raise PermissionDenied


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _compras(user):
    qs = Compra.objects.select_related("proveedor", "sucursal")
    if es_gerente(user):
        return qs
    return qs.filter(sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()


@solo_personal
def lista(request):
    _exigir(request.user, "compras.registrar_compras")
    qs = _compras(request.user)
    estado = request.GET.get("estado") or ""
    if estado in Compra.Estado.values:
        qs = qs.filter(estado=estado)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(proveedor__nombre__icontains=q) | Q(observaciones__icontains=q))
    return render(request, "panel/compras/lista.html", {
        "titulo": "Compras", "compras": qs[:300], "estado": estado, "q": q, "estados": Compra.Estado.choices,
    })


@solo_personal
def nueva(request):
    user = request.user
    _exigir(user, "compras.registrar_compras")
    form = CompraForm(request.POST or None, request.FILES or None, user=user, es_gerente=es_gerente(user))
    if request.method == "POST" and form.is_valid():
        compra = form.save(commit=False)
        compra.creada_por = user
        try:
            compra.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Compra creada en borrador: cargá los productos.")
            return redirect("compras:detalle", compra.pk)
    return render(request, "panel/form_pagina.html", {
        "titulo": "Nueva compra", "form": form, "volver": "/panel/compras/", "multipart": True,
        "ayuda": "¿El proveedor no está? Cargalo en Proveedores.",
    })


@solo_personal
def detalle(request, pk):
    user = request.user
    _exigir(user, "compras.registrar_compras")
    c = get_object_or_404(_compras(user), pk=pk)
    borrador = c.estado == Compra.Estado.BORRADOR
    return render(request, "panel/compras/detalle.html", {
        "titulo": f"Compra #{c.pk}", "c": c, "items": c.detalles.select_related("producto"),
        "borrador": borrador, "form_item": CompraItemForm() if borrador else None,
        "puede_anular": c.estado != Compra.Estado.ANULADA and _puede(user, "compras.anular_compras"),
    })


@require_POST
@solo_personal
def item_agregar(request, pk):
    _exigir(request.user, "compras.registrar_compras")
    c = get_object_or_404(_compras(request.user), pk=pk)
    form = CompraItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.compra = c
        try:
            item.save()
        except ValidationError as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Revisá el ítem: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return redirect("compras:detalle", c.pk)


@require_POST
@solo_personal
def item_borrar(request, pk, item_pk):
    _exigir(request.user, "compras.registrar_compras")
    c = get_object_or_404(_compras(request.user), pk=pk)
    try:
        get_object_or_404(CompraDetalle, pk=item_pk, compra=c).delete()
    except ValidationError as e:
        messages.error(request, _texto(e))
    return redirect("compras:detalle", c.pk)


@require_POST
@solo_personal
def confirmar(request, pk):
    c = get_object_or_404(_compras(request.user), pk=pk)
    try:
        c.confirmar(user=request.user)
        messages.success(request, "Compra confirmada: el stock y el costo promedio quedaron actualizados.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect("compras:detalle", c.pk)


@require_POST
@solo_personal
def anular(request, pk):
    c = get_object_or_404(_compras(request.user), pk=pk)
    try:
        c.anular(user=request.user)
        messages.success(request, "Compra anulada.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect("compras:detalle", c.pk)


@solo_personal
def adjunto(request, pk):
    _exigir(request.user, "compras.registrar_compras")
    c = get_object_or_404(_compras(request.user), pk=pk)
    if not c.documento_adjunto:
        raise Http404()
    return _servir(c.documento_adjunto, adjunto=True, publico=False)


# ============================================================
# Proveedores
# ============================================================

@solo_personal
def proveedores(request):
    _exigir(request.user, "compras.gestionar_proveedores")
    q = (request.GET.get("q") or "").strip()
    qs = Proveedor.objects.all()
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(documento__icontains=q))
    return render(request, "panel/compras/proveedores.html", {"titulo": "Proveedores", "proveedores": qs, "q": q})


@solo_personal
def proveedor_form(request, pk=None):
    _exigir(request.user, "compras.gestionar_proveedores")
    p = get_object_or_404(Proveedor, pk=pk) if pk else None
    form = ProveedorForm(request.POST or None, instance=p)
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Proveedor guardado.")
            return redirect("compras:proveedores")
    return render(request, "panel/form_pagina.html", {
        "titulo": "Editar proveedor" if p else "Nuevo proveedor", "form": form, "volver": "/panel/compras/proveedores/",
    })
