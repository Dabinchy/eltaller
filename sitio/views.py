"""
Vistas del sitio público.

- El Taller: portada, servicios, trabajos, presupuesto y contacto, con el contenido cargado
  en el admin (sitio/models.py). Sin contenido se ven textos por defecto.
- El Prepa: portada provisoria (se completa en su parte).
- Formularios: guardan una Consulta, con campo trampa y límite de envíos por conexión.
- Campeonatos: campeonatos, tablas, resultados, pilotos, autos y asociaciones (sólo lo visible).
"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from campeonatos.models import Campeonato
from campeonatos.tabla import tabla_posiciones

from . import consultas as q
from .forms import ConsultaForm
from .models import Consulta, FotoTrabajo, Parte, Portada, Servicio, Testimonio, Trabajo

PORTADAS = {
    "prepa": ("sitio/prepa/inicio.html", "Competición, personalización y clásicos"),
}


def portada(request, parte: str):
    plantilla, titulo = PORTADAS[parte]
    return render(request, plantilla, {"titulo": titulo})


# ===========================
# El Taller
# ===========================

def _trabajos_taller():
    return Trabajo.objects.publicados().filter(tipo=Trabajo.Tipo.CALLE)


def inicio(request):
    trabajos = list(_trabajos_taller().filter(destacado=True)[:6]) or list(_trabajos_taller()[:3])
    return render(request, "sitio/taller/inicio.html", {
        "titulo": "Mecánica de confianza",
        "portada": Portada.objects.filter(parte=Parte.TALLER).first(),
        "servicios": Servicio.objects.publicados().filter(parte=Parte.TALLER)[:6],
        "trabajos": trabajos,
        "testimonios": Testimonio.objects.publicados().filter(parte=Parte.TALLER)[:6],
    })


def servicios(request):
    return render(request, "sitio/taller/servicios.html", {
        "titulo": "Servicios",
        "servicios": Servicio.objects.publicados().filter(parte=Parte.TALLER),
    })


def trabajos(request):
    pagina = Paginator(_trabajos_taller(), 12).get_page(request.GET.get("pagina"))
    return render(request, "sitio/taller/trabajos.html", {"titulo": "Trabajos realizados", "pagina": pagina})


def trabajo(request, slug: str):
    t = get_object_or_404(_trabajos_taller(), slug=slug)
    fotos = list(t.fotos.all())
    etapas = [
        (etiqueta, [f for f in fotos if f.etapa == valor])
        for valor, etiqueta in FotoTrabajo.Etapa.choices
    ]
    etapas = [(etiqueta, lista) for etiqueta, lista in etapas if lista]
    sin_etapa = [f for f in fotos if not f.etapa]
    return render(request, "sitio/taller/trabajo.html", {
        "titulo": t.titulo,
        "trabajo": t,
        "etapas": etapas,
        "sin_etapa": sin_etapa,
        "hay_fotos": bool(fotos),
        "otros": _trabajos_taller().exclude(pk=t.pk)[:3],
    })


# ===========================
# Formularios (consultas)
# ===========================

def _ip(request) -> str:
    # Detrás de Cloudflare/nginx la IP real llega en CF-Connecting-IP (lo configura el despliegue).
    return request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR") or "desconocida"


def guardar_consulta(request, tipo: str, parte: str, plantilla: str, contexto: dict):
    """Muestra y procesa un formulario de consulta. Al guardar, lleva a la pantalla de gracias."""
    form = ConsultaForm(request.POST or None, tipo=tipo, parte=parte)
    clave_ip = f"consulta-ip:{_ip(request)}"
    if request.method == "POST":
        if (cache.get(clave_ip) or 0) >= settings.SITIO_CONSULTAS_POR_IP_HORA:
            form.add_error(None, "Se enviaron muchas consultas desde esta conexión. Probá más tarde o escribinos por WhatsApp.")
        elif form.is_valid():
            if not form.es_robot:  # a un robot se lo despide como si nada
                form.save()
                cache.set(clave_ip, (cache.get(clave_ip) or 0) + 1, 3600)
            return redirect("sitio:consulta_enviada", tipo=tipo)
    return render(request, plantilla, {**contexto, "form": form})


def presupuesto(request):
    return guardar_consulta(request, Consulta.Tipo.PRESUPUESTO, Parte.TALLER, "sitio/taller/presupuesto.html", {
        "titulo": "Pedir presupuesto",
    })


def contacto(request):
    return guardar_consulta(request, Consulta.Tipo.CONTACTO, Parte.TALLER, "sitio/taller/contacto.html", {
        "titulo": "Contacto",
    })


_TEXTOS_GRACIAS = {
    Consulta.Tipo.PRESUPUESTO: "Hola, acabo de pedir un presupuesto desde la web.",
    Consulta.Tipo.CONTACTO: "Hola, les escribí desde la web.",
    Consulta.Tipo.PROYECTO: "Hola, les conté mi proyecto desde la web de El Prepa.",
}


def consulta_enviada(request, tipo: str):
    if tipo not in Consulta.Tipo.values:
        raise Http404()
    return render(request, "sitio/consulta_enviada.html", {
        "titulo": "¡Gracias!",
        "texto_whatsapp": _TEXTOS_GRACIAS[tipo],
    })


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
