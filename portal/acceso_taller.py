"""
"Mi taller": qué órdenes ve un usuario del portal con acceso de cliente.

- TITULAR: todas las órdenes de su cliente.
- PILOTO del equipo: sólo las de vehículos vinculados a autos donde es piloto aceptado.
- Nunca las de otro dueño: la orden tiene que ser de SU cliente (titular al ingreso).
"""
from __future__ import annotations

from django.db.models import Q

from taller.models import OrdenTrabajo


def ordenes_del_cliente(user):
    from .models import AccesoCliente
    from .models_contenido import PilotoAuto

    if not getattr(user, "is_authenticated", False) or not getattr(user, "es_portal", False) or not user.is_active:
        return OrdenTrabajo.objects.none()
    accesos = AccesoCliente.objects.filter(usuario=user, estado=AccesoCliente.Estado.APROBADO)
    titular = accesos.filter(rol=AccesoCliente.Rol.TITULAR).values("cliente_id")
    piloto = accesos.filter(rol=AccesoCliente.Rol.PILOTO).values("cliente_id")
    vehiculos_que_maneja = PilotoAuto.objects.filter(
        piloto__usuario=user, estado=PilotoAuto.Estado.ACEPTADA, auto__vehiculo_taller__isnull=False,
    ).values("auto__vehiculo_taller_id")
    return OrdenTrabajo.objects.filter(
        Q(cliente_id__in=titular) | Q(cliente_id__in=piloto, vehiculo_id__in=vehiculos_que_maneja)
    )
