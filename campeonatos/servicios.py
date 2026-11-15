"""
Operaciones de campeonatos.

- Estructura (campeonato, tabla de puntos, categorías, fechas, carreras): moderadores de la
  asociación del campeonato (y el gerente).
- Inscripción: el propio piloto, si es miembro aprobado de esa asociación.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from portal import permisos
from portal.models import Membresia, PerfilPiloto, RegistroModeracion
from portal.models_contenido import PilotoAuto, piloto_habilitado
from portal.servicios import _exigir_motivo, registrar

from .models import Campeonato, Carrera, Categoria, Fecha, Inscripcion, PuntajePosicion, TipoCarrera

A = RegistroModeracion.Accion


def verificar_moderador(actor, campeonato_o_asociacion) -> None:
    asociacion = getattr(campeonato_o_asociacion, "asociacion", campeonato_o_asociacion)
    permisos.verificar_puede_moderar(actor, asociacion)


# ============================================================
# Estructura (moderadores)
# ============================================================

def crear_campeonato(asociacion, actor, **datos) -> Campeonato:
    verificar_moderador(actor, asociacion)
    return Campeonato.objects.create(asociacion=asociacion, creado_por=actor, **datos)


def cambiar_estado(campeonato: Campeonato, actor, estado: str) -> Campeonato:
    verificar_moderador(actor, campeonato)
    campeonato.estado = estado
    campeonato.save()
    return campeonato


@transaction.atomic
def definir_tabla_puntos(campeonato: Campeonato, actor, puntos: list, tipo: str = TipoCarrera.FINAL) -> None:
    """`puntos` en orden: [20, 17, 15, ...] → 1° = 20, 2° = 17, ... Reemplaza la tabla de ese tipo."""
    verificar_moderador(actor, campeonato)
    campeonato.tabla_puntos.filter(tipo_carrera=tipo).delete()
    PuntajePosicion.objects.bulk_create([
        PuntajePosicion(campeonato=campeonato, tipo_carrera=tipo, posicion=i, puntos=Decimal(str(p)))
        for i, p in enumerate(puntos, start=1)
    ])


def crear_categoria(campeonato: Campeonato, actor, nombre: str, orden: int = 0) -> Categoria:
    verificar_moderador(actor, campeonato)
    return Categoria.objects.create(campeonato=campeonato, nombre=nombre, orden=orden)


def crear_fecha(campeonato: Campeonato, actor, *, categorias=None, **datos) -> Fecha:
    """Crea la fecha (con su Final automática). `categorias` vacío = corren todas."""
    verificar_moderador(actor, campeonato)
    with transaction.atomic():
        fecha = Fecha.objects.create(campeonato=campeonato, **datos)
        if categorias:
            if any(c.campeonato_id != campeonato.pk for c in categorias):
                raise ValidationError("Las categorías tienen que ser de este campeonato.")
            fecha.categorias.set(categorias)
    return fecha


def agregar_carrera(fecha: Fecha, actor, nombre: str, tipo: str = TipoCarrera.SERIE, orden: int = 0,
                    otorga_bonus: bool = False) -> Carrera:
    verificar_moderador(actor, fecha.campeonato)
    return Carrera.objects.create(fecha=fecha, nombre=nombre, tipo=tipo, orden=orden, otorga_bonus=otorga_bonus)


# ============================================================
# Inscripción (pilotos)
# ============================================================

def _miembro_aprobado(perfil: PerfilPiloto, asociacion) -> bool:
    return perfil.usuario.membresias.filter(
        asociacion=asociacion, rol=Membresia.Rol.PILOTO, estado=Membresia.Estado.APROBADA,
    ).exists()


@transaction.atomic
def inscribirse(perfil: PerfilPiloto, categoria: Categoria, numero: str, auto=None) -> Inscripcion:
    campeonato = categoria.campeonato
    if not piloto_habilitado(perfil) or not _miembro_aprobado(perfil, campeonato.asociacion):
        raise PermissionDenied("Tenés que ser piloto aprobado de esta asociación para inscribirte.")
    if campeonato.estado != Campeonato.Estado.EN_CURSO:
        raise ValidationError("Las inscripciones están cerradas para este campeonato.")
    if auto is not None and not PilotoAuto.objects.filter(
        auto=auto, piloto=perfil, estado=PilotoAuto.Estado.ACEPTADA
    ).exists():
        raise PermissionDenied("Sólo podés inscribirte con un auto en el que seas piloto.")
    existente = Inscripcion.objects.filter(categoria=categoria, piloto=perfil).first()
    if existente:
        if existente.estado == Inscripcion.Estado.ACTIVA:
            raise ValidationError("Ya estás inscripto en esa categoría.")
        # Se reinscribe después de una baja.
        existente.numero, existente.auto = numero, auto
        existente.estado, existente.motivo_baja = Inscripcion.Estado.ACTIVA, ""
        existente.full_clean()
        existente.save(update_fields=["numero", "auto", "estado", "motivo_baja"])
        return existente
    return Inscripcion.objects.create(categoria=categoria, piloto=perfil, numero=numero, auto=auto)


@transaction.atomic
def dar_de_baja(inscripcion: Inscripcion, actor, motivo: str = "") -> Inscripcion:
    """La baja la puede pedir el propio piloto o hacerla un moderador (con motivo)."""
    propio = inscripcion.piloto.usuario_id == actor.pk
    if not propio:
        verificar_moderador(actor, inscripcion.campeonato)
        motivo = _exigir_motivo(motivo)
    if inscripcion.estado == Inscripcion.Estado.BAJA:
        raise ValidationError("La inscripción ya está dada de baja.")
    inscripcion.estado = Inscripcion.Estado.BAJA
    inscripcion.motivo_baja = (motivo or "Baja pedida por el piloto")[:255]
    inscripcion.save(update_fields=["estado", "motivo_baja"])
    if not propio:
        registrar(actor, A.BAJA, inscripcion, inscripcion.campeonato.asociacion, motivo)
    return inscripcion
