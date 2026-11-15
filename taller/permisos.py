"""
Quién ve y opera cada orden de trabajo.

- Superusuario y gerente: todas.
- Personal con taller.cambiar_estado_orden (jefe, administración): las de su sucursal fija.
- Mecánico (sólo taller.trabajar_orden): las órdenes asignadas a él (Tecnico.usuario).
- Pilotos y el resto: ninguna (el portal tiene su propio control por dueño del dato).
"""
from __future__ import annotations

from core.roles import GRUPO_GERENTE

PERM_CAMBIAR_ESTADO = "taller.cambiar_estado_orden"
PERM_TRABAJAR = "taller.trabajar_orden"
PERM_APROBAR_ITEMS = "taller.aprobar_items"
PERM_ENTREGAR = "taller.entregar_orden"
PERM_CANCELAR = "taller.cancelar_orden"


def es_gerente(user) -> bool:
    if not getattr(user, "is_authenticated", False) or getattr(user, "es_piloto", False):
        return False
    return bool(
        user.is_superuser
        or user.has_perm("core.administrar_core")
        or user.groups.filter(name=GRUPO_GERENTE).exists()
    )


def es_solo_mecanico(user) -> bool:
    """Trabaja órdenes pero no las gestiona: ve sólo las asignadas."""
    return user.has_perm(PERM_TRABAJAR) and not user.has_perm(PERM_CAMBIAR_ESTADO) and not es_gerente(user)


def ordenes_visibles(qs, user):
    """Filtra un queryset de OrdenTrabajo según quién mira."""
    if getattr(user, "es_piloto", False) or not getattr(user, "is_authenticated", False):
        return qs.none()
    if es_gerente(user):
        return qs
    if user.has_perm(PERM_CAMBIAR_ESTADO):
        return qs.filter(sucursal_id=user.sucursal_id) if user.sucursal_id else qs.none()
    if user.has_perm(PERM_TRABAJAR):
        return qs.filter(tecnico__usuario=user)
    return qs.none()


def puede_operar(user, orden) -> bool:
    """True si la orden está dentro del alcance del usuario."""
    return ordenes_visibles(type(orden).objects.filter(pk=orden.pk), user).exists()
