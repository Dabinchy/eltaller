"""
Vistas del sitio público.

- El Taller: portada, servicios, trabajos, presupuesto y contacto.
- El Prepa: portada, secciones (competición, personalización, clásicos), proyectos y
  "Contanos tu proyecto".
- Novedades: de las tres partes; cada una se ve con el encabezado de su parte.
- Formularios: guardan una Consulta, con campo trampa y límite de envíos por conexión.
- Campeonatos: campeonatos, tablas, resultados, pilotos, autos y asociaciones (sólo lo visible).

El contenido se carga en el panel (/panel/sitio/). Sin contenido se ven textos por defecto.
El personal que puede editar ve una barra con "Editar esta página" (contexto `editar`) y puede
abrir borradores como vista previa (con un aviso; para el resto, esas páginas no existen).
"""
from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from campeonatos.models import Campeonato
from campeonatos.tabla import tabla_posiciones

from . import consultas as q
from .context_processors import puede_editar_sitio
from .forms import ConsultaForm
from .models import Consulta, FotoTrabajo, Parte, Portada, Publicacion, Servicio, Testimonio, Trabajo


# ===========================
# Ayudas
# ===========================

def _editar(request, url_name: str, *args, texto: str = "Editar esta página") -> dict | None:
    """Link al panel para la barra del personal; al guardar vuelve a esta página."""
    if not puede_editar_sitio(request.user):
        return None
    return {"url": f"{reverse(url_name, args=args)}?next={quote(request.get_full_path())}", "texto": texto}


def _puede_ver_borrador(request, perm: str) -> bool:
    u = request.user
    return u.is_authenticated and not u.es_portal and (u.is_superuser or u.has_perm(perm))


def _novedades(parte: str, cantidad: int = 3):
    return Publicacion.objects.publicadas().filter(parte=parte)[:cantidad]


def _ficha_trabajo(request, t: Trabajo, *, lista_url: str, lista_texto: str, detalle_url: str, otros, cta: dict):
    """Página de un trabajo (El Taller) o proyecto (El Prepa): galería por etapas, video y otros."""
    fotos = list(t.fotos.all())
    etapas = [(etiqueta, [f for f in fotos if f.etapa == valor]) for valor, etiqueta in FotoTrabajo.Etapa.choices]
    return render(request, "sitio/trabajo.html", {
        "titulo": t.titulo,
        "trabajo": t,
        "etapas": [(etiqueta, lista) for etiqueta, lista in etapas if lista],
        "sin_etapa": [f for f in fotos if not f.etapa],
        "hay_fotos": bool(fotos),
        "otros": otros.exclude(pk=t.pk)[:3],
        "lista_url": lista_url, "lista_texto": lista_texto, "detalle_url": detalle_url, "cta": cta,
        "borrador": None if t.publicado else "Borrador: todavía no se ve en la web.",
        "editar": _editar(request, "sitio_panel:trabajo_editar", t.pk, texto="Editar este trabajo"),
    })


def _trabajo_o_404(request, qs, slug: str) -> Trabajo:
    t = get_object_or_404(qs, slug=slug)
    if not t.publicado and not _puede_ver_borrador(request, "sitio.view_trabajo"):
        raise Http404()
    return t


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
        "novedades": _novedades(Parte.TALLER),
        "editar": _editar(request, "sitio_panel:portada", Parte.TALLER, texto="Editar la portada"),
    })


def servicios(request):
    return render(request, "sitio/taller/servicios.html", {
        "titulo": "Servicios",
        "servicios": Servicio.objects.publicados().filter(parte=Parte.TALLER),
        "editar": _editar(request, "sitio_panel:servicios", texto="Editar los servicios"),
    })


def trabajos(request):
    pagina = Paginator(_trabajos_taller(), 12).get_page(request.GET.get("pagina"))
    return render(request, "sitio/taller/trabajos.html", {
        "titulo": "Trabajos realizados", "pagina": pagina,
        "editar": _editar(request, "sitio_panel:trabajos", texto="Cargar o editar trabajos"),
    })


