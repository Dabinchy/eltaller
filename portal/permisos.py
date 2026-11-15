"""
Quién modera qué en el portal.

- Moderador de una asociación: membresía rol MODERADOR y estado APROBADA en esa asociación.
- Gerente (o superusuario): modera todas las asociaciones y es el único que nombra moderadores.
- Nadie modera lo propio (su membresía, su perfil, sus resultados).
- Accesos de cliente: sólo el personal del taller con portal.gestionar_accesos_cliente.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied

from taller.permisos import es_gerente

PERM_ACCESOS_CLIENTE = "portal.gestionar_accesos_cliente"


def asociaciones_moderadas(user):
    from .models import Asociacion, Membresia

    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return Asociacion.objects.none()
    if es_gerente(user):
        return Asociacion.objects.all()
    return Asociacion.objects.filter(
        activa=True,
        membresias__usuario=user,
        membresias__rol=Membresia.Rol.MODERADOR,
        membresias__estado=Membresia.Estado.APROBADA,
    ).distinct()


def es_moderador(user, asociacion=None) -> bool:
    qs = asociaciones_moderadas(user)
    return qs.filter(pk=asociacion.pk).exists() if asociacion is not None else qs.exists()


def verificar_puede_moderar(user, asociaciones, sobre_usuario=None) -> None:
    """
    Lanza PermissionDenied si `user` no modera ninguna de `asociaciones`
    (una Asociacion, un queryset o una lista) o si se trata de algo suyo.
    """
    if sobre_usuario is not None and getattr(sobre_usuario, "pk", None) == user.pk:
        raise PermissionDenied("No podés moderar lo tuyo: tiene que hacerlo otro moderador.")
    ids = [asociaciones.pk] if hasattr(asociaciones, "pk") else [a.pk for a in asociaciones]
    if not ids or not asociaciones_moderadas(user).filter(pk__in=ids).exists():
        raise PermissionDenied("No sos moderador de esa asociación.")


def puede_gestionar_accesos(user) -> bool:
    return (
        getattr(user, "is_authenticated", False)
        and not getattr(user, "es_portal", False)
        and (user.is_superuser or user.has_perm(PERM_ACCESOS_CLIENTE))
    )


def verificar_gestiona_accesos(user) -> None:
    if not puede_gestionar_accesos(user):
        raise PermissionDenied("Sólo el personal del taller gestiona los accesos de clientes.")
