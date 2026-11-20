"""
Quién modera qué en el portal.

- Moderador de una asociación: membresía rol MODERADOR y estado APROBADA en esa asociación.
- Gerente (o superusuario): modera todas las asociaciones y es el único que nombra moderadores.
- Nadie modera lo propio (su membresía, su perfil, sus resultados).
- Accesos de cliente (quién ve su taller desde el portal): sólo la gerencia o un superusuario.
  Los moderadores y los usuarios del portal nunca: no ven clientes ni datos del taller.
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
    """Gerencia (grupo gerente o core.administrar_core) o superusuario; nunca usuarios del portal."""
    return es_gerente(user) and getattr(user, "is_active", False)


def verificar_gestiona_accesos(user) -> None:
    if not puede_gestionar_accesos(user):
        raise PermissionDenied("Sólo la gerencia aprueba, rechaza o revoca los accesos de clientes.")


# ============================================================
# Quién ve cada archivo (lo usa la vista de descarga)
# ============================================================

def _es_personal(user) -> bool:
    return getattr(user, "is_authenticated", False) and not getattr(user, "es_portal", True) and user.is_active


def _es_piloto_del_destino(user, archivo) -> bool:
    """Piloto aceptado del auto del archivo, o el piloto dueño del perfil."""
    from .models_contenido import PilotoAuto

    if archivo.auto_id:
        return PilotoAuto.objects.filter(
            auto_id=archivo.auto_id, piloto__usuario=user, estado=PilotoAuto.Estado.ACEPTADA
        ).exists()
    return bool(archivo.piloto_id and archivo.piloto.usuario_id == user.pk)


def _modera_al_autor(user, archivo) -> bool:
    perfil = getattr(archivo.subido_por, "perfil_piloto", None) if archivo.subido_por_id else None
    if perfil is None:
        return False
    return asociaciones_moderadas(user).filter(pk__in=perfil.asociaciones_aprobadas()).exists()


def puede_ver_archivo(user, archivo) -> bool:
    from taller.permisos import ordenes_visibles

    V = type(archivo).Visibilidad
    if archivo.visibilidad == V.PUBLICO and archivo.aprobado:
        return True
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    if archivo.subido_por_id == user.pk:
        return True

    if archivo.orden_id:  # archivos de órdenes: INTERNO o PILOTO
        orden = archivo.orden
        if _es_personal(user):
            return ordenes_visibles(type(orden).objects.filter(pk=orden.pk), user).exists()
        if archivo.visibilidad == V.PILOTO:
            from .acceso_taller import ordenes_del_cliente

            return ordenes_del_cliente(user).filter(pk=orden.pk).exists()
        return False

    if archivo.visibilidad == V.PRIVADO:
        return _es_piloto_del_destino(user, archivo)
    if archivo.visibilidad == V.PILOTO:
        return _es_piloto_del_destino(user, archivo) or _es_personal(user)
    if archivo.visibilidad == V.PUBLICO:  # pendiente de aprobación
        return _es_piloto_del_destino(user, archivo) or _modera_al_autor(user, archivo)
    return False
