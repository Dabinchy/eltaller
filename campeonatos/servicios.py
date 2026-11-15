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


# ============================================================
# Resultados
# ============================================================

from collections import defaultdict  # noqa: E402

from django.utils import timezone  # noqa: E402

from .models import Resultado  # noqa: E402

ER = Resultado.Estado
CAMPOS_RESULTADO = ("posicion", "condicion", "pole", "vuelta_rapida")


def reevaluar_conflictos(carrera: Carrera, categoria: Categoria) -> None:
    """
    Dos pilotos con la misma posición, o más de una pole / vuelta rápida en la misma carrera y
    categoría: esos resultados quedan OBSERVADOS (no suman). Un resultado VALIDADO manda: el que
    choca con él queda observado. Cuando el conflicto desaparece, vuelven solos a PROVISORIO.
    """
    resultados = list(
        Resultado.objects.select_for_update()
        .filter(carrera=carrera, inscripcion__categoria=categoria)
        .exclude(estado=ER.ANULADO)
    )
    grupos: list[tuple[str, list]] = []
    por_posicion = defaultdict(list)
    for r in resultados:
        if r.clasificado:
            por_posicion[r.posicion].append(r)
    grupos += [(f"Otro piloto también cargó el puesto {p}.", g) for p, g in por_posicion.items() if len(g) > 1]
    poles = [r for r in resultados if r.pole]
    vueltas = [r for r in resultados if r.vuelta_rapida]
    if len(poles) > 1:
        grupos.append(("Más de un piloto cargó la pole.", poles))
    if len(vueltas) > 1:
        grupos.append(("Más de un piloto cargó la vuelta rápida.", vueltas))

    motivos: dict[int, str] = {}
    for motivo, grupo in grupos:
        for r in grupo:
            if r.estado != ER.VALIDADO:
                motivos.setdefault(r.pk, motivo)

    for r in resultados:
        if r.pk in motivos and r.estado == ER.PROVISORIO:
            r.estado, r.observado_por_conflicto, r.motivo = ER.OBSERVADO, True, motivos[r.pk]
            r.save(update_fields=["estado", "observado_por_conflicto", "motivo"])
        elif r.pk not in motivos and r.estado == ER.OBSERVADO and r.observado_por_conflicto:
            r.estado, r.observado_por_conflicto, r.motivo = ER.PROVISORIO, False, ""
            r.save(update_fields=["estado", "observado_por_conflicto", "motivo"])


def _inscripcion_para(perfil: PerfilPiloto, carrera: Carrera, inscripcion=None) -> Inscripcion:
    fecha = carrera.fecha
    candidatas = [
        i for i in Inscripcion.objects.filter(
            piloto=perfil, estado=Inscripcion.Estado.ACTIVA, categoria__campeonato=fecha.campeonato,
        ).select_related("categoria")
        if fecha.corre_categoria(i.categoria)
    ]
    if inscripcion is not None:
        if inscripcion not in candidatas:
            raise PermissionDenied("Esa inscripción no es tuya o su categoría no corre en esta fecha.")
        return inscripcion
    if not candidatas:
        raise ValidationError("No estás inscripto en ninguna categoría que corra esta fecha.")
    if len(candidatas) > 1:
        raise ValidationError("Corrés en más de una categoría en esta fecha: elegí en cuál cargar el resultado.")
    return candidatas[0]


@transaction.atomic
def cargar_resultado(perfil: PerfilPiloto, carrera: Carrera, *, inscripcion=None, **datos) -> Resultado:
    """El piloto carga (o corrige, dentro del plazo) SU resultado. Suma al instante como provisorio."""
    fecha = carrera.fecha
    if fecha.campeonato.estado != Campeonato.Estado.EN_CURSO:
        raise ValidationError("El campeonato no está en curso.")
    if not fecha.carga_abierta:
        raise ValidationError("La carga de resultados de esta fecha está cerrada.")
    insc = _inscripcion_para(perfil, carrera, inscripcion)

    resultado = Resultado.objects.select_for_update().filter(carrera=carrera, inscripcion=insc).first()
    if resultado and resultado.estado in (ER.VALIDADO, ER.ANULADO):
        raise ValidationError("Tu resultado ya fue revisado: para cambiarlo, pedíselo a un moderador.")
    if resultado is None:
        resultado = Resultado(carrera=carrera, inscripcion=insc, cargado_por=perfil.usuario)
    for campo in CAMPOS_RESULTADO:
        if campo in datos:
            setattr(resultado, campo, datos[campo])
    resultado.save()
    reevaluar_conflictos(carrera, insc.categoria)
    resultado.refresh_from_db()
    return resultado


