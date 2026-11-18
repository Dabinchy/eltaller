"""
Gestión de campeonatos por los moderadores (/portal/moderacion/campeonatos/): estructura
(campeonato, categorías, tabla de puntos, fechas, carreras), inscripciones y resultados.
Cada objeto se busca dentro de las asociaciones que modera el usuario (si no, 404) y las reglas
están en campeonatos/servicios.py.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from portal.views_moderacion import moderador_requerido

from . import servicios as s
from .forms import CampeonatoForm, CarreraForm, CategoriaForm, CorregirResultadoForm, FechaForm, PuntosForm
from .models import Campeonato, Carrera, Categoria, Fecha, Inscripcion, Resultado, TipoCarrera

ER = Resultado.Estado


def _texto(e):
    return "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)


def _errores(form) -> str:
    return "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items())


def _campeonato(request, pk) -> Campeonato:
    return get_object_or_404(Campeonato, pk=pk, asociacion__in=request.asociaciones)


def _ir(c: Campeonato, ancla=""):
    return redirect(reverse("campeonatos_mod:detalle", args=[c.pk]) + (f"#{ancla}" if ancla else ""))


# ============================================================
# Campeonatos
# ============================================================

@moderador_requerido
def lista(request):
    form = CampeonatoForm(request.POST or None, asociaciones=request.asociaciones)
    if request.method == "POST" and form.is_valid():
        datos = dict(form.cleaned_data)
        asociacion = datos.pop("asociacion")
        try:
            c = s.crear_campeonato(asociacion, request.user, **datos)
        except (ValidationError, PermissionDenied) as e:
            form.add_error(None, _texto(e))
        else:
            messages.success(request, "Campeonato creado en borrador: cargá categorías, puntos y fechas.")
            return redirect("campeonatos_mod:detalle", c.pk)
    return render(request, "campeonatos/mod_lista.html", {
        "titulo": "Campeonatos",
        "campeonatos": Campeonato.objects.filter(asociacion__in=request.asociaciones).select_related("asociacion"),
        "form": form,
    })


@moderador_requerido
def detalle(request, pk):
    c = _campeonato(request, pk)
    tablas = {t: list(c.tabla_puntos.filter(tipo_carrera=t).values_list("puntos", flat=True)) for t in TipoCarrera.values}
    return render(request, "campeonatos/mod_detalle.html", {
        "titulo": str(c), "c": c,
        "form_config": CampeonatoForm(instance=c),
        "form_categoria": CategoriaForm(),
        "form_puntos": PuntosForm(),
        "form_fecha": FechaForm(campeonato=c),
        "form_carrera": CarreraForm(initial={"tipo": TipoCarrera.SERIE}),
        "tablas": [(TipoCarrera(t).label, ", ".join(f"{p:g}" for p in v)) for t, v in tablas.items()],
        "fechas": c.fechas.prefetch_related("carreras", "categorias").order_by("numero"),
        "inscripciones": Inscripcion.objects.filter(categoria__campeonato=c).select_related("piloto", "categoria", "auto")
                         .order_by("categoria__orden", "numero"),
        "observados": Resultado.objects.filter(carrera__fecha__campeonato=c, estado=ER.OBSERVADO).count(),
    })


@require_POST
@moderador_requerido
def editar(request, pk):
    c = _campeonato(request, pk)
    form = CampeonatoForm(request.POST, instance=c)
    if form.is_valid():
        try:
            form.save()
            messages.success(request, "Campeonato actualizado.")
        except ValidationError as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, _errores(form))
    return _ir(c)


@require_POST
@moderador_requerido
def estado(request, pk):
    c = _campeonato(request, pk)
    nuevo = request.POST.get("estado")
    if nuevo not in Campeonato.Estado.values:
        messages.error(request, "Estado inválido.")
    else:
        try:
            s.cambiar_estado(c, request.user, nuevo)
            messages.success(request, f"Campeonato: {c.get_estado_display()}.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    return _ir(c)


@require_POST
@moderador_requerido
def categoria(request, pk):
    c = _campeonato(request, pk)
    form = CategoriaForm(request.POST)
    if form.is_valid():
        try:
            s.crear_categoria(c, request.user, **form.cleaned_data)
            messages.success(request, "Categoría agregada.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, _errores(form))
    return _ir(c, "categorias")


@require_POST
@moderador_requerido
def puntos(request, pk):
    c = _campeonato(request, pk)
    form = PuntosForm(request.POST)
    if form.is_valid():
        try:
            s.definir_tabla_puntos(c, request.user, form.cleaned_data["puntos"], tipo=form.cleaned_data["tipo"])
            messages.success(request, "Tabla de puntos guardada.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, _errores(form))
    return _ir(c, "puntos")


@require_POST
@moderador_requerido
def fecha(request, pk):
    c = _campeonato(request, pk)
    form = FechaForm(request.POST, campeonato=c)
    if form.is_valid():
        datos = dict(form.cleaned_data)
        categorias = list(datos.pop("categorias"))
        try:
            s.crear_fecha(c, request.user, categorias=categorias, **datos)
            messages.success(request, "Fecha agregada (con su Final).")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, _errores(form))
    return _ir(c, "fechas")


@require_POST
@moderador_requerido
def carrera(request, fecha_pk):
    f = get_object_or_404(Fecha, pk=fecha_pk, campeonato__asociacion__in=request.asociaciones)
    form = CarreraForm(request.POST)
    if form.is_valid():
        try:
            s.agregar_carrera(f, request.user, **form.cleaned_data)
            messages.success(request, "Carrera agregada.")
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, _texto(e))
    else:
        messages.error(request, _errores(form))
    return _ir(f.campeonato, "fechas")


@require_POST
@moderador_requerido
def baja(request, pk):
    insc = get_object_or_404(Inscripcion, pk=pk, categoria__campeonato__asociacion__in=request.asociaciones)
    try:
        s.dar_de_baja(insc, request.user, request.POST.get("motivo", ""))
        messages.success(request, "Inscripción dada de baja.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return _ir(insc.categoria.campeonato, "inscripciones")


# ============================================================
# Resultados
# ============================================================

@moderador_requerido
def resultados(request, fecha_pk):
    f = get_object_or_404(Fecha.objects.select_related("campeonato"), pk=fecha_pk,
                          campeonato__asociacion__in=request.asociaciones)
    bloques = []
    for carrera_obj in f.carreras.all():
        for cat in f.campeonato.categorias.all():
            if not f.corre_categoria(cat):
                continue
            lista_res = list(Resultado.objects.filter(carrera=carrera_obj, inscripcion__categoria=cat)
                             .select_related("inscripcion__piloto__usuario", "cargado_por")
                             .order_by("posicion", "inscripcion__numero"))
            con_resultado = {r.inscripcion_id for r in lista_res}
            faltan = cat.inscripciones.filter(estado=Inscripcion.Estado.ACTIVA).exclude(pk__in=con_resultado)
            bloques.append({
                "carrera": carrera_obj, "categoria": cat, "resultados": lista_res, "faltan": faltan,
                "provisorios": sum(1 for r in lista_res if r.estado == ER.PROVISORIO),
            })
    return render(request, "campeonatos/mod_resultados.html", {
        "titulo": f"Resultados · {f}", "fecha": f, "bloques": bloques,
        "condiciones": Resultado.Condicion.choices,
    })


@require_POST
@moderador_requerido
def resultado(request, pk):
    r = get_object_or_404(Resultado.objects.select_related("carrera__fecha"), pk=pk,
                          carrera__fecha__campeonato__asociacion__in=request.asociaciones)
    accion, motivo = request.POST.get("accion"), request.POST.get("motivo", "")
    try:
        if accion == "validar":
            s.validar_resultado(r, request.user)
        elif accion == "observar":
            s.observar_resultado(r, request.user, motivo)
        elif accion == "anular":
            s.anular_resultado(r, request.user, motivo)
        elif accion == "corregir":
            form = CorregirResultadoForm(request.POST)
            if not form.is_valid():
                raise ValidationError(_errores(form))
            d = dict(form.cleaned_data)
            s.corregir_resultado(r, request.user, d.pop("motivo"), **d)
        else:
            raise ValidationError("Acción desconocida.")
        messages.success(request, "Resultado actualizado.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect(reverse("campeonatos_mod:resultados", args=[r.carrera.fecha_id]) + f"#c{r.carrera_id}")


@require_POST
@moderador_requerido
def validar_todos(request, carrera_pk, categoria_pk):
    carrera_obj = get_object_or_404(Carrera.objects.select_related("fecha"), pk=carrera_pk,
                                    fecha__campeonato__asociacion__in=request.asociaciones)
    cat = get_object_or_404(Categoria, pk=categoria_pk, campeonato_id=carrera_obj.fecha.campeonato_id)
    try:
        n = s.validar_carrera(carrera_obj, cat, request.user)
        messages.success(request, f"{n} resultado(s) validado(s).")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, _texto(e))
    return redirect(reverse("campeonatos_mod:resultados", args=[carrera_obj.fecha_id]) + f"#c{carrera_obj.pk}")
