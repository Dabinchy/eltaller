"""
Las tres partes del sitio público.

- El Taller (portada): autos de calle, generar confianza y conseguir clientes.
- El Prepa (/prepa/): competición, personalización y restauración de clásicos.
- Campeonatos: resultados, tablas y pilotos. Es de las asociaciones, no sólo del taller,
  por eso tiene identidad propia.

Cada parte tiene su marca, su menú, su botón principal y su botón de ingreso. Un ítem cuya
dirección todavía no existe no aparece (igual que en core/menu.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.conf import settings
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse

TALLER, PREPA, CAMPEONATOS = "taller", "prepa", "campeonatos"


@dataclass(frozen=True)
class Parte:
    clave: str
    nombre: str
    inicio: str                       # nombre de la URL de su portada
    icono: str
    lema: str                         # texto corto debajo del nombre (pie, pestañas en pantallas grandes)
    logo: str = ""                    # archivo estático; vacío = se muestra el nombre con el ícono
    favicon: str = ""                 # ícono de la pestaña del navegador (archivo estático)
    menu: tuple = field(default_factory=tuple)   # (título, nombre de URL)
    accion: tuple | None = None       # botón principal: (texto, nombre de URL, ícono, texto corto)
    ingreso: tuple = ("Ingresar", "bi-box-arrow-in-right")   # botón de ingreso: (texto, ícono)
    ingreso_ayuda: str = ""           # texto en la pantalla de ingreso


PARTES: dict[str, Parte] = {
    TALLER: Parte(
        clave=TALLER,
        nombre=settings.TALLER_MARCA_NOMBRE,
        inicio="sitio:inicio",
        icono="bi-wrench-adjustable",
        lema="Mecánica de confianza",
        logo=settings.TALLER_MARCA_LOGO,
        favicon=settings.TALLER_MARCA_FAVICON,
        menu=(
            ("Servicios", "sitio:servicios"),
            ("Trabajos", "sitio:trabajos"),
            ("Novedades", "sitio:publicaciones"),
            ("Contacto", "sitio:contacto"),
        ),
        accion=("Pedir presupuesto", "sitio:presupuesto", "bi-calendar-check", "Presupuesto"),
        ingreso=("Seguí tu vehículo", "bi-car-front"),
        ingreso_ayuda="Clientes: seguí el trabajo de tu vehículo y autorizá presupuestos.",
    ),
    PREPA: Parte(
        clave=PREPA,
        nombre=settings.PORTAL_MARCA_NOMBRE,
        inicio="sitio:prepa",
        icono="bi-speedometer2",
        lema="Competición, personalización y clásicos",
        logo=settings.PORTAL_MARCA_LOGO,
        favicon=settings.PORTAL_MARCA_FAVICON,
        menu=(
            ("Competición", "sitio:prepa_competicion"),
            ("Personalización", "sitio:prepa_personalizacion"),
            ("Clásicos", "sitio:prepa_clasicos"),
            ("Proyectos", "sitio:prepa_proyectos"),
        ),
        accion=("Contanos tu proyecto", "sitio:prepa_consulta", "bi-chat-dots", "Consultar"),
        ingreso=("Seguí tu proyecto", "bi-car-front"),
        ingreso_ayuda="Clientes: seguí el avance de tu proyecto y autorizá presupuestos.",
    ),
    CAMPEONATOS: Parte(
        clave=CAMPEONATOS,
        nombre="Campeonatos",
        inicio="sitio:campeonatos",
        icono="bi-trophy",
        lema="Resultados, tablas y pilotos",
        favicon=settings.CAMPEONATOS_FAVICON,
        menu=(
            ("Campeonatos", "sitio:campeonatos"),
            ("Pilotos", "sitio:pilotos"),
            ("Asociaciones", "sitio:asociaciones"),
        ),
        ingreso=("Acceso pilotos", "bi-person-badge"),
        ingreso_ayuda="Pilotos y moderadores: ingresá con tu usuario.",
    ),
}

# Direcciones que pertenecen a cada parte (lo que no está acá es de El Taller).
_PREFIJOS = (
    ("/prepa/", PREPA),
    ("/campeonatos/", CAMPEONATOS),
    ("/pilotos/", CAMPEONATOS),
    ("/autos/", CAMPEONATOS),
    ("/asociaciones/", CAMPEONATOS),
)


def parte_de_ruta(ruta: str) -> str:
    for prefijo, clave in _PREFIJOS:
        if ruta.startswith(prefijo):
            return clave
    return TALLER


def parte_de_request(request) -> str:
    """En la pantalla de ingreso manda ?parte=...; en el resto, la dirección."""
    ruta = getattr(request, "path", "") or "/"
    if ruta.startswith("/ingresar/"):
        pedida = request.GET.get("parte") or request.POST.get("parte") or ""
        return pedida if pedida in PARTES else TALLER
    return parte_de_ruta(ruta)


def marca_de(clave: str) -> dict:
    """Clave, nombre, logo e ícono de pestaña para el título, el color y la pantalla de ingreso."""
    parte = PARTES[clave]
    logo = parte.logo or settings.TALLER_MARCA_LOGO
    favicon = parte.favicon or settings.TALLER_MARCA_FAVICON
    return {"clave": clave, "nombre": parte.nombre, "logo": static(logo), "favicon": static(favicon)}


def _url(nombre: str) -> str | None:
    try:
        return reverse(nombre)
    except NoReverseMatch:
        return None


def contexto(request, clave: str) -> dict:
    """Todo lo que el encabezado y el pie necesitan, ya con las direcciones resueltas."""
    ruta = getattr(request, "path", "") or "/"
    login = reverse("login")

    def armar(p: Parte) -> dict:
        inicio = reverse(p.inicio)
        menu = []
        for titulo, nombre in p.menu:
            url = _url(nombre)
            if url:
                menu.append({"titulo": titulo, "url": url, "activo": ruta.startswith(url) and url != "/"})
        accion = None
        if p.accion and (url := _url(p.accion[1])):
            accion = {"texto": p.accion[0], "url": url, "icono": p.accion[2], "corto": p.accion[3]}
        return {
            "clave": p.clave,
            "nombre": p.nombre,
            "lema": p.lema,
            "icono": p.icono,
            "logo": static(p.logo) if p.logo else "",
            "inicio": inicio,
            "menu": menu,
            "accion": accion,
            "ingreso": {"texto": p.ingreso[0], "icono": p.ingreso[1], "url": f"{login}?parte={p.clave}"},
            "ingreso_ayuda": p.ingreso_ayuda,
            "activa": p.clave == clave,
        }

    partes = [armar(p) for p in PARTES.values()]
    return {"parte": next(p for p in partes if p["activa"]), "partes": partes}
