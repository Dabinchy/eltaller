"""
"Mi taller": lo que ve un cliente del taller en el portal (vehículos, órdenes, presupuestos,
comentarios, fotos compartidas y turnos). Nunca ve costos ni comentarios internos.
Las reglas de acceso están en portal/acceso_taller.py.
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Sucursal
from taller.models import OrdenTrabajo

from . import acceso_taller as mt
from .acceso import cliente_requerido
from .models_contenido import Archivo

FORMATO = "%Y-%m-%dT%H:%M"


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


class ComentarioClienteForm(forms.Form):
    texto = forms.CharField(label="Tu consulta o comentario", widget=forms.Textarea(attrs={"rows": 2}), max_length=2000)


class PedirTurnoForm(forms.Form):
    vehiculo = forms.ModelChoiceField(queryset=None, label="Vehículo")
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.filter(activa=True), label="Sucursal")
    inicio = forms.DateTimeField(label="Día y hora", input_formats=[FORMATO],
                                 widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format=FORMATO))
    motivo = forms.CharField(label="Motivo", max_length=255)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehiculo"].queryset = mt.vehiculos_del_cliente(user)
        self.fields["vehiculo"].label_from_instance = lambda v: f"{v.identificacion} · {v.marca} {v.modelo}"


@cliente_requerido
def mi_taller(request):
    user = request.user
    ordenes = mt.ordenes_del_cliente(user).select_related("vehiculo").order_by("-numero")
    return render(request, "portal/taller/inicio.html", {
        "titulo": "Mi taller",
        "vehiculos": mt.vehiculos_del_cliente(user),
        "en_curso": ordenes.exclude(estado__in=OrdenTrabajo.ESTADOS_FINALES),
        "historial": ordenes.filter(estado__in=OrdenTrabajo.ESTADOS_FINALES)[:30],
        "presupuestos": [o for o in ordenes.filter(estado=OrdenTrabajo.Estado.PRESUPUESTO) if mt.es_titular(user, o.cliente_id)],
    })


@cliente_requerido
def orden(request, pk):
    user = request.user
    o = get_object_or_404(mt.ordenes_del_cliente(user).select_related("vehiculo", "sucursal"), pk=pk)
    return render(request, "portal/taller/orden.html", {
        "titulo": f"Orden #{o.numero}", "orden": o,
        "items": o.items.select_related("producto"),
        "historial": o.historial.all(),
        "comentarios": mt.comentarios_visibles(o, user),
        "archivos": Archivo.objects.filter(orden=o, visibilidad=Archivo.Visibilidad.PILOTO),
        "puede_aprobar": o.estado == OrdenTrabajo.Estado.PRESUPUESTO and mt.es_titular(user, o.cliente_id),
        "form_comentario": ComentarioClienteForm(),
    })


@require_POST
@cliente_requerido
def orden_aprobar(request, pk):
    o = get_object_or_404(mt.ordenes_del_cliente(request.user), pk=pk)
    try:
        mt.aprobar_presupuesto(o, request.user)
        messages.success(request, "¡Presupuesto aprobado! El taller ya puede empezar el trabajo.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect("portal:taller_orden", o.pk)


@require_POST
@cliente_requerido
def orden_comentar(request, pk):
    o = get_object_or_404(mt.ordenes_del_cliente(request.user), pk=pk)
    form = ComentarioClienteForm(request.POST)
    if form.is_valid():
        try:
            mt.comentar_orden(o, request.user, form.cleaned_data["texto"])
            messages.success(request, "Comentario enviado al taller.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    return redirect(reverse("portal:taller_orden", args=[o.pk]) + "#comentarios")


@cliente_requerido
def turnos(request):
    user = request.user
    form = PedirTurnoForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            mt.solicitar_turno(user, vehiculo=d["vehiculo"], sucursal=d["sucursal"], inicio=d["inicio"], motivo=d["motivo"])
        except (ValidationError, PermissionDenied) as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Pedido de turno enviado. El taller te lo confirma.")
            return redirect("portal:turnos")
    ahora = timezone.now()
    todos = mt.turnos_del_cliente(user).order_by("-inicio")
    return render(request, "portal/taller/turnos.html", {
        "titulo": "Turnos", "form": form,
        "proximos": todos.filter(inicio__gte=ahora).order_by("inicio"), "pasados": todos.filter(inicio__lt=ahora)[:20],
    })
