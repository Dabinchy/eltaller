"""Vistas del sitio público. Las portadas son provisorias hasta que se cargue el contenido."""
from __future__ import annotations

from django.shortcuts import render

PORTADAS = {
    "taller": ("sitio/taller/inicio.html", "Mecánica de confianza"),
    "prepa": ("sitio/prepa/inicio.html", "Competición, personalización y clásicos"),
    "campeonatos": ("sitio/campeonatos/inicio.html", "Resultados, tablas y pilotos"),
}


def portada(request, parte: str):
    plantilla, titulo = PORTADAS[parte]
    return render(request, plantilla, {"titulo": titulo})


def proximamente(request, seccion: str, slug: str | None = None):
    return render(request, "sitio/proximamente.html", {"titulo": seccion, "seccion": seccion})
