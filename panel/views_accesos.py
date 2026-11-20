"""
Accesos al portal: /panel/clientes/accesos/...

Una persona registrada en el portal pide ver "su taller" (sus vehículos y órdenes). La gerencia
identifica a qué cliente corresponde, elige el rol (titular o piloto del equipo) y aprueba;
también rechaza o revoca, siempre con motivo. Sólo la gerencia o un superusuario
(portal/permisos.py); las reglas y el historial están en portal/servicios.py.
"""
from __future__ import annotations

import re

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from clientes.models import Cliente
from core.acceso import solo_personal
from portal import servicios
from portal.models import AccesoCliente
from portal.permisos import puede_gestionar_accesos

E = AccesoCliente.Estado


class AprobarAccesoForm(forms.Form):
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.filter(activo=True), label="Cliente",
                                     error_messages={"required": "Elegí a qué cliente corresponde."})
    rol = forms.ChoiceField(choices=AccesoCliente.Rol.choices, label="Qué puede ver")


def _exigir(user) -> None:
    if not puede_gestionar_accesos(user):
        raise PermissionDenied


def _texto(e) -> str:
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _sugeridos(acceso: AccesoCliente):
    """Clientes que coinciden con el documento o el nombre que declaró la persona."""
    doc = re.sub(r"\D", "", acceso.doc_declarado or "")
    filtro = Q(pk__in=[])
    if doc:
        filtro |= Q(doc_numero__icontains=doc)
    palabras = [p for p in re.split(r"\s+", acceso.nombre_declarado or "") if len(p) >= 3]
    if palabras:
        por_nombre = Q()
        for p in palabras:
            por_nombre &= Q(nombre__icontains=p)
        filtro |= por_nombre
    return list(Cliente.objects.filter(activo=True).filter(filtro).order_by("nombre")[:8])


def _buscar(q: str):
    if len(q) < 2:
        return []
    return list(
        Cliente.objects.filter(activo=True)
        .filter(Q(nombre__icontains=q) | Q(doc_numero__icontains=q) | Q(telefono__icontains=q)
                | Q(email__icontains=q) | Q(vehiculos__patente__icontains=q))
        .distinct().order_by("nombre")[:15]
    )


@solo_personal
def lista(request):
    _exigir(request.user)
    estado = request.GET.get("estado") or E.PENDIENTE
    q = (request.GET.get("q") or "").strip()
    qs = AccesoCliente.objects.select_related("usuario", "cliente", "resuelto_por")
    if estado in E.values:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(usuario__username__icontains=q) | Q(usuario__email__icontains=q) | Q(usuario__dni__icontains=q)
                       | Q(nombre_declarado__icontains=q) | Q(doc_declarado__icontains=q) | Q(cliente__nombre__icontains=q))
    conteo = dict(AccesoCliente.objects.values_list("estado").annotate(n=Count("id")))
    pestanas = [(v, n, conteo.get(v, 0)) for v, n in [(E.PENDIENTE, "Pendientes"), (E.APROBADO, "Aprobados"),
                                                      (E.RECHAZADO, "Rechazados"), (E.REVOCADO, "Revocados")]]
    return render(request, "panel/clientes/accesos.html", {
        "titulo": "Accesos al portal", "pagina": Paginator(qs.order_by("-solicitado_el"), 25).get_page(request.GET.get("pagina")),
        "estado": estado, "q": q, "pestanas": pestanas,
    })


@solo_personal
def detalle(request, pk: int):
    user = request.user
    _exigir(user)
    acceso = get_object_or_404(AccesoCliente.objects.select_related("usuario", "cliente", "resuelto_por"), pk=pk)
    form = AprobarAccesoForm(initial={"cliente": acceso.cliente_id, "rol": acceso.rol})

    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "aprobar":
                form = AprobarAccesoForm(request.POST)
                if form.is_valid():
                    servicios.aprobar_acceso(acceso, user, cliente=form.cleaned_data["cliente"],
                                             rol=form.cleaned_data["rol"])
                    messages.success(request, f"Acceso aprobado: {acceso.usuario} ya ve el taller de {acceso.cliente}.")
                    return redirect("clientes:accesos")
            elif accion == "rechazar":
                servicios.rechazar_acceso(acceso, user, request.POST.get("motivo", ""))
                messages.success(request, "Solicitud rechazada.")
                return redirect("clientes:accesos")
            elif accion == "revocar":
                servicios.revocar_acceso(acceso, user, request.POST.get("motivo", ""))
                messages.success(request, f"Acceso revocado: {acceso.usuario} ya no ve el taller de {acceso.cliente}.")
                return redirect("clientes:acceso", acceso.pk)
            else:
                raise PermissionDenied
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))

    q = (request.GET.get("q") or "").strip()
    sugeridos = _sugeridos(acceso)
    encontrados = [c for c in _buscar(q) if c not in sugeridos]
    elegido = form["cliente"].value()
    if not elegido and len(sugeridos) == 1:
        elegido = sugeridos[0].pk   # un único cliente coincide: queda marcado
    candidatos = sugeridos + encontrados
    if acceso.cliente and acceso.cliente not in candidatos:
        candidatos.insert(0, acceso.cliente)
    ya_con_acceso = dict(
        AccesoCliente.objects.filter(cliente__in=candidatos, estado=E.APROBADO).exclude(pk=acceso.pk)
        .values_list("cliente").annotate(n=Count("id"))
    )
    return render(request, "panel/clientes/acceso.html", {
        "titulo": f"Acceso de {acceso.nombre_declarado or acceso.usuario}", "a": acceso, "form": form, "q": q,
        "candidatos": [(c, str(c.pk) == str(elegido), ya_con_acceso.get(c.pk, 0), c in sugeridos) for c in candidatos],
        "buscado_sin_resultados": bool(q) and not encontrados and len(q) >= 2,
        "otros_accesos": acceso.usuario.accesos_cliente.exclude(pk=acceso.pk).select_related("cliente"),
    })