def trabajo(request, slug: str):
    t = _trabajo_o_404(request, Trabajo.objects.filter(tipo=Trabajo.Tipo.CALLE), slug)
    return _ficha_trabajo(
        request, t, lista_url=reverse("sitio:trabajos"), lista_texto="Trabajos", detalle_url="sitio:trabajo",
        otros=_trabajos_taller(),
        cta={"texto": "¿Tu auto necesita algo parecido?", "boton": "Pedir presupuesto", "url": reverse("sitio:presupuesto")},
    )


# ===========================
# El Prepa
# ===========================

TIPOS_PREPA = (Trabajo.Tipo.COMPETICION, Trabajo.Tipo.PERSONALIZACION, Trabajo.Tipo.CLASICO)

# Cada sección de El Prepa: sus servicios (Servicio.seccion) y sus proyectos (Trabajo.tipo).
SECCIONES_PREPA = {
    Servicio.Seccion.COMPETICION: {
        "titulo": "Competición", "tipo": Trabajo.Tipo.COMPETICION, "icono": "bi-flag",
        "texto": "Preparación de motor, suspensión y seguridad para pista, rally y regularidad.",
        "por_defecto": [
            ("bi-speedometer2", "Motor", "Preparación y puesta a punto según el reglamento de tu categoría."),
            ("bi-arrows-collapse-vertical", "Suspensión y frenos", "Geometría, amortiguación y frenos para cada circuito."),
            ("bi-shield-check", "Seguridad", "Jaulas, butacas, arneses y matafuegos homologados."),
        ],
    },
    Servicio.Seccion.PERSONALIZACION: {
        "titulo": "Personalización", "tipo": Trabajo.Tipo.PERSONALIZACION, "icono": "bi-brush",
        "texto": "Potencia, estética y puesta a punto para que tu auto sea único.",
        "por_defecto": [
            ("bi-lightning-charge", "Potencia", "Mejoras de motor, admisión y escape con puesta a punto."),
            ("bi-palette", "Estética", "Llantas, detalles exteriores e interiores a tu gusto."),
            ("bi-cpu", "Electrónica", "Instrumental, iluminación y accesorios bien instalados."),
        ],
    },
    Servicio.Seccion.CLASICOS: {
        "titulo": "Restauración de clásicos", "tipo": Trabajo.Tipo.CLASICO, "icono": "bi-hourglass-split",
        "texto": "Restauración respetando el original, con el proceso documentado paso a paso.",
        "por_defecto": [
            ("bi-hourglass-split", "Restauración integral", "Chapa, pintura, mecánica y tapizado, respetando el original."),
            ("bi-gear", "Mecánica", "Motores y cajas de época puestos a punto para disfrutarlos."),
            ("bi-images", "Proceso documentado", "Fotos de cada etapa para que sigas la restauración."),
        ],
    },
}


def _proyectos_prepa():
    return Trabajo.objects.publicados().filter(tipo__in=TIPOS_PREPA)


def prepa_inicio(request):
    proyectos = list(_proyectos_prepa().filter(destacado=True)[:6]) or list(_proyectos_prepa()[:3])
    return render(request, "sitio/prepa/inicio.html", {
        "titulo": "Competición, personalización y clásicos",
        "portada": Portada.objects.filter(parte=Parte.PREPA).first(),
        "secciones": [(clave, datos, reverse(f"sitio:prepa_{clave}")) for clave, datos in SECCIONES_PREPA.items()],
        "proyectos": proyectos,
        "testimonios": Testimonio.objects.publicados().filter(parte=Parte.PREPA)[:6],
        "novedades": _novedades(Parte.PREPA),
        "editar": _editar(request, "sitio_panel:portada", Parte.PREPA, texto="Editar la portada"),
    })


def prepa_seccion(request, seccion: str):
    datos = SECCIONES_PREPA[seccion]
    return render(request, "sitio/prepa/seccion.html", {
        "titulo": datos["titulo"], "seccion": datos,
        "servicios": Servicio.objects.publicados().filter(parte=Parte.PREPA, seccion=seccion),
        "proyectos": _proyectos_prepa().filter(tipo=datos["tipo"])[:6],
        "url_proyectos": f"{reverse('sitio:prepa_proyectos')}?tipo={datos['tipo']}",
        "editar": _editar(request, "sitio_panel:servicios", texto="Editar los servicios"),
    })


