"""
Pantallas del taller en el panel: órdenes, turnos y vehículos.

Toda regla de negocio vive en los modelos/servicios (taller, portal); acá se arma la pantalla
y se traducen los errores a mensajes. Cada vista filtra por el alcance del usuario:
sucursal (personal) u órdenes asignadas (mecánico).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.acceso import solo_personal
from core.models import SesionCaja
from portal import acceso_taller, servicios_contenido
from portal.models_contenido import Archivo
from taller import permisos
from taller.models import OrdenItem, OrdenTrabajo, Turno, Vehiculo

from .forms_taller import (
    ArchivoOrdenForm,
    ComentarioForm,
    ItemForm,
    OrdenDiagnosticoForm,
    OrdenEditarForm,
    OrdenNuevaForm,
    TurnoForm,
    VehiculoForm,
)

E = OrdenTrabajo.Estado
ETIQUETAS_PASO = {
    E.APROBADA: ("Aprobar presupuesto", "btn-success", "bi-check2-circle"),
    E.EN_PROCESO: ("Empezar trabajo", "btn-primary", "bi-play-circle"),
    E.TERMINADA: ("Terminar trabajo", "btn-primary", "bi-flag"),
    E.CANCELADA: ("Cancelar orden", "btn-outline-danger", "bi-x-circle"),
}


def _texto(e: Exception) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _exigir(user, *perms):
    if not (user.is_superuser or any(user.has_perm(p) for p in perms)):
        raise PermissionDenied


def _de_mi_sucursal(qs, user, campo="sucursal_id"):
    if permisos.es_gerente(user):
        return qs
    return qs.filter(**{campo: user.sucursal_id}) if user.sucursal_id else qs.none()


def _orden(user, pk):
    return get_object_or_404(permisos.ordenes_visibles(OrdenTrabajo.objects.all(), user), pk=pk)


# ============================================================
# Órdenes
# ============================================================

@solo_personal
def ordenes(request, solo_mias=False):
    user = request.user
    _exigir(user, permisos.PERM_CAMBIAR_ESTADO, permisos.PERM_TRABAJAR)
    qs = permisos.ordenes_visibles(OrdenTrabajo.objects.all(), user).select_related(
        "vehiculo", "cliente", "tecnico", "sucursal"
    )
    estado = request.GET.get("estado", "curso")
    if estado == "curso":
        qs = qs.exclude(estado__in=OrdenTrabajo.ESTADOS_FINALES)
    elif estado in E.values:
        qs = qs.filter(estado=estado)
    q = (request.GET.get("q") or "").strip()
    if q:
        filtro = Q(vehiculo__patente__icontains=q) | Q(vehiculo__vin__icontains=q) | Q(cliente__nombre__icontains=q)
        if q.isdigit():
            filtro |= Q(numero=int(q))
        qs = qs.filter(filtro)
    return render(request, "panel/taller/ordenes.html", {
        "titulo": "Mis órdenes" if solo_mias else "Órdenes de trabajo",
        "ordenes": qs.order_by("-numero")[:200],
        "estado": estado, "q": q, "estados": E.choices,
        "puede_crear": user.is_superuser or user.has_perm("taller.add_ordentrabajo"),
    })


@solo_personal
def orden_nueva(request):
    user = request.user
    _exigir(user, "taller.add_ordentrabajo")
    turno = None
    if request.GET.get("turno"):
        turno = get_object_or_404(_de_mi_sucursal(Turno.objects.all(), user), pk=request.GET["turno"])
    inicial = {}
    if turno:
        inicial = {"sucursal": turno.sucursal_id, "vehiculo": turno.vehiculo_id, "motivo_cliente": turno.motivo}
    elif request.GET.get("vehiculo"):
        inicial = {"vehiculo": request.GET["vehiculo"]}
    form = OrdenNuevaForm(request.POST or None, initial=inicial, user=user, es_gerente=permisos.es_gerente(user))
    if request.method == "POST" and form.is_valid():
        orden = form.save(commit=False)
        orden.creada_por = user
        orden.turno = turno
        try:
            orden.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, f"Orden #{orden.numero} creada. Cargá el presupuesto.")
            return redirect("taller:orden", orden.pk)
    return render(request, "panel/taller/orden_nueva.html", {"titulo": "Nueva orden", "form": form, "turno": turno})


@solo_personal
def orden(request, pk):
    user = request.user
    o = _orden(user, pk)
    mecanico = permisos.es_solo_mecanico(user)
    editable = o.estado in OrdenTrabajo.ESTADOS_EDITABLES
    puede_editar = editable and (user.is_superuser or user.has_perm("taller.change_ordentrabajo"))
    puede_items = editable and (user.is_superuser or user.has_perm("taller.add_ordenitem"))
    ver_costos = user.is_superuser or user.has_perm("productos.ver_costos")

    sesiones = []
    if o.estado == E.TERMINADA and (user.is_superuser or user.has_perm(permisos.PERM_ENTREGAR)):
        sesiones = list(SesionCaja.objects.filter(caja__sucursal=o.sucursal_id, estado=SesionCaja.Estado.ABIERTA)
                        .select_related("caja"))

    form_orden = None
    if puede_editar:
        form_orden = OrdenDiagnosticoForm(instance=o) if mecanico else OrdenEditarForm(instance=o)

    return render(request, "panel/taller/orden.html", {
        "titulo": f"OT #{o.numero}",
        "orden": o,
        "items": o.items.select_related("producto", "tecnico"),
        "historial": o.historial.select_related("usuario"),
        "comentarios": acceso_taller.comentarios_visibles(o, user),
        "archivos": Archivo.objects.filter(orden=o),
        "pasos": [(n, *ETIQUETAS_PASO[n]) for n in o.transiciones_para(user)],
        "form_orden": form_orden,
        "form_item": ItemForm(puede_precio=not mecanico) if puede_items else None,
        "puede_borrar_items": editable and (user.is_superuser or user.has_perm("taller.delete_ordenitem")),
        "puede_aprobar": editable and (user.is_superuser or user.has_perm(permisos.PERM_APROBAR_ITEMS))
                         and o.items.filter(aprobado=False).exists() and o.estado != E.PRESUPUESTO,
        "sesiones": sesiones,
        "ver_costos": ver_costos,
        "form_comentario": ComentarioForm(),
        "form_archivo": ArchivoOrdenForm(),
        "mecanico": mecanico,
    })


@require_POST
@solo_personal
def orden_editar(request, pk):
    user = request.user
    o = _orden(user, pk)
    _exigir(user, "taller.change_ordentrabajo")
    Form = OrdenDiagnosticoForm if permisos.es_solo_mecanico(user) else OrdenEditarForm
    form = Form(request.POST, instance=o)
    if form.is_valid():
        try:
            form.save()
            messages.success(request, "Orden actualizada.")
        except ValidationError as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Revisá los datos: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def item_agregar(request, pk):
    user = request.user
    o = _orden(user, pk)
    _exigir(user, "taller.add_ordenitem")
    form = ItemForm(request.POST, puede_precio=not permisos.es_solo_mecanico(user))
    if form.is_valid():
        item = form.save(commit=False)
        item.orden = o
        if not item.tecnico_id and hasattr(user, "tecnico"):
            item.tecnico = user.tecnico
        try:
            item.save()
        except ValidationError as e:
            messages.error(request, _texto(e))
        else:
            if item.falta_stock:
                messages.warning(request, f"No hay stock suficiente de {item.producto} ({item.stock_disponible} disp.). "
                                          "Se cargó igual: hay que reponer antes de entregar.")
            else:
                messages.success(request, f"Agregado: {item.descripcion}.")
    else:
        messages.error(request, "Revisá el ítem: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def item_borrar(request, pk, item_pk):
    user = request.user
    o = _orden(user, pk)
    _exigir(user, "taller.delete_ordenitem")
    item = get_object_or_404(OrdenItem, pk=item_pk, orden=o)
    try:
        item.delete()
        messages.success(request, "Ítem quitado.")
    except ValidationError as e:
        messages.error(request, _texto(e))
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def orden_estado(request, pk):
    o = _orden(request.user, pk)
    try:
        o.cambiar_estado(request.POST.get("estado", ""), user=request.user)
        messages.success(request, f"La orden pasó a {o.get_estado_display()}.")
    except (ValidationError, PermissionDenied, ValueError) as e:
        messages.error(request, _texto(e))
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def orden_aprobar_items(request, pk):
    o = _orden(request.user, pk)
    try:
        n = o.aprobar_items(user=request.user)
        messages.success(request, f"{n} ítem(s) aprobado(s).")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def orden_entregar(request, pk):
    o = _orden(request.user, pk)
    sesion = get_object_or_404(SesionCaja, pk=request.POST.get("sesion"), estado=SesionCaja.Estado.ABIERTA)
    try:
        venta = o.entregar(user=request.user, sesion=sesion)
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
        return redirect("taller:orden", o.pk)
    messages.success(request, f"Orden entregada. Venta #{venta.pk} lista para cobrar en caja.")
    return redirect("taller:orden", o.pk)


@require_POST
@solo_personal
def orden_comentar(request, pk):
    o = _orden(request.user, pk)
    form = ComentarioForm(request.POST)
    if form.is_valid():
        try:
            acceso_taller.comentar_orden(o, request.user, form.cleaned_data["texto"], form.cleaned_data["visible_piloto"])
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    return redirect(reverse("taller:orden", args=[o.pk]) + "#comentarios")


@require_POST
@solo_personal
def orden_subir_archivo(request, pk):
    o = _orden(request.user, pk)
    form = ArchivoOrdenForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            servicios_contenido.subir_archivo_orden(o, request.user, **form.cleaned_data)
            messages.success(request, "Archivo subido.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Elegí un archivo y un título.")
    return redirect("taller:orden", o.pk)


# ============================================================
# Turnos
# ============================================================

@solo_personal
def turnos(request):
    user = request.user
    _exigir(user, "taller.view_turno")
    dia = parse_date(request.GET.get("dia") or "") or timezone.localdate()
    qs = _de_mi_sucursal(Turno.objects.all(), user).filter(inicio__date=dia).select_related(
        "vehiculo", "cliente", "sucursal"
    ).order_by("inicio")
    return render(request, "panel/taller/turnos.html", {
        "titulo": "Turnos", "turnos": qs, "dia": dia,
        "anterior": dia - timedelta(days=1), "siguiente": dia + timedelta(days=1), "hoy": timezone.localdate(),
        "puede_crear": user.is_superuser or user.has_perm("taller.add_turno"),
        "puede_cambiar": user.is_superuser or user.has_perm("taller.change_turno"),
        "puede_orden": user.is_superuser or user.has_perm("taller.add_ordentrabajo"),
    })


@solo_personal
def turno_form(request, pk=None):
    user = request.user
    _exigir(user, "taller.change_turno" if pk else "taller.add_turno")
    turno = get_object_or_404(_de_mi_sucursal(Turno.objects.all(), user), pk=pk) if pk else None
    form = TurnoForm(request.POST or None, instance=turno, user=user, es_gerente=permisos.es_gerente(user))
    if request.method == "POST" and form.is_valid():
        t = form.save(commit=False)
        if not pk:
            t.creado_por = user
        try:
            t.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Turno guardado.")
            return redirect(f"/panel/taller/turnos/?dia={timezone.localtime(t.inicio).date().isoformat()}")
    return render(request, "panel/taller/turno_form.html", {
        "titulo": "Editar turno" if pk else "Nuevo turno", "form": form, "turno": turno,
    })


@require_POST
@solo_personal
def turno_estado(request, pk):
    user = request.user
    _exigir(user, "taller.change_turno")
    t = get_object_or_404(_de_mi_sucursal(Turno.objects.all(), user), pk=pk)
    nuevo = request.POST.get("estado")
    permitidos = {Turno.Estado.CONFIRMADO, Turno.Estado.CANCELADO, Turno.Estado.AUSENTE}
    if nuevo not in permitidos or t.estado not in (Turno.Estado.PENDIENTE, Turno.Estado.CONFIRMADO):
        messages.error(request, "Ese cambio no está permitido para este turno.")
    else:
        t.estado = nuevo
        try:
            t.save()
            messages.success(request, f"Turno {t.get_estado_display().lower()}.")
        except ValidationError as e:
            messages.error(request, _texto(e))
    return redirect(f"/panel/taller/turnos/?dia={timezone.localtime(t.inicio).date().isoformat()}")


# ============================================================
# Vehículos
# ============================================================

@solo_personal
def vehiculos(request):
    _exigir(request.user, "taller.view_vehiculo")
    q = (request.GET.get("q") or "").strip()
    qs = Vehiculo.objects.select_related("cliente")
    if q:
        qs = qs.filter(Q(patente__icontains=q) | Q(vin__icontains=q) | Q(marca__icontains=q)
                       | Q(modelo__icontains=q) | Q(cliente__nombre__icontains=q))
    return render(request, "panel/taller/vehiculos.html", {
        "titulo": "Vehículos", "vehiculos": qs.order_by("patente", "vin")[:200], "q": q,
        "puede_crear": request.user.is_superuser or request.user.has_perm("taller.add_vehiculo"),
    })


@solo_personal
def vehiculo(request, pk):
    user = request.user
    _exigir(user, "taller.view_vehiculo")
    v = get_object_or_404(Vehiculo.objects.select_related("cliente"), pk=pk)
    return render(request, "panel/taller/vehiculo.html", {
        "titulo": v.identificacion, "vehiculo": v,
        "ordenes": permisos.ordenes_visibles(v.ordenes.all(), user).order_by("-numero")[:50],
        "turnos": _de_mi_sucursal(v.turnos.all(), user).order_by("-inicio")[:20],
        "puede_editar": user.is_superuser or user.has_perm("taller.change_vehiculo"),
        "puede_orden": user.is_superuser or user.has_perm("taller.add_ordentrabajo"),
    })


@solo_personal
def vehiculo_form(request, pk=None):
    user = request.user
    _exigir(user, "taller.change_vehiculo" if pk else "taller.add_vehiculo")
    v = get_object_or_404(Vehiculo, pk=pk) if pk else None
    form = VehiculoForm(request.POST or None, instance=v)
    if request.method == "POST" and form.is_valid():
        try:
            v = form.save()
        except ValidationError as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Vehículo guardado.")
            return redirect("taller:vehiculo", v.pk)
    return render(request, "panel/taller/vehiculo_form.html", {
        "titulo": "Editar vehículo" if pk else "Nuevo vehículo", "form": form, "vehiculo": v,
    })
