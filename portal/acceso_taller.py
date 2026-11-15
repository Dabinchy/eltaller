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


# ============================================================
# Vehículos y turnos del cliente
# ============================================================

def vehiculos_del_cliente(user):
    """Vehículos del taller que el usuario puede ver: los de su cliente (titular) o los que maneja."""
    from taller.models import Vehiculo

    from .models import AccesoCliente
    from .models_contenido import PilotoAuto

    if not getattr(user, "is_authenticated", False) or not getattr(user, "es_portal", False) or not user.is_active:
        return Vehiculo.objects.none()
    accesos = AccesoCliente.objects.filter(usuario=user, estado=AccesoCliente.Estado.APROBADO)
    titular = accesos.filter(rol=AccesoCliente.Rol.TITULAR).values("cliente_id")
    piloto = accesos.filter(rol=AccesoCliente.Rol.PILOTO).values("cliente_id")
    que_maneja = PilotoAuto.objects.filter(
        piloto__usuario=user, estado=PilotoAuto.Estado.ACEPTADA, auto__vehiculo_taller__isnull=False,
    ).values("auto__vehiculo_taller_id")
    return Vehiculo.objects.filter(
        Q(cliente_id__in=titular) | Q(cliente_id__in=piloto, pk__in=que_maneja), activo=True,
    )


def turnos_del_cliente(user):
    from taller.models import Turno

    return Turno.objects.filter(vehiculo__in=vehiculos_del_cliente(user)).select_related("vehiculo", "sucursal")


def es_titular(user, cliente_id) -> bool:
    from .models import AccesoCliente

    return AccesoCliente.objects.filter(
        usuario=user, cliente_id=cliente_id, rol=AccesoCliente.Rol.TITULAR, estado=AccesoCliente.Estado.APROBADO,
    ).exists()


# ============================================================
# Acciones del cliente
# ============================================================

def comentar_orden(orden, autor, texto: str, visible_piloto: bool = False):
    """
    - Personal con la orden en su alcance (incluido el mecánico asignado): interno salvo que lo marque visible.
    - Cliente con acceso a la orden: siempre visible.
    """
    from django.core.exceptions import PermissionDenied

    from taller import permisos as permisos_taller

    from .models_contenido import OrdenComentario

    if getattr(autor, "es_portal", False):
        if not ordenes_del_cliente(autor).filter(pk=orden.pk).exists():
            raise PermissionDenied("No tenés acceso a esta orden.")
        visible_piloto = True
    elif not permisos_taller.puede_operar(autor, orden):
        raise PermissionDenied("Esta orden no está dentro de tu alcance.")
    return OrdenComentario.objects.create(orden=orden, autor=autor, texto=texto, visible_piloto=visible_piloto)


def comentarios_visibles(orden, user):
    qs = orden.comentarios.select_related("autor")
    return qs.filter(visible_piloto=True) if getattr(user, "es_portal", False) else qs


def aprobar_presupuesto(orden, user):
    """Sólo el TITULAR del cliente de la orden puede aprobar su presupuesto desde el portal."""
    from django.core.exceptions import PermissionDenied

    if not getattr(user, "es_portal", False) or not es_titular(user, orden.cliente_id):
        raise PermissionDenied("Sólo el titular puede aprobar el presupuesto.")
    return orden.aprobar_presupuesto_por_cliente(user=user)


def solicitar_turno(user, *, vehiculo, sucursal, inicio, duracion_min: int = 60, motivo: str = ""):
    """El cliente pide un turno para uno de sus vehículos: queda PENDIENTE y respeta el cupo."""
    from django.core.exceptions import PermissionDenied

    from taller.models import Turno

    from django.core.exceptions import ValidationError
    from django.utils import timezone

    if not vehiculos_del_cliente(user).filter(pk=vehiculo.pk).exists():
        raise PermissionDenied("Ese vehículo no está entre los tuyos.")
    if not sucursal.activa:
        raise ValidationError("Esa sucursal no está tomando turnos.")
    if inicio <= timezone.now():
        raise ValidationError("Elegí una fecha y hora futura.")
    return Turno.objects.create(
        sucursal=sucursal, cliente=vehiculo.cliente, vehiculo=vehiculo, inicio=inicio,
        duracion_min=duracion_min, motivo=(motivo or "")[:255], estado=Turno.Estado.PENDIENTE, creado_por=user,
    )
