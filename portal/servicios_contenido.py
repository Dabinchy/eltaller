"""
Operaciones sobre el contenido del portal (autos y pilotos por auto).

- Sólo pilotos habilitados (cuenta activa + membresía aprobada) crean o editan contenido.
- Al auto lo gestiona su piloto principal; los acompañantes entran por invitación aceptada.
- Lo aprueba un moderador de alguna asociación del piloto principal (nunca un piloto del auto).
- El vínculo con la ficha del taller lo hace sólo el personal.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from . import permisos
from .models import PerfilPiloto, RegistroModeracion
from .models_contenido import Auto, PilotoAuto, piloto_habilitado
from .servicios import _exigir_motivo, registrar

A = RegistroModeracion.Accion
EP = PilotoAuto.Estado


def verificar_habilitado(perfil: PerfilPiloto) -> None:
    if not piloto_habilitado(perfil):
        raise PermissionDenied("Tu cuenta todavía no fue aprobada por tu asociación.")


def _es_principal(auto: Auto, perfil: PerfilPiloto) -> bool:
    return auto.pilotos.filter(piloto=perfil, principal=True).exists()


def verificar_principal(auto: Auto, perfil: PerfilPiloto) -> None:
    verificar_habilitado(perfil)
    if not _es_principal(auto, perfil):
        raise PermissionDenied("Sólo el piloto principal puede hacer esto.")


# ============================================================
# Autos y pilotos
# ============================================================

@transaction.atomic
def crear_auto(perfil: PerfilPiloto, **datos) -> Auto:
    verificar_habilitado(perfil)
    campos = {k: v for k, v in datos.items() if k in Auto.CAMPOS_PUBLICOS}
    auto = Auto.objects.create(creado_por=perfil.usuario, **campos)
    PilotoAuto.objects.create(
        auto=auto, piloto=perfil, principal=True, estado=EP.ACEPTADA, respondida_el=timezone.now(),
    )
    return auto


def publicar_auto(auto: Auto, perfil: PerfilPiloto, publicado: bool) -> Auto:
    verificar_principal(auto, perfil)
    auto.publicado = publicado
    auto.save(update_fields=["publicado", "updated_at"])
    return auto


@transaction.atomic
def invitar_piloto(auto: Auto, perfil: PerfilPiloto, invitado: PerfilPiloto) -> PilotoAuto:
    verificar_principal(auto, perfil)
    if invitado.pk == perfil.pk:
        raise ValidationError("Ya sos piloto de este auto.")
    if not piloto_habilitado(invitado):
        raise ValidationError("Ese piloto todavía no tiene la cuenta aprobada.")
    existente = PilotoAuto.objects.filter(auto=auto, piloto=invitado).first()
    if existente and existente.estado != EP.RECHAZADA:
        raise ValidationError("Ese piloto ya está en el auto o tiene una invitación pendiente.")
    if existente:  # había rechazado: se lo vuelve a invitar
        existente.estado, existente.invitado_por, existente.respondida_el = EP.PENDIENTE, perfil.usuario, None
        existente.save(update_fields=["estado", "invitado_por", "respondida_el"])
        return existente
    return PilotoAuto.objects.create(auto=auto, piloto=invitado, invitado_por=perfil.usuario)


def responder_invitacion(invitacion: PilotoAuto, perfil: PerfilPiloto, aceptar: bool) -> PilotoAuto:
    if invitacion.piloto_id != perfil.pk:
        raise PermissionDenied("Esa invitación no es para vos.")
    if invitacion.estado != EP.PENDIENTE:
        raise ValidationError("La invitación ya fue respondida.")
    if aceptar:
        verificar_habilitado(perfil)
    invitacion.estado = EP.ACEPTADA if aceptar else EP.RECHAZADA
    invitacion.respondida_el = timezone.now()
    invitacion.save(update_fields=["estado", "respondida_el"])
    return invitacion


def quitar_piloto(auto: Auto, perfil: PerfilPiloto, quitado: PerfilPiloto) -> None:
    """El principal quita a un acompañante; cualquiera puede salir (el principal, transfiriendo antes)."""
    pa = PilotoAuto.objects.filter(auto=auto, piloto=quitado).first()
    if not pa:
        raise ValidationError("Ese piloto no está en el auto.")
    if pa.principal:
        raise ValidationError("El piloto principal no puede salir: primero transferí el auto a otro piloto.")
    if quitado.pk != perfil.pk and not _es_principal(auto, perfil):
        raise PermissionDenied("Sólo el piloto principal puede quitar a otros pilotos.")
    pa.delete()


@transaction.atomic
def transferir_principal(auto: Auto, perfil: PerfilPiloto, nuevo: PerfilPiloto) -> None:
    verificar_principal(auto, perfil)
    destino = PilotoAuto.objects.filter(auto=auto, piloto=nuevo, estado=EP.ACEPTADA).first()
    if not destino:
        raise ValidationError("El nuevo principal tiene que ser un piloto que ya aceptó estar en el auto.")
    PilotoAuto.objects.filter(auto=auto, principal=True).update(principal=False)
    destino.principal = True
    destino.save(update_fields=["principal"])


# ============================================================
# Moderación de autos
# ============================================================

def _verificar_puede_moderar_auto(auto: Auto, actor):
    """Devuelve la asociación (para el historial) o lanza PermissionDenied."""
    principal = auto.principal
    if principal is None:
        raise ValidationError("El auto no tiene piloto principal.")
    if auto.pilotos.filter(piloto__usuario=actor).exists():
        raise PermissionDenied("No podés moderar un auto en el que sos piloto.")
    asociaciones = list(principal.asociaciones_aprobadas())
    if not asociaciones:
        raise ValidationError("El piloto principal no tiene una membresía aprobada.")
    permisos.verificar_puede_moderar(actor, asociaciones)
    moderadas = set(permisos.asociaciones_moderadas(actor).values_list("pk", flat=True))
    return next(a for a in asociaciones if a.pk in moderadas)


@transaction.atomic
def aprobar_auto(auto: Auto, actor) -> Auto:
    asociacion = _verificar_puede_moderar_auto(auto, actor)
    auto.aprobado, auto.aprobado_por, auto.aprobado_el = True, actor, timezone.now()
    auto.cambio_tras_aprobacion = False
    auto.save(update_fields=["aprobado", "aprobado_por", "aprobado_el", "cambio_tras_aprobacion"])
    registrar(actor, A.APROBAR, auto, asociacion)
    return auto


@transaction.atomic
def retirar_aprobacion_auto(auto: Auto, actor, motivo: str) -> Auto:
    asociacion = _verificar_puede_moderar_auto(auto, actor)
    motivo = _exigir_motivo(motivo)
    auto.aprobado = auto.cambio_tras_aprobacion = False
    auto.save(update_fields=["aprobado", "cambio_tras_aprobacion"])
    registrar(actor, A.RETIRAR, auto, asociacion, motivo)
    return auto


@transaction.atomic
def marcar_auto_revisado(auto: Auto, actor) -> Auto:
    asociacion = _verificar_puede_moderar_auto(auto, actor)
    auto.cambio_tras_aprobacion = False
    auto.save(update_fields=["cambio_tras_aprobacion"])
    registrar(actor, A.REVISADO, auto, asociacion)
    return auto


# ============================================================
# Vínculo con la ficha del taller (sólo personal)
# ============================================================

def _verificar_personal_taller(actor) -> None:
    if getattr(actor, "es_portal", True) or not (actor.is_superuser or actor.has_perm("taller.change_vehiculo")):
        raise PermissionDenied("Sólo el personal del taller vincula autos con vehículos.")


@transaction.atomic
def vincular_vehiculo(auto: Auto, vehiculo, actor) -> Auto:
    _verificar_personal_taller(actor)
    otro = Auto.objects.filter(vehiculo_taller=vehiculo).exclude(pk=auto.pk).first()
    if otro:
        raise ValidationError(f"Ese vehículo ya está vinculado al auto «{otro}».")
    auto.vehiculo_taller = vehiculo
    auto.save(update_fields=["vehiculo_taller", "updated_at"])
    registrar(actor, A.VINCULAR, auto, motivo=f"Vehículo {vehiculo}")
    return auto


@transaction.atomic
def desvincular_vehiculo(auto: Auto, actor) -> Auto:
    _verificar_personal_taller(actor)
    if not auto.vehiculo_taller_id:
        raise ValidationError("El auto no está vinculado a ningún vehículo.")
    anterior = str(auto.vehiculo_taller)
    auto.vehiculo_taller = None
    auto.save(update_fields=["vehiculo_taller", "updated_at"])
    registrar(actor, A.DESVINCULAR, auto, motivo=f"Vehículo {anterior}")
    return auto
