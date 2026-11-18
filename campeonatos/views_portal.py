"""
Campeonatos del piloto en el portal (/portal/campeonatos/): inscribirse, cargar sus resultados
y ver la tabla en vivo. Vive en la app campeonatos porque campeonatos depende de portal (nunca al revés).
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from portal.acceso import piloto_requerido
from portal.models_contenido import PilotoAuto

from . import servicios as s
from .models import Campeonato, Carrera, Inscripcion, Resultado
from .tabla import tabla_posiciones


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


class InscripcionForm(forms.Form):
    categoria = forms.ModelChoiceField(queryset=None, label="Categoría")
    numero = forms.CharField(label="Tu número", max_length=5)
    auto = forms.ModelChoiceField(queryset=None, label="Auto (opcional)", required=False)

    def __init__(self, *args, campeonato=None, perfil=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].queryset = campeonato.categorias.all()
        from portal.models_contenido import Auto

        self.fields["auto"].queryset = Auto.objects.filter(
            pilotos__piloto=perfil, pilotos__estado=PilotoAuto.Estado.ACEPTADA,
        )


class ResultadoForm(forms.Form):
    condicion = forms.ChoiceField(choices=Resultado.Condicion.choices, label="¿Cómo terminaste?")
    posicion = forms.IntegerField(min_value=1, required=False, label="Posición")
    pole = forms.BooleanField(required=False, label="Hice la pole")
    vuelta_rapida = forms.BooleanField(required=False, label="Hice la vuelta rápida")


def _campeonatos_de(perfil):
    """Campeonatos visibles para el piloto: los de sus asociaciones aprobadas (no borradores)."""
    return Campeonato.objects.filter(
        asociacion__in=perfil.asociaciones_aprobadas(),
    ).exclude(estado=Campeonato.Estado.BORRADOR).select_related("asociacion")


@piloto_requerido
def inicio(request):
    perfil = request.perfil
    inscripciones = Inscripcion.objects.filter(piloto=perfil, estado=Inscripcion.Estado.ACTIVA).select_related(
        "categoria__campeonato"
    )
    return render(request, "campeonatos/portal_inicio.html", {
        "titulo": "Mis campeonatos",
        "inscripciones": inscripciones,
        "campeonatos": _campeonatos_de(perfil).order_by("-temporada", "nombre"),
    })


@piloto_requerido
def campeonato(request, slug):
    perfil = request.perfil
    c = get_object_or_404(_campeonatos_de(perfil), slug=slug)
    mias = list(Inscripcion.objects.filter(piloto=perfil, categoria__campeonato=c, estado=Inscripcion.Estado.ACTIVA)
                .select_related("categoria"))
    mis_resultados = {
        (r.carrera_id, r.inscripcion_id): r
        for r in Resultado.objects.filter(inscripcion__in=mias).select_related("carrera")
    }
    fechas = []
    for f in c.fechas.prefetch_related("carreras", "categorias").order_by("numero"):
        carreras = []
        for carrera in f.carreras.all():
            for insc in mias:
                if not f.corre_categoria(insc.categoria):
                    continue
                r = mis_resultados.get((carrera.pk, insc.pk))
                editable = (c.estado == Campeonato.Estado.EN_CURSO and f.carga_abierta
                            and (r is None or r.estado not in (Resultado.Estado.VALIDADO, Resultado.Estado.ANULADO)))
                carreras.append({
                    "carrera": carrera, "inscripcion": insc, "resultado": r, "editable": editable,
                    "form": ResultadoForm(initial={
                        "condicion": r.condicion if r else Resultado.Condicion.FINALIZO,
                        "posicion": r.posicion if r else None, "pole": r.pole if r else False,
                        "vuelta_rapida": r.vuelta_rapida if r else False,
                    }, prefix=f"r{carrera.pk}-{insc.pk}") if editable else None,
                })
        fechas.append({"fecha": f, "carreras": carreras})
    tablas = []
    for insc in mias:
        filas, provisoria = tabla_posiciones(insc.categoria)
        tablas.append({"categoria": insc.categoria, "filas": filas, "provisoria": provisoria, "mi_inscripcion": insc})
    return render(request, "campeonatos/portal_campeonato.html", {
        "titulo": str(c), "campeonato": c, "inscripciones": mias, "fechas": fechas, "tablas": tablas,
        "hoy": timezone.localdate(),
        "form_inscripcion": InscripcionForm(campeonato=c, perfil=perfil)
        if c.estado == Campeonato.Estado.EN_CURSO else None,
    })


@require_POST
@piloto_requerido
def inscribirse(request, slug):
    perfil = request.perfil
    c = get_object_or_404(_campeonatos_de(perfil), slug=slug)
    form = InscripcionForm(request.POST, campeonato=c, perfil=perfil)
    if form.is_valid():
        d = form.cleaned_data
        try:
            s.inscribirse(perfil, d["categoria"], d["numero"], auto=d["auto"])
            messages.success(request, f"Inscripto en {d['categoria'].nombre} con el número {d['numero']}.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, "Revisá la categoría y el número.")
    return redirect("campeonatos_portal:campeonato", c.slug)


@require_POST
@piloto_requerido
def baja(request, pk):
    insc = get_object_or_404(Inscripcion, pk=pk, piloto=request.perfil)
    try:
        s.dar_de_baja(insc, request.user)
        messages.info(request, "Te diste de baja de esa categoría.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect("campeonatos_portal:campeonato", insc.categoria.campeonato.slug)


@require_POST
@piloto_requerido
def cargar_resultado(request, carrera_pk, inscripcion_pk):
    perfil = request.perfil
    carrera = get_object_or_404(Carrera.objects.select_related("fecha__campeonato"), pk=carrera_pk)
    insc = get_object_or_404(Inscripcion, pk=inscripcion_pk, piloto=perfil)
    form = ResultadoForm(request.POST, prefix=f"r{carrera.pk}-{insc.pk}")
    slug = carrera.fecha.campeonato.slug
    if form.is_valid():
        try:
            r = s.cargar_resultado(perfil, carrera, inscripcion=insc, **form.cleaned_data)
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
        else:
            if r.estado == Resultado.Estado.OBSERVADO:
                messages.warning(request, f"Cargado, pero quedó observado: {r.motivo} Un moderador lo va a revisar.")
            else:
                messages.success(request, f"Resultado cargado: {r.puntos} puntos (provisorio).")
    else:
        messages.error(request, "Revisá el resultado.")
    return redirect(reverse("campeonatos_portal:campeonato", args=[slug]) + f"#fecha-{carrera.fecha.numero}")