def _verificar_moderador_resultado(resultado: Resultado, actor) -> None:
    verificar_moderador(actor, resultado.carrera.fecha.campeonato)
    if resultado.inscripcion.piloto.usuario_id == actor.pk:
        raise PermissionDenied("No podés moderar tu propio resultado: tiene que hacerlo otro moderador.")


def _registrar(actor, accion, resultado: Resultado, motivo: str = "") -> None:
    registrar(actor, accion, resultado, resultado.carrera.fecha.campeonato.asociacion, motivo)


@transaction.atomic
def validar_resultado(resultado: Resultado, actor) -> Resultado:
    """Validar un observado significa que el moderador decidió que este es el correcto."""
    _verificar_moderador_resultado(resultado, actor)
    if resultado.estado not in (ER.PROVISORIO, ER.OBSERVADO):
        raise ValidationError("Sólo se validan resultados provisorios u observados.")
    resultado.estado, resultado.observado_por_conflicto, resultado.motivo = ER.VALIDADO, False, ""
    resultado.validado_por, resultado.validado_el = actor, timezone.now()
    resultado.save(update_fields=["estado", "observado_por_conflicto", "motivo", "validado_por", "validado_el"])
    reevaluar_conflictos(resultado.carrera, resultado.inscripcion.categoria)
    _registrar(actor, A.VALIDAR, resultado)
    return resultado


@transaction.atomic
def validar_carrera(carrera: Carrera, categoria: Categoria, actor) -> int:
    """Valida todos los provisorios (sin conflicto) de una carrera y categoría, salvo el propio."""
    verificar_moderador(actor, carrera.fecha.campeonato)
    pendientes = Resultado.objects.filter(
        carrera=carrera, inscripcion__categoria=categoria, estado=ER.PROVISORIO,
    ).exclude(inscripcion__piloto__usuario=actor)
    n = 0
    for r in pendientes:
        validar_resultado(r, actor)
        n += 1
    return n


@transaction.atomic
def corregir_resultado(resultado: Resultado, actor, motivo: str, **datos) -> Resultado:
    """El moderador corrige (también fuera de plazo); el resultado corregido queda validado."""
    _verificar_moderador_resultado(resultado, actor)
    motivo = _exigir_motivo(motivo)
    for campo in CAMPOS_RESULTADO:
        if campo in datos:
            setattr(resultado, campo, datos[campo])
    resultado.estado, resultado.observado_por_conflicto, resultado.motivo = ER.VALIDADO, False, ""
    resultado.validado_por, resultado.validado_el = actor, timezone.now()
    resultado.save()
    reevaluar_conflictos(resultado.carrera, resultado.inscripcion.categoria)
    _registrar(actor, A.CORREGIR, resultado, motivo)
    return resultado


@transaction.atomic
def observar_resultado(resultado: Resultado, actor, motivo: str) -> Resultado:
    _verificar_moderador_resultado(resultado, actor)
    motivo = _exigir_motivo(motivo)
    resultado.estado, resultado.observado_por_conflicto, resultado.motivo = ER.OBSERVADO, False, motivo[:255]
    resultado.save(update_fields=["estado", "observado_por_conflicto", "motivo"])
    _registrar(actor, A.OBSERVAR, resultado, motivo)
    return resultado


@transaction.atomic
def anular_resultado(resultado: Resultado, actor, motivo: str) -> Resultado:
    _verificar_moderador_resultado(resultado, actor)
    motivo = _exigir_motivo(motivo)
    resultado.estado, resultado.observado_por_conflicto, resultado.motivo = ER.ANULADO, False, motivo[:255]
    resultado.save(update_fields=["estado", "observado_por_conflicto", "motivo"])
    reevaluar_conflictos(resultado.carrera, resultado.inscripcion.categoria)
    _registrar(actor, A.ANULAR, resultado, motivo)
    return resultado


@transaction.atomic
def validar_vencidos() -> int:
    """Al vencer el plazo de carga, los provisorios (sin conflicto) quedan validados solos."""
    n = 0
    ahora = timezone.now()
    for r in Resultado.objects.filter(estado=ER.PROVISORIO).select_related("carrera__fecha__campeonato"):
        if ahora > r.carrera.fecha.cierre_carga:
            r.estado, r.validado_el = ER.VALIDADO, ahora
            r.save(update_fields=["estado", "validado_el"])
            n += 1
    return n