def prepa_proyectos(request):
    tipo = request.GET.get("tipo") or ""
    qs = _proyectos_prepa()
    if tipo in TIPOS_PREPA:
        qs = qs.filter(tipo=tipo)
    else:
        tipo = ""
    filtros = [("", "Todos")] + [(t.value, t.label.split(" (")[0]) for t in TIPOS_PREPA]
    return render(request, "sitio/prepa/proyectos.html", {
        "titulo": "Proyectos", "pagina": Paginator(qs, 12).get_page(request.GET.get("pagina")),
        "tipo": tipo, "filtros": filtros,
        "editar": _editar(request, "sitio_panel:trabajos", texto="Cargar o editar proyectos"),
    })


def prepa_proyecto(request, slug: str):
    t = _trabajo_o_404(request, Trabajo.objects.filter(tipo__in=TIPOS_PREPA), slug)
    return _ficha_trabajo(
        request, t, lista_url=reverse("sitio:prepa_proyectos"), lista_texto="Proyectos",
        detalle_url="sitio:prepa_proyecto", otros=_proyectos_prepa().filter(tipo=t.tipo),
        cta={"texto": "¿Tenés un proyecto parecido?", "boton": "Contanos tu proyecto", "url": reverse("sitio:prepa_consulta")},
    )


def prepa_consulta(request):
    return guardar_consulta(request, Consulta.Tipo.PROYECTO, Parte.PREPA, "sitio/prepa/consulta.html", {
        "titulo": "Contanos tu proyecto",
    })


# ===========================
# Novedades (las tres partes)
# ===========================

def publicaciones(request):
    parte = request.GET.get("parte") or ""
    qs = Publicacion.objects.publicadas()
    if parte in Parte.values:
        qs = qs.filter(parte=parte)
        request.parte_sitio = parte   # el encabezado de esa parte
    else:
        parte = ""
    return render(request, "sitio/novedades.html", {
        "titulo": "Novedades", "pagina": Paginator(qs, 9).get_page(request.GET.get("pagina")),
        "filtro": parte, "filtros": [("", "Todas")] + list(Parte.choices),
        "editar": _editar(request, "sitio_panel:novedades", texto="Cargar o editar novedades"),
    })


def publicacion(request, slug: str):
    pub = get_object_or_404(Publicacion, slug=slug)
    ahora = timezone.now()
    borrador = None
    if not pub.publicada:
        borrador = "Borrador: todavía no se ve en la web."
    elif pub.fecha > ahora:
        borrador = f"Programada: se ve en la web desde el {timezone.localtime(pub.fecha):%d/%m/%Y a las %H:%M}."
    if borrador and not _puede_ver_borrador(request, "sitio.view_publicacion"):
        raise Http404()
    request.parte_sitio = pub.parte
    return render(request, "sitio/novedad.html", {
        "titulo": pub.titulo, "pub": pub, "borrador": borrador,
        "otras": Publicacion.objects.publicadas().filter(parte=pub.parte).exclude(pk=pub.pk)[:3],
        "url_lista": f"{reverse('sitio:publicaciones')}?parte={pub.parte}",
        "editar": _editar(request, "sitio_panel:novedad", pub.pk, texto="Editar esta novedad"),
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
    if tipo == Consulta.Tipo.PROYECTO:
        request.parte_sitio = Parte.PREPA
    return render(request, "sitio/consulta_enviada.html", {
        "titulo": "¡Gracias!",
        "texto_whatsapp": _TEXTOS_GRACIAS[tipo],
    })


# ===========================
# Campeonatos
# ===========================

def campeonatos(request):
    visibles = list(q.campeonatos_visibles())
    en_curso = [c for c in visibles if c.estado == Campeonato.Estado.EN_CURSO]
    return render(request, "sitio/campeonatos/inicio.html", {
        "titulo": "Resultados, tablas y pilotos",
        "portada": Portada.objects.filter(parte=Parte.CAMPEONATOS).first(),
        "novedades": _novedades(Parte.CAMPEONATOS),
        "editar": _editar(request, "sitio_panel:portada", Parte.CAMPEONATOS, texto="Editar la portada"),
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
