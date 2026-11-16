"""
Vistas del sitio público.

- Portadas de El Taller y El Prepa: provisorias hasta que se cargue el contenido.
- Campeonatos: campeonatos, tablas, resultados, pilotos, autos y asociaciones (sólo lo visible).
"""
from __future__ import annotations

from django.shortcuts import render

from campeonatos.models import Campeonato
from campeonatos.tabla import tabla_posiciones

from . import consultas as q

PORTADAS = {
    "taller": ("sitio/taller/inicio.html", "Mecánica de confianza"),
    "prepa": ("sitio/prepa/inicio.html", "Competición, personalización y clásicos"),
}


def portada(request, parte: str):
    plantilla, titulo = PORTADAS[parte]
    return render(request, plantilla, {"titulo": titulo})


def proximamente(request, seccion: str, slug: str | None = None):
    return render(request, "sitio/proximamente.html", {"titulo": seccion, "seccion": seccion})


# ===========================
# Campeonatos
# ===========================

def campeonatos(request):
    visibles = list(q.campeonatos_visibles())
    en_curso = [c for c in visibles if c.estado == Campeonato.Estado.EN_CURSO]
    return render(request, "sitio/campeonatos/inicio.html", {
        "titulo": "Resultados, tablas y pilotos",
        "en_curso": [(c, q.resumen_categorias(c)) for c in en_curso],
        "finalizados": [c for c in visibles if c.estado == Campeonato.Estado.FINALIZADO],
        "proximas": q.proximas_fechas(en_curso),
    })


def campeonato(request, slug: str):
    camp = q.campeonato_visible(slug)
    categorias = list(camp.categorias.all())
    elegida = None
    if categorias:
        pedida = request.GET.get("categoria", "")
        elegida = next((c for c in categorias if str(c.pk) == pedida), categorias[0])
    contexto = {
        "titulo": str(camp),
        "camp": camp,
        "categorias": categorias,
        "elegida": elegida,
        "tabla": None,
        "fechas": [],
    }
    if elegida:
        filas, provisoria = tabla_posiciones(elegida)
        contexto.update(tabla=filas, provisoria=provisoria, fechas=q.fechas_de_categoria(camp, elegida))
    return render(request, "sitio/campeonatos/campeonato.html", contexto)


def pilotos(request):
    busqueda = (request.GET.get("q") or "").strip()[:60]
    return render(request, "sitio/campeonatos/pilotos.html", {
        "titulo": "Pilotos",
        "pilotos": q.pilotos_visibles(busqueda),
        "busqueda": busqueda,
    })


def piloto(request, slug: str):
    perfil = q.piloto_visible(slug)
    archivos = q.galeria(piloto=perfil)
    return render(request, "sitio/campeonatos/piloto.html", {
        "titulo": perfil.nombre_publico,
        "perfil": perfil,
        "asociaciones": perfil.asociaciones_aprobadas(),
        "participaciones": q.participaciones(perfil),
        "autos": q.autos_visibles_de(perfil),
        "palmares": perfil.palmares.all(),
        "fotos": [a for a in archivos if a.es_imagen],
        "videos": [a for a in archivos if a.video_embed_url],
    })


def auto(request, slug: str):
    auto_ = q.auto_visible(slug)
    archivos = q.galeria(auto=auto_)
    inscripciones = (
        auto_.inscripciones.filter(categoria__campeonato__in=q.campeonatos_visibles())
        .select_related("categoria__campeonato", "piloto__usuario")
    )
    return render(request, "sitio/campeonatos/auto.html", {
        "titulo": str(auto_),
        "auto": auto_,
        "pilotos": q.pilotos_del_auto(auto_),
        "inscripciones": inscripciones,
        "fotos": [a for a in archivos if a.es_imagen],
        "videos": [a for a in archivos if a.video_embed_url],
    })


def asociaciones(request):
    return render(request, "sitio/campeonatos/asociaciones.html", {
        "titulo": "Asociaciones",
        "asociaciones": q.asociaciones_visibles(),
    })


def asociacion(request, slug: str):
    asoc = q.asociacion_visible(slug)
    return render(request, "sitio/campeonatos/asociacion.html", {
        "titulo": asoc.nombre,
        "asoc": asoc,
        "campeonatos": q.campeonatos_visibles().filter(asociacion=asoc),
        "pilotos": q.pilotos_visibles(asociacion=asoc),
    })
