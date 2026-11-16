"""
Consultas del sitio público: sólo lo que puede verse en la web.

Las reglas de visibilidad viven en los modelos (visible_en_web). Acá se hace un primer filtro
en la base y después se confirma con esa propiedad, para no repetir las reglas a medias.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch, Q
from django.http import Http404
from django.utils import timezone

from campeonatos.models import Campeonato, Categoria, Fecha, Inscripcion, Resultado
from campeonatos.tabla import FilaTabla, tabla_posiciones
from portal.models import Asociacion, Membresia, PerfilPiloto
from portal.models_contenido import Archivo, Auto, PilotoAuto

ESTADOS_PUBLICOS = (Campeonato.Estado.EN_CURSO, Campeonato.Estado.FINALIZADO)


# ===========================
# Campeonatos
# ===========================

def campeonatos_visibles():
    return Campeonato.objects.filter(estado__in=ESTADOS_PUBLICOS, asociacion__activa=True).select_related("asociacion")


def campeonato_visible(slug: str) -> Campeonato:
    camp = campeonatos_visibles().filter(slug=slug).first()
    if not camp:
        raise Http404()
    return camp


def proximas_fechas(campeonatos=None, limite: int = 6):
    qs = Fecha.objects.filter(
        campeonato__in=campeonatos if campeonatos is not None else campeonatos_visibles(),
        estado=Fecha.Estado.PROGRAMADA,
        dia__gte=timezone.localdate(),
    ).select_related("campeonato")
    return qs.order_by("dia", "numero")[:limite]


@dataclass
class ResumenCategoria:
    categoria: Categoria
    filas: list[FilaTabla]
    provisoria: bool

    @property
    def podio(self) -> list[FilaTabla]:
        return [f for f in self.filas if f.puntos > 0][:3]


def resumen_categorias(campeonato: Campeonato) -> list[ResumenCategoria]:
    resumen = []
    for cat in campeonato.categorias.all():
        filas, provisoria = tabla_posiciones(cat)
        resumen.append(ResumenCategoria(cat, filas, provisoria))
    return resumen


@dataclass
class ResultadosCarrera:
    carrera: object
    resultados: list[Resultado]


@dataclass
class FechaConResultados:
    fecha: Fecha
    carreras: list[ResultadosCarrera]

    @property
    def tiene_resultados(self) -> bool:
        return any(c.resultados for c in self.carreras)


def fechas_de_categoria(campeonato: Campeonato, categoria: Categoria) -> list[FechaConResultados]:
    """Calendario de la categoría con los resultados que suman (provisorios y validados)."""
    resultados = Resultado.objects.filter(
        inscripcion__categoria=categoria, estado__in=Resultado.ESTADOS_QUE_SUMAN,
    ).select_related("inscripcion__piloto__usuario").order_by("posicion", "condicion", "inscripcion__numero")
    fechas = (
        campeonato.fechas.prefetch_related("categorias")
        .prefetch_related(Prefetch("carreras__resultados", queryset=resultados, to_attr="publicos"))
    )
    lista = []
    for fecha in fechas:
        if not fecha.corre_categoria(categoria):
            continue
        carreras = [ResultadosCarrera(c, c.publicos) for c in fecha.carreras.all()]
        lista.append(FechaConResultados(fecha, carreras))
    return lista


# ===========================
# Pilotos
# ===========================

def _pilotos_candidatos():
    """Primer filtro en la base; visible_en_web confirma (menores, asociaciones aprobadas)."""
    return (
        PerfilPiloto.objects.filter(
            perfil_publico=True, aprobado=True, usuario__is_active=True,
            usuario__membresias__rol=Membresia.Rol.PILOTO,
            usuario__membresias__estado=Membresia.Estado.APROBADA,
            usuario__membresias__asociacion__activa=True,
        )
        .select_related("usuario")
        .distinct()
    )


def pilotos_visibles(busqueda: str = "", asociacion: Asociacion | None = None) -> list[PerfilPiloto]:
    qs = _pilotos_candidatos()
    if busqueda:
        qs = qs.filter(nombre_publico__icontains=busqueda)
    if asociacion is not None:
        qs = qs.filter(
            usuario__membresias__asociacion=asociacion,
            usuario__membresias__rol=Membresia.Rol.PILOTO,
            usuario__membresias__estado=Membresia.Estado.APROBADA,
        )
    return [p for p in qs if p.visible_en_web]


def piloto_visible(slug: str) -> PerfilPiloto:
    perfil = PerfilPiloto.objects.select_related("usuario").filter(slug=slug).first()
    if not perfil or not perfil.visible_en_web:
        raise Http404()
    return perfil


@dataclass
class Participacion:
    inscripcion: Inscripcion
    fila: FilaTabla | None
    total: int


def participaciones(perfil: PerfilPiloto) -> list[Participacion]:
    """Campeonatos públicos donde corre (o corrió), con su puesto actual en la tabla."""
    inscripciones = (
        perfil.inscripciones.filter(categoria__campeonato__in=campeonatos_visibles())
        .select_related("categoria__campeonato__asociacion", "auto")
        .order_by("-categoria__campeonato__temporada", "categoria__campeonato__nombre")
    )
    lista = []
    for insc in inscripciones:
        filas, _ = tabla_posiciones(insc.categoria)
        fila = next((f for f in filas if f.inscripcion.pk == insc.pk), None)
        lista.append(Participacion(insc, fila, len(filas)))
    return lista


# ===========================
# Autos y archivos
# ===========================

def autos_visibles_de(perfil: PerfilPiloto) -> list[Auto]:
    autos = Auto.objects.filter(
        pilotos__piloto=perfil, pilotos__estado=PilotoAuto.Estado.ACEPTADA,
        activo=True, publicado=True, aprobado=True,
    ).select_related("portada").distinct()
    return [a for a in autos if a.visible_en_web]


def auto_visible(slug: str) -> Auto:
    auto = Auto.objects.select_related("portada").filter(slug=slug).first()
    if not auto or not auto.visible_en_web:
        raise Http404()
    return auto


def galeria(*, piloto: PerfilPiloto | None = None, auto: Auto | None = None) -> list[Archivo]:
    """Fotos y videos públicos y aprobados (setups, telemetría y documentos nunca se muestran)."""
    filtro = Q(auto=auto) if auto is not None else Q(piloto=piloto, auto__isnull=True)
    qs = Archivo.objects.filter(
        filtro, visibilidad=Archivo.Visibilidad.PUBLICO, aprobado=True,
        tipo__in=(Archivo.Tipo.FOTO, Archivo.Tipo.VIDEO),
    )
    return list(qs)


def pilotos_del_auto(auto: Auto) -> list[PilotoAuto]:
    """Pilotos aceptados del auto (el principal primero); sólo los de perfil público llevan link."""
    return list(
        PilotoAuto.objects.filter(auto=auto, estado=PilotoAuto.Estado.ACEPTADA)
        .select_related("piloto__usuario")
        .order_by("-principal", "piloto__nombre_publico")
    )


# ===========================
# Asociaciones
# ===========================

def asociaciones_visibles():
    return Asociacion.objects.filter(activa=True)


def asociacion_visible(slug: str) -> Asociacion:
    asoc = asociaciones_visibles().filter(slug=slug).first()
    if not asoc:
        raise Http404()
    return asoc
