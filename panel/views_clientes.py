"""
Clientes en el panel: lista, alta/edición y ficha con cuenta corriente, vehículos y órdenes.
Pagos de cuenta corriente con clientes.servicios.registrar_pago (efectivo entra a la caja).
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from clientes.models import Cliente
from clientes.servicios import registrar_pago
from core.acceso import solo_personal
from core.models import SesionCaja
from taller import permisos

from .forms_gestion import ClienteForm, PagoCuentaForm


def _puede(user, perm) -> bool:
    return user.is_superuser or user.has_perm(perm)


def _exigir(user, perm):
    if not _puede(user, perm):
        raise PermissionDenied


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


@solo_personal
def lista(request):
    _exigir(request.user, "clientes.ver_clientes")
    q = (request.GET.get("q") or "").strip()
    qs = Cliente.objects.select_related("cuenta_corriente")
    if request.GET.get("inactivos") != "1":
        qs = qs.filter(activo=True)
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(doc_numero__icontains=q) | Q(telefono__icontains=q)
                       | Q(email__icontains=q) | Q(vehiculos__patente__icontains=q)).distinct()
    if request.GET.get("deudores") == "1":
        qs = qs.filter(cuenta_corriente__saldo__gt=0)
    return render(request, "panel/clientes/lista.html", {
        "titulo": "Clientes", "clientes": qs.order_by("nombre")[:300], "q": q,
        "deudores": request.GET.get("deudores") == "1",
        "puede_crear": _puede(request.user, "clientes.add_cliente"),
    })


@solo_personal
def detalle(request, pk):
    user = request.user
    _exigir(user, "clientes.ver_clientes")
    c = get_object_or_404(Cliente, pk=pk)
    cuenta = getattr(c, "cuenta_corriente", None)
    sesiones = SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA).select_related("caja__sucursal")
    if not permisos.es_gerente(user):
        sesiones = sesiones.filter(caja__sucursal_id=user.sucursal_id) if user.sucursal_id else sesiones.none()
    return render(request, "panel/clientes/detalle.html", {
        "titulo": c.nombre, "c": c, "cuenta": cuenta,
        "movimientos": cuenta.movimientos.select_related("creado_por").order_by("-fecha")[:50] if cuenta else [],
        "vehiculos": c.vehiculos.all(),
        "ordenes": permisos.ordenes_visibles(c.ordenes.all(), user).order_by("-numero")[:20]
        if _puede(user, permisos.PERM_CAMBIAR_ESTADO) else [],
        "puede_editar": _puede(user, "clientes.change_cliente"),
        "puede_pago": _puede(user, "clientes.movimientos_cc") and cuenta and cuenta.saldo > 0,
        "form_pago": PagoCuentaForm(),
        "sesiones": sesiones,
    })


@solo_personal
def cliente_form(request, pk=None):
    _exigir(request.user, "clientes.change_cliente" if pk else "clientes.add_cliente")
    c = get_object_or_404(Cliente, pk=pk) if pk else None
    form = ClienteForm(request.POST or None, instance=c)
    if request.method == "POST" and form.is_valid():
        try:
            c = form.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Cliente guardado.")
            return redirect("clientes:detalle", c.pk)
    return render(request, "panel/form_pagina.html", {
        "titulo": "Editar cliente" if c else "Nuevo cliente", "form": form,
        "volver": f"/panel/clientes/{c.pk}/" if c else "/panel/clientes/",
    })


@solo_personal
def pago(request, pk):
    if request.method != "POST":
        return redirect("clientes:detalle", pk)
    c = get_object_or_404(Cliente, pk=pk)
    form = PagoCuentaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Revisá el monto.")
        return redirect("clientes:detalle", c.pk)
    sesion = None
    if request.POST.get("sesion"):
        sesion = SesionCaja.objects.filter(pk=request.POST["sesion"]).select_related("caja").first()
    try:
        registrar_pago(c, request.user, sesion=sesion, **form.cleaned_data)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    else:
        messages.success(request, "Pago registrado.")
    return redirect("clientes:detalle", c.pk)
