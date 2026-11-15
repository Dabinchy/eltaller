"""
Pantallas de caja del panel: ver cajas, abrir, mover efectivo, cerrar y configurar el PIN.
Las reglas (permisos, PIN, saldos) están en el modelo y en core/caja.py; acá sólo se muestran.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from . import caja as servicio
from .acceso import solo_personal
from .forms_caja import AbrirCajaForm, CerrarCajaForm, MovimientoCajaForm, PinForm
from .models import SesionCaja

PERMISOS_CAJA = ("core.view_caja", "core.abrir_caja", "core.movimientos_caja", "core.cerrar_caja")


def _ip(request) -> str | None:
    return request.META.get("REMOTE_ADDR")


def _exigir_acceso_caja(user) -> None:
    if not (user.is_superuser or any(user.has_perm(p) for p in PERMISOS_CAJA)):
        raise PermissionDenied("No tenés acceso a la caja.")


def _error(form, e: Exception) -> None:
    if isinstance(e, ValidationError) and hasattr(e, "error_dict"):
        for campo, errores in e.message_dict.items():
            form.add_error(campo if campo in form.fields else None, errores)
    else:
        form.add_error(None, "; ".join(e.messages) if isinstance(e, ValidationError) else str(e))


@solo_personal
def lista(request):
    _exigir_acceso_caja(request.user)
    filas = []
    for c in servicio.cajas_visibles(request.user).order_by("sucursal__nombre", "numero"):
        sesion = c.sesiones.filter(estado=SesionCaja.Estado.ABIERTA).select_related("abierta_por").first()
        filas.append({"caja": c, "sesion": sesion})
    return render(request, "panel/caja/lista.html", {"titulo": "Caja", "filas": filas})


@solo_personal
def detalle_caja(request, pk: int):
    _exigir_acceso_caja(request.user)
    c = get_object_or_404(servicio.cajas_visibles(request.user), pk=pk)
    sesiones = c.sesiones.select_related("abierta_por", "cerrada_por").order_by("-abierta_el")[:50]
    return render(request, "panel/caja/detalle_caja.html", {"titulo": f"Caja {c.numero}", "caja": c, "sesiones": sesiones})


@solo_personal
def abrir(request, pk: int):
    if not (request.user.is_superuser or request.user.has_perm("core.abrir_caja")):
        raise PermissionDenied
    c = get_object_or_404(servicio.cajas_visibles(request.user), pk=pk)
    form = AbrirCajaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            sesion = SesionCaja.abrir(
                caja=c, usuario=request.user, pin=form.cleaned_data["pin"], ip=_ip(request),
                saldo_inicial=form.cleaned_data["saldo_inicial"],
            )
        except (PermissionDenied, ValidationError) as e:
            _error(form, e)
        else:
            messages.success(request, f"Caja {c.numero} abierta.")
            return redirect("core:sesion", sesion.pk)
    return render(request, "panel/caja/abrir.html", {"titulo": "Abrir caja", "caja": c, "form": form})


def _resumen_ventas(sesion) -> dict:
    from ventas.models import Venta

    return Venta.objects.filter(sesion=sesion, estado=Venta.Estado.FINALIZADA).aggregate(
        total=Sum("total"), efectivo=Sum("monto_efectivo"), tarjeta=Sum("monto_tarjeta"),
        transferencia=Sum("monto_transferencia"), ctacte=Sum("monto_ctacte"),
    )


@solo_personal
def sesion(request, pk: int):
    _exigir_acceso_caja(request.user)
    s = get_object_or_404(servicio.sesiones_visibles(request.user), pk=pk)
    return render(request, "panel/caja/sesion.html", {
        "titulo": f"Sesión de caja #{s.pk}",
        "sesion": s,
        "movimientos": s.movimientos.select_related("creado_por").order_by("-creado_el"),
        "ventas": _resumen_ventas(s),
        "puede_cerrar": request.user.is_superuser or request.user.has_perm("core.cerrar_caja"),
        "puede_mover": request.user.is_superuser or request.user.has_perm("core.movimientos_caja"),
    })


@solo_personal
def cerrar(request, pk: int):
    if not (request.user.is_superuser or request.user.has_perm("core.cerrar_caja")):
        raise PermissionDenied
    s = get_object_or_404(servicio.sesiones_visibles(request.user), pk=pk)
    if s.estado != SesionCaja.Estado.ABIERTA:
        messages.info(request, "Esa sesión ya está cerrada.")
        return redirect("core:sesion", s.pk)
    form = CerrarCajaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            servicio.cerrar_sesion(
                s, request.user, pin=form.cleaned_data["pin"], total_contado=form.cleaned_data["total_contado"],
                observacion=form.cleaned_data["observacion"], ip=_ip(request),
            )
        except (PermissionDenied, ValidationError) as e:
            _error(form, e)
        else:
            s.refresh_from_db()
            nivel = messages.SUCCESS if s.diferencia == 0 else messages.WARNING
            messages.add_message(request, nivel, f"Caja cerrada. Diferencia: {s.diferencia}.")
            return redirect("core:sesion", s.pk)
    return render(request, "panel/caja/cerrar.html", {"titulo": "Cerrar caja", "sesion": s, "form": form})


@solo_personal
def movimiento(request, pk: int):
    if not (request.user.is_superuser or request.user.has_perm("core.movimientos_caja")):
        raise PermissionDenied
    c = get_object_or_404(servicio.cajas_visibles(request.user), pk=pk)
    abierta = c.sesiones.filter(estado=SesionCaja.Estado.ABIERTA).first()
    form = MovimientoCajaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            servicio.registrar_movimiento(c, request.user, **form.cleaned_data)
        except (PermissionDenied, ValidationError) as e:
            _error(form, e)
        else:
            messages.success(request, "Movimiento registrado.")
            return redirect("core:sesion", abierta.pk) if abierta else redirect("core:caja")
    return render(request, "panel/caja/movimiento.html", {
        "titulo": "Movimiento de caja", "caja": c, "sesion": abierta, "form": form,
    })


@solo_personal
def mi_pin(request):
    form = PinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            servicio.configurar_pin(
                request.user, actual=form.cleaned_data["pin_actual"],
                nuevo=form.cleaned_data["nuevo_pin"], repetido=form.cleaned_data["repetir_pin"],
            )
        except (PermissionDenied, ValidationError) as e:
            _error(form, e)
        else:
            messages.success(request, "PIN actualizado.")
            return redirect("panel:inicio")
    return render(request, "panel/caja/pin.html", {
        "titulo": "Mi PIN", "form": form, "tiene_pin": bool(request.user.action_pin_hash),
    })
