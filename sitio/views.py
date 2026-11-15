"""Vistas del sitio público (provisorias hasta el paso 6)."""
from __future__ import annotations

from django.shortcuts import render


def inicio(request):
    return render(request, "sitio/inicio.html", {"titulo": "Inicio"})


def proximamente(request, seccion: str, slug: str | None = None):
    return render(request, "sitio/proximamente.html", {"titulo": seccion, "seccion": seccion})
