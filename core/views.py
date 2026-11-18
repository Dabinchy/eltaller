"""
Vistas generales: redirección después de ingresar e inicio del panel interno.
(La portada es el sitio público: app sitio.)
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .acceso import solo_personal


@login_required
def redireccion(request):
    """Después de ingresar, cada uno va a su lugar según su tipo de usuario."""
    return redirect("portal:inicio" if request.user.es_portal else "panel:inicio")


@solo_personal
def panel_inicio(request):
    from portal.permisos import puede_gestionar_accesos
    from taller import permisos as permisos_taller
    from taller.models import OrdenTrabajo, Turno
    from ventas.models import Venta

    user = request.user
    es_gerente = permisos_taller.es_gerente(user)
    tarjetas = []

    if user.has_perm(permisos_taller.PERM_CAMBIAR_ESTADO) or user.has_perm(permisos_taller.PERM_TRABAJAR):
        E = OrdenTrabajo.Estado
        ordenes = permisos_taller.ordenes_visibles(
            OrdenTrabajo.objects.exclude(estado__in=OrdenTrabajo.ESTADOS_FINALES), user
        )
        tarjetas.append({
            "titulo": "Mis órdenes" if permisos_taller.es_solo_mecanico(user) else "Órdenes en curso",
            "icono": "bi-clipboard-check",
            "valor": ordenes.count(),
            "detalle": [
                ("Presupuesto", ordenes.filter(estado=E.PRESUPUESTO).count()),
                ("Aprobadas", ordenes.filter(estado=E.APROBADA).count()),
                ("En proceso", ordenes.filter(estado=E.EN_PROCESO).count()),
                ("Terminadas", ordenes.filter(estado=E.TERMINADA).count()),
            ],
        })

    def de_mi_sucursal(qs):
        if es_gerente:
            return qs
        return qs.filter(sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()

    if user.has_perm("taller.view_turno"):
        turnos = de_mi_sucursal(
            Turno.objects.filter(inicio__date=timezone.localdate(), estado__in=Turno.ESTADOS_ACTIVOS)
        )
        tarjetas.append({"titulo": "Turnos de hoy", "icono": "bi-calendar-week", "valor": turnos.count()})

    if user.has_perm("ventas.finalizar_venta"):
        abiertas = de_mi_sucursal(Venta.objects.filter(estado=Venta.Estado.ABIERTA))
        tarjetas.append({"titulo": "Ventas por cobrar", "icono": "bi-receipt", "valor": abiertas.count()})

    if puede_gestionar_accesos(user):
        from portal.models import AccesoCliente

        pendientes = AccesoCliente.objects.filter(estado=AccesoCliente.Estado.PENDIENTE).count()
        tarjetas.append({"titulo": "Accesos al portal pendientes", "icono": "bi-person-check", "valor": pendientes})

    if user.has_perm("sitio.view_consulta"):
        from django.urls import reverse

        from sitio.models import Consulta

        nuevas = Consulta.objects.filter(estado=Consulta.Estado.NUEVA).count()
        tarjetas.append({
            "titulo": "Consultas nuevas del sitio",
            "icono": "bi-chat-left-text",
            "valor": nuevas,
            # La lista está en el admin (sólo para quien puede entrar al admin).
            "url": reverse("admin:sitio_consulta_changelist") + "?estado__exact=nueva" if user.is_staff else "",
        })

    return render(request, "panel/inicio.html", {"titulo": "Inicio", "tarjetas": tarjetas})
