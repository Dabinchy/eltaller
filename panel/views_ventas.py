"""
Ventas en el panel: por cobrar, mostrador, cobro, listado, comprobante y anulación.
Las reglas están en ventas.models (finalizar, anular) y en clientes (límite de crédito).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.acceso import solo_personal
from core.models import SesionCaja
from taller import permisos
from ventas.models import Venta, VentaDetalle

from .forms_ventas import AnularVentaForm, ClienteVentaForm, CobroForm, ItemVentaForm

EV = Venta.Estado


def _texto(e: Exception) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _exigir(user, perm):
    if not (user.is_superuser or user.has_perm(perm)):
        raise PermissionDenied


def _ventas_visibles(user):
    qs = Venta.objects.select_related("sucursal", "caja", "cliente", "creada_por")
    if permisos.es_gerente(user):
        return qs
    return qs.filter(sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()


def _venta(user, pk):
    return get_object_or_404(_ventas_visibles(user), pk=pk)


def _orden_de(venta):
    try:
        return venta.orden
    except Exception:
        return None


def _sesiones_abiertas(user):
    qs = SesionCaja.objects.filter(estado=SesionCaja.Estado.ABIERTA).select_related("caja__sucursal")
    if permisos.es_gerente(user):
        return qs
    return qs.filter(caja__sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()


# ============================================================
# Listados
# ============================================================

@solo_personal
def por_cobrar(request):
    _exigir(request.user, "ventas.finalizar_venta")
    ventas = _ventas_visibles(request.user).filter(estado=EV.ABIERTA).order_by("creada_el")
    return render(request, "panel/ventas/por_cobrar.html", {"titulo": "Por cobrar", "ventas": ventas})


@solo_personal
def listado(request):
    _exigir(request.user, "ventas.ver_ventas")
    hoy = timezone.localdate()
    desde = parse_date(request.GET.get("desde") or "") or hoy - timedelta(days=7)
    hasta = parse_date(request.GET.get("hasta") or "") or hoy
    qs = _ventas_visibles(request.user).filter(creada_el__date__gte=desde, creada_el__date__lte=hasta)
    estado = request.GET.get("estado") or ""
    if estado in EV.values:
        qs = qs.filter(estado=estado)
    q = (request.GET.get("q") or "").strip()
    if q:
        filtro = Q(cliente__nombre__icontains=q) | Q(observacion__icontains=q)
        if q.isdigit():
            filtro |= Q(pk=int(q))
        qs = qs.filter(filtro)
    totales = qs.filter(estado=EV.FINALIZADA).aggregate(t=Sum("total"))
    return render(request, "panel/ventas/listado.html", {
        "titulo": "Ventas", "ventas": qs.order_by("-creada_el")[:300], "desde": desde, "hasta": hasta,
        "estado": estado, "q": q, "estados": EV.choices, "total_finalizadas": totales["t"] or 0,
    })


# ============================================================
# Mostrador
# ============================================================

@solo_personal
def mostrador(request):
    """Venta de repuestos sin orden: se crea ABIERTA en una caja abierta de la sucursal."""
    user = request.user
    _exigir(user, "ventas.crear_venta")
    sesiones = list(_sesiones_abiertas(user))
    if request.method == "POST" or len(sesiones) == 1:
        sesion = sesiones[0] if len(sesiones) == 1 else get_object_or_404(
            _sesiones_abiertas(user), pk=request.POST.get("sesion"))
        venta = Venta.objects.create(
            sucursal=sesion.caja.sucursal, caja=sesion.caja, sesion=sesion, creada_por=user,
            observacion="Venta de mostrador",
        )
        return redirect("ventas:venta", venta.pk)
    return render(request, "panel/ventas/mostrador.html", {"titulo": "Venta de mostrador", "sesiones": sesiones})


# ============================================================
# Venta (cobro o detalle)
# ============================================================

def _puede_precio(user) -> bool:
    return user.is_superuser or user.has_perm("productos.gestionar_precios")


@solo_personal
def venta(request, pk):
    user = request.user
    _exigir(user, "ventas.ver_ventas")
    v = _venta(user, pk)
    orden = _orden_de(v)
    abierta = v.estado == EV.ABIERTA
    cuenta = None
    if v.cliente_id:
        cuenta = getattr(v.cliente, "cuenta_corriente", None)
    return render(request, "panel/ventas/venta.html", {
        "titulo": f"Venta #{v.pk}",
        "venta": v,
        "orden": orden,
        "detalles": v.detalles.select_related("producto"),
        "editable": abierta and orden is None and (user.is_superuser or user.has_perm("ventas.crear_venta")),
        "puede_cobrar": abierta and (user.is_superuser or user.has_perm("ventas.finalizar_venta")),
        "puede_anular": v.estado == EV.FINALIZADA and (user.is_superuser or user.has_perm("ventas.anular_venta")),
        "ver_costos": user.is_superuser or user.has_perm("productos.ver_costos"),
        "form_item": ItemVentaForm(puede_precio=_puede_precio(user)),
        "form_cliente": ClienteVentaForm(initial={"cliente": v.cliente_id}),
        "form_cobro": CobroForm(),
        "form_anular": AnularVentaForm(),
        "cuenta": cuenta,
        "disponible": (v.cliente.limite_credito - cuenta.saldo) if cuenta else None,
    })


def _venta_abierta_editable(request, pk):
    user = request.user
    _exigir(user, "ventas.crear_venta")
    v = _venta(user, pk)
    if v.estado != EV.ABIERTA:
        raise ValidationError("La venta ya no está abierta.")
    if _orden_de(v) is not None:
        raise ValidationError("Los ítems de una venta de orden se cambian en la orden, no acá.")
    return v


@require_POST
@solo_personal
def item_agregar(request, pk):
    try:
        v = _venta_abierta_editable(request, pk)
    except ValidationError as e:
        messages.error(request, _texto(e))
        return redirect("ventas:venta", pk)
    form = ItemVentaForm(request.POST, puede_precio=_puede_precio(request.user))
    if form.is_valid():
        try:
            VentaDetalle.objects.create(
                venta=v, producto=form.cleaned_data["producto"], cantidad=form.cleaned_data["cantidad"],
                precio_unitario=form.cleaned_data.get("precio_unitario"),
            )
        except ValidationError as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Revisá el producto y la cantidad.")
    return redirect("ventas:venta", v.pk)


@require_POST
@solo_personal
def item_borrar(request, pk, item_pk):
    try:
        v = _venta_abierta_editable(request, pk)
        get_object_or_404(VentaDetalle, pk=item_pk, venta=v).delete()
    except ValidationError as e:
        messages.error(request, _texto(e))
    return redirect("ventas:venta", pk)


@require_POST
@solo_personal
def cliente(request, pk):
    _exigir(request.user, "ventas.crear_venta")
    v = _venta(request.user, pk)
    if v.estado != EV.ABIERTA or _orden_de(v) is not None:
        messages.error(request, "El cliente de esta venta no se puede cambiar.")
        return redirect("ventas:venta", v.pk)
    form = ClienteVentaForm(request.POST)
    if form.is_valid():
        v.cliente = form.cleaned_data["cliente"]
        v.save(update_fields=["cliente"])
    return redirect("ventas:venta", v.pk)


@require_POST
@solo_personal
def cobrar(request, pk):
    v = _venta(request.user, pk)
    form = CobroForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Revisá los montos: " + "; ".join(f"{k}: {e[0]}" for k, e in form.errors.items()))
        return redirect("ventas:venta", v.pk)
    m = form.cleaned_data
    try:
        v.finalizar(
            user=request.user, efectivo=m["monto_efectivo"], tarjeta=m["monto_tarjeta"],
            transferencia=m["monto_transferencia"], ctacte=m["monto_ctacte"],
        )
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
        return redirect("ventas:venta", v.pk)
    messages.success(request, f"Venta #{v.pk} cobrada.")
    return redirect("ventas:comprobante", v.pk)


@require_POST
@solo_personal
def descartar(request, pk):
    """Una venta de mostrador abierta se puede descartar (no deja rastro en stock ni caja)."""
    try:
        v = _venta_abierta_editable(request, pk)
        with transaction.atomic():
            for d in v.detalles.all():
                d.delete()
            v.delete()
        messages.success(request, "Venta descartada.")
        return redirect("ventas:por_cobrar")
    except ValidationError as e:
        messages.error(request, _texto(e))
        return redirect("ventas:venta", pk)


@require_POST
@solo_personal
def anular(request, pk):
    """Sólo el gerente, con su PIN: devuelve stock, efectivo y cuenta corriente."""
    user = request.user
    _exigir(user, "ventas.anular_venta")
    v = _venta(user, pk)
    form = AnularVentaForm(request.POST)
    try:
        if not form.is_valid():
            raise ValidationError("Ingresá tu PIN.")
        if not user.action_pin_hash:
            raise ValidationError("Configurá tu PIN antes de anular ventas.")
        user.verify_action_pin_or_raise(form.cleaned_data["pin"])
        v.anular(user=user)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    else:
        messages.success(request, f"Venta #{v.pk} anulada.")
    return redirect("ventas:venta", v.pk)


@solo_personal
def comprobante(request, pk):
    _exigir(request.user, "ventas.ver_ventas")
    v = _venta(request.user, pk)
    return render(request, "panel/ventas/comprobante.html", {
        "titulo": f"Comprobante venta #{v.pk}", "venta": v, "orden": _orden_de(v),
        "detalles": v.detalles.select_related("producto"),
    })
