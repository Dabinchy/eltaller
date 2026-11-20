"""
Contenido del sitio público en el panel: /panel/sitio/...

Lo mismo que se hacía en el admin, con el diseño del panel:
- Novedades, trabajos y proyectos (con galería), servicios, testimonios y portadas.
- Consultas que llegan por los formularios de la web.

Permisos (sitio/signals.py): gerente y administración cargan, editan y publican todo; el jefe ve y
responde consultas. No hay paso de aprobación: quien carga, publica.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.acceso import solo_personal
from sitio.models import Consulta, FotoTrabajo, Parte, Portada, Publicacion, Servicio, Testimonio, Trabajo

from .forms_sitio import (
    ConsultaNotasForm,
    FotoForm,
    PortadaForm,
    PublicacionForm,
    ServicioForm,
    SubirFotosForm,
    TestimonioForm,
    TrabajoForm,
)

POR_PAGINA = 25


# ===========================
# Ayudas
# ===========================

def _puede(user, perm: str) -> bool:
    return user.is_superuser or user.has_perm(perm)


def _exigir(user, perm: str) -> None:
    if not _puede(user, perm):
        raise PermissionDenied


def _volver(request, por_defecto: str) -> str:
    """Vuelve a donde se estaba (?next= o campo next), si es una dirección de este sitio."""
    destino = request.POST.get("next") or request.GET.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(destino, {request.get_host()}, request.is_secure()):
        return destino
    return por_defecto


def _paginar(request, qs):
    return Paginator(qs, POR_PAGINA).get_page(request.GET.get("pagina"))


def _guardar_form(request, form_cls, instancia, *, perm, titulo, volver, plantilla="panel/sitio/form.html",
                  inicial=None, al_crear=None, extra=None):
    """Alta/edición común: muestra el formulario, guarda y vuelve con un aviso."""
    _exigir(request.user, perm)
    if request.method == "POST":
        form = form_cls(request.POST, request.FILES, instance=instancia)
        if form.is_valid():
            nuevo = form.instance.pk is None
            obj = form.save(commit=False)
            if nuevo and al_crear:
                al_crear(obj)
            obj.save()
            messages.success(request, f"«{obj}» guardado.")
            return obj, None
    else:
        form = form_cls(instance=instancia, initial=inicial)
    contexto = {"titulo": titulo, "form": form, "volver": volver, **(extra or {})}
    return None, render(request, plantilla, contexto)


def _siguiente_orden(qs) -> int:
    maximo = qs.aggregate(m=Max("orden"))["m"]
    return 0 if maximo is None else maximo + 1


def _whatsapp(numero: str) -> str:
    """Link de WhatsApp para el teléfono que dejó el visitante (si no tiene código de país, asume Argentina)."""
    digitos = re.sub(r"\D", "", numero or "")
    if not digitos:
        return ""
    if not digitos.startswith("54"):
        digitos = digitos.lstrip("0")
        if len(digitos) == 10:
            digitos = "549" + digitos
    return f"https://wa.me/{digitos}"


# ===========================
# Acciones comunes (publicar, mover, borrar)
# ===========================

@dataclass(frozen=True)
class _Tipo:
    modelo: type
    campo_publicado: str
    perm: str          # sufijo del permiso: sitio.change_<perm>
    lista: str         # nombre de la URL de la lista
    agrupar: tuple = ()  # campos que separan los grupos al ordenar (None = no se ordena)


TIPOS = {
    "novedades": _Tipo(Publicacion, "publicada", "publicacion", "sitio_panel:novedades"),
    "trabajos": _Tipo(Trabajo, "publicado", "trabajo", "sitio_panel:trabajos"),
    "servicios": _Tipo(Servicio, "publicado", "servicio", "sitio_panel:servicios", ("parte", "seccion")),
    "testimonios": _Tipo(Testimonio, "publicado", "testimonio", "sitio_panel:testimonios", ("parte",)),
}


def _tipo(nombre: str) -> _Tipo:
    if nombre not in TIPOS:
        raise PermissionDenied
    return TIPOS[nombre]


def _reordenar(qs, obj, direccion: str) -> None:
    """Sube o baja obj un lugar dentro de qs y deja los números de orden prolijos (0, 1, 2…)."""
    items = list(qs)
    i = next(n for n, x in enumerate(items) if x.pk == obj.pk)
    j = i - 1 if direccion == "subir" else i + 1
    if 0 <= j < len(items):
        items[i], items[j] = items[j], items[i]
    for n, x in enumerate(items):
        if x.orden != n:
            x.orden = n
            x.save(update_fields=["orden"])


@solo_personal
@require_POST
def publicar(request, tipo: str, pk: int):
    t = _tipo(tipo)
    _exigir(request.user, f"sitio.change_{t.perm}")
    obj = get_object_or_404(t.modelo, pk=pk)
    valor = request.POST.get("valor") == "1"
    setattr(obj, t.campo_publicado, valor)
    obj.save(update_fields=[t.campo_publicado])
    if valor:
        aviso = f"«{obj}» publicado."
        if isinstance(obj, Publicacion) and obj.fecha > timezone.now():
            aviso = f"«{obj}» queda programado: se ve en la web desde el {timezone.localtime(obj.fecha):%d/%m/%Y %H:%M}."
        messages.success(request, aviso)
    else:
        messages.success(request, f"«{obj}» ya no se ve en la web.")
    return redirect(_volver(request, reverse(t.lista)))


@solo_personal
@require_POST
def destacar(request, pk: int):
    _exigir(request.user, "sitio.change_trabajo")
    trabajo = get_object_or_404(Trabajo, pk=pk)
    trabajo.destacado = request.POST.get("valor") == "1"
    trabajo.save(update_fields=["destacado"])
    messages.success(request, f"«{trabajo}» {'aparece' if trabajo.destacado else 'ya no aparece'} en la portada.")
    return redirect(_volver(request, reverse("sitio_panel:trabajos")))


@solo_personal
@require_POST
def mover(request, tipo: str, pk: int):
    t = _tipo(tipo)
    if not t.agrupar:
        raise PermissionDenied
    _exigir(request.user, f"sitio.change_{t.perm}")
    obj = get_object_or_404(t.modelo, pk=pk)
    grupo = t.modelo.objects.filter(**{c: getattr(obj, c) for c in t.agrupar})
    with transaction.atomic():
        _reordenar(grupo.order_by("orden", "id").select_for_update(), obj, request.POST.get("direccion", ""))
    return redirect(_volver(request, reverse(t.lista)))


@solo_personal
@require_POST
def borrar(request, tipo: str, pk: int):
    t = _tipo(tipo)
    _exigir(request.user, f"sitio.delete_{t.perm}")
    obj = get_object_or_404(t.modelo, pk=pk)
    nombre = str(obj)
    obj.delete()
    messages.success(request, f"«{nombre}» borrado.")
    return redirect(reverse(t.lista))


# ===========================
# Inicio
# ===========================

@solo_personal
def inicio(request):
    user = request.user
    puede_contenido = any(
        _puede(user, f"sitio.view_{m}") for m in ("publicacion", "trabajo", "servicio", "testimonio", "portada")
    )
    puede_consultas = _puede(user, "sitio.view_consulta")
    if not (puede_contenido or puede_consultas):
        raise PermissionDenied

    ahora = timezone.now()
    tarjetas = []
    if puede_consultas:
        nuevas = Consulta.objects.filter(estado=Consulta.Estado.NUEVA).count()
        tarjetas.append({
            "titulo": "Consultas", "icono": "bi-chat-left-text", "url": reverse("sitio_panel:consultas"),
            "valor": nuevas, "detalle": "nuevas sin responder" if nuevas != 1 else "nueva sin responder",
            "alerta": nuevas > 0,
        })
    if _puede(user, "sitio.view_publicacion"):
        qs = Publicacion.objects.all()
        tarjetas.append({
            "titulo": "Novedades", "icono": "bi-newspaper", "url": reverse("sitio_panel:novedades"),
            "valor": qs.publicadas().count(), "detalle": "publicadas",
            "extra": [("Programadas", qs.filter(publicada=True, fecha__gt=ahora).count()),
                      ("Borradores", qs.filter(publicada=False).count())],
        })
    if _puede(user, "sitio.view_trabajo"):
        qs = Trabajo.objects.all()
        tarjetas.append({
            "titulo": "Trabajos y proyectos", "icono": "bi-images", "url": reverse("sitio_panel:trabajos"),
            "valor": qs.publicados().count(), "detalle": "publicados",
            "extra": [("Destacados", qs.filter(publicado=True, destacado=True).count()),
                      ("Borradores", qs.filter(publicado=False).count())],
        })
    if _puede(user, "sitio.view_servicio"):
        qs = Servicio.objects.all()
        tarjetas.append({
            "titulo": "Servicios", "icono": "bi-tools", "url": reverse("sitio_panel:servicios"),
            "valor": qs.publicados().count(), "detalle": "publicados",
            "extra": [("Borradores", qs.filter(publicado=False).count())],
        })
    if _puede(user, "sitio.view_testimonio"):
        qs = Testimonio.objects.all()
        tarjetas.append({
            "titulo": "Testimonios", "icono": "bi-chat-quote", "url": reverse("sitio_panel:testimonios"),
            "valor": qs.publicados().count(), "detalle": "publicados",
            "extra": [("Borradores", qs.filter(publicado=False).count())],
        })
    if _puede(user, "sitio.view_portada"):
        cargadas = Portada.objects.count()
        tarjetas.append({
            "titulo": "Portadas", "icono": "bi-window", "url": reverse("sitio_panel:portadas"),
            "valor": cargadas, "detalle": f"de {len(Parte.choices)} personalizadas",
        })

    return render(request, "panel/sitio/inicio.html", {
        "titulo": "Sitio web", "tarjetas": tarjetas,
        "puede_crear_novedad": _puede(user, "sitio.add_publicacion"),
        "puede_crear_trabajo": _puede(user, "sitio.add_trabajo"),
    })


# ===========================
# Novedades
# ===========================

ESTADOS_NOVEDAD = [("publicadas", "Publicadas"), ("programadas", "Programadas"), ("borradores", "Borradores")]


@solo_personal
def novedades(request):
    user = request.user
    _exigir(user, "sitio.view_publicacion")
    qs = Publicacion.objects.all()
    q = (request.GET.get("q") or "").strip()
    parte = request.GET.get("parte") or ""
    estado = request.GET.get("estado") or ""
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(resumen__icontains=q) | Q(cuerpo__icontains=q))
    if parte in Parte.values:
        qs = qs.filter(parte=parte)
    ahora = timezone.now()
    if estado == "publicadas":
        qs = qs.filter(publicada=True, fecha__lte=ahora)
    elif estado == "programadas":
        qs = qs.filter(publicada=True, fecha__gt=ahora)
    elif estado == "borradores":
        qs = qs.filter(publicada=False)
    return render(request, "panel/sitio/novedades.html", {
        "titulo": "Novedades", "pagina": _paginar(request, qs), "q": q, "parte": parte, "estado": estado,
        "partes": Parte.choices, "estados": ESTADOS_NOVEDAD, "ahora": ahora,
        "puede_crear": _puede(user, "sitio.add_publicacion"),
        "puede_editar": _puede(user, "sitio.change_publicacion"),
        "puede_borrar": _puede(user, "sitio.delete_publicacion"),
    })


@solo_personal
def novedad_form(request, pk: int | None = None):
    obj = get_object_or_404(Publicacion, pk=pk) if pk else None
    volver = reverse("sitio_panel:novedades")
    guardado, respuesta = _guardar_form(
        request, PublicacionForm, obj,
        perm="sitio.change_publicacion" if obj else "sitio.add_publicacion",
        titulo="Editar novedad" if obj else "Nueva novedad", volver=volver,
        inicial={"parte": request.GET.get("parte")} if not obj and request.GET.get("parte") in Parte.values else None,
        extra={"objeto": obj, "tipo": "novedades", "ver_en_web": _url_publica(obj),
               "puede_borrar": obj and _puede(request.user, "sitio.delete_publicacion")},
    )
    return redirect(_volver(request, volver)) if guardado else respuesta


# ===========================
# Trabajos y proyectos
# ===========================

@solo_personal
def trabajos(request):
    user = request.user
    _exigir(user, "sitio.view_trabajo")
    qs = Trabajo.objects.annotate(cant_fotos=Count("fotos")).order_by("-fecha", "-id")
    q = (request.GET.get("q") or "").strip()
    tipo = request.GET.get("tipo") or ""
    estado = request.GET.get("estado") or ""
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(auto__icontains=q) | Q(resumen__icontains=q))
    if tipo in Trabajo.Tipo.values:
        qs = qs.filter(tipo=tipo)
    if estado == "publicados":
        qs = qs.filter(publicado=True)
    elif estado == "destacados":
        qs = qs.filter(publicado=True, destacado=True)
    elif estado == "borradores":
        qs = qs.filter(publicado=False)
    return render(request, "panel/sitio/trabajos.html", {
        "titulo": "Trabajos y proyectos", "pagina": _paginar(request, qs), "q": q, "tipo": tipo, "estado": estado,
        "tipos": Trabajo.Tipo.choices,
        "estados": [("publicados", "Publicados"), ("destacados", "Destacados"), ("borradores", "Borradores")],
        "puede_crear": _puede(user, "sitio.add_trabajo"),
        "puede_editar": _puede(user, "sitio.change_trabajo"),
    })


@solo_personal
def trabajo_form(request, pk: int | None = None):
    obj = get_object_or_404(Trabajo, pk=pk) if pk else None
    guardado, respuesta = _guardar_form(
        request, TrabajoForm, obj,
        perm="sitio.change_trabajo" if obj else "sitio.add_trabajo",
        titulo="Editar trabajo" if obj else "Nuevo trabajo o proyecto",
        volver=reverse("sitio_panel:trabajo", args=[obj.pk]) if obj else reverse("sitio_panel:trabajos"),
        inicial={"tipo": request.GET.get("tipo")} if not obj and request.GET.get("tipo") in Trabajo.Tipo.values else None,
        extra={"objeto": obj, "tipo": "trabajos", "ver_en_web": _url_publica(obj),
               "puede_borrar": obj and _puede(request.user, "sitio.delete_trabajo")},
    )
    if guardado:
        if not obj:
            messages.info(request, "Ahora podés sumarle fotos a la galería.")
        return redirect("sitio_panel:trabajo", guardado.pk)
    return respuesta


@solo_personal
def trabajo(request, pk: int):
    """Ficha del trabajo: datos, estado y galería de fotos."""
    user = request.user
    _exigir(user, "sitio.view_trabajo")
    obj = get_object_or_404(Trabajo, pk=pk)
    puede_editar = _puede(user, "sitio.change_trabajo")
    fotos = list(obj.fotos.all())
    return render(request, "panel/sitio/trabajo.html", {
        "titulo": obj.titulo, "t": obj, "fotos": [(f, FotoForm(instance=f, prefix=f"f{f.pk}")) for f in fotos],
        "subir": SubirFotosForm(), "puede_editar": puede_editar,
        "puede_borrar": _puede(user, "sitio.delete_trabajo"),
        "puede_fotos": _puede(user, "sitio.add_fototrabajo"),
        "ver_en_web": _url_publica(obj),
    })


@solo_personal
@require_POST
def fotos_subir(request, pk: int):
    _exigir(request.user, "sitio.add_fototrabajo")
    obj = get_object_or_404(Trabajo, pk=pk)
    form = SubirFotosForm(request.POST, request.FILES)
    if not form.is_valid():
        for errores in form.errors.values():
            for e in errores:
                messages.error(request, e)
        return redirect("sitio_panel:trabajo", obj.pk)
    orden = _siguiente_orden(obj.fotos.all())
    with transaction.atomic():
        for n, archivo in enumerate(form.cleaned_data["fotos"]):
            FotoTrabajo(trabajo=obj, imagen=archivo, etapa=form.cleaned_data["etapa"], orden=orden + n).save()
    cant = len(form.cleaned_data["fotos"])
    messages.success(request, f"{cant} foto{'s' if cant != 1 else ''} agregada{'s' if cant != 1 else ''}.")
    if not obj.portada:
        messages.info(request, "El trabajo no tiene foto de portada: podés usar una de la galería.")
    return redirect("sitio_panel:trabajo", obj.pk)


@solo_personal
@require_POST
def foto_accion(request, pk: int):
    """Guardar epígrafe/etapa, mover, usar como portada o borrar una foto de la galería."""
    foto = get_object_or_404(FotoTrabajo.objects.select_related("trabajo"), pk=pk)
    trabajo_obj = foto.trabajo
    accion = request.POST.get("accion")
    if accion == "borrar":
        _exigir(request.user, "sitio.delete_fototrabajo")
        foto.delete()
        messages.success(request, "Foto borrada.")
    elif accion in ("subir", "bajar"):
        _exigir(request.user, "sitio.change_fototrabajo")
        with transaction.atomic():
            _reordenar(trabajo_obj.fotos.order_by("orden", "id").select_for_update(), foto, accion)
    elif accion == "portada":
        _exigir(request.user, "sitio.change_trabajo")
        from django.core.files.base import ContentFile

        foto.imagen.open("rb")
        contenido = ContentFile(foto.imagen.read(), name=foto.imagen.name.rsplit("/", 1)[-1])
        foto.imagen.close()
        trabajo_obj.portada = contenido
        trabajo_obj.save()
        messages.success(request, "Foto de portada cambiada.")
    else:
        _exigir(request.user, "sitio.change_fototrabajo")
        form = FotoForm(request.POST, instance=foto, prefix=f"f{foto.pk}")
        if form.is_valid():
            form.save()
            messages.success(request, "Foto actualizada.")
        else:
            messages.error(request, "No se pudo guardar la foto: revisá el epígrafe.")
    return redirect(reverse("sitio_panel:trabajo", args=[trabajo_obj.pk]) + "#galeria")


# ===========================
# Servicios y testimonios
# ===========================

def _grupos_servicios(qs):
    """[(titulo, [servicios])] en el orden en que aparecen en la web."""
    grupos = [("El Taller", list(qs.filter(parte=Parte.TALLER)))]
    for valor, nombre in Servicio.Seccion.choices:
        grupos.append((f"El Prepa · {nombre}", list(qs.filter(parte=Parte.PREPA, seccion=valor))))
    return grupos


@solo_personal
def servicios(request):
    user = request.user
    _exigir(user, "sitio.view_servicio")
    qs = Servicio.objects.order_by("orden", "id")
    return render(request, "panel/sitio/servicios.html", {
        "titulo": "Servicios", "grupos": _grupos_servicios(qs),
        "puede_crear": _puede(user, "sitio.add_servicio"),
        "puede_editar": _puede(user, "sitio.change_servicio"),
    })


@solo_personal
def servicio_form(request, pk: int | None = None):
    obj = get_object_or_404(Servicio, pk=pk) if pk else None
    volver = reverse("sitio_panel:servicios")
    guardado, respuesta = _guardar_form(
        request, ServicioForm, obj,
        perm="sitio.change_servicio" if obj else "sitio.add_servicio",
        titulo="Editar servicio" if obj else "Nuevo servicio", volver=volver,
        inicial={k: request.GET[k] for k in ("parte", "seccion") if request.GET.get(k)} if not obj else None,
        al_crear=lambda s: setattr(s, "orden", _siguiente_orden(Servicio.objects.filter(parte=s.parte, seccion=s.seccion))),
        extra={"objeto": obj, "tipo": "servicios",
               "puede_borrar": obj and _puede(request.user, "sitio.delete_servicio")},
    )
    return redirect(volver) if guardado else respuesta


@solo_personal
def testimonios(request):
    user = request.user
    _exigir(user, "sitio.view_testimonio")
    qs = Testimonio.objects.order_by("orden", "-creado")
    grupos = [(nombre, list(qs.filter(parte=valor))) for valor, nombre in Testimonio._meta.get_field("parte").choices]
    return render(request, "panel/sitio/testimonios.html", {
        "titulo": "Testimonios", "grupos": grupos,
        "puede_crear": _puede(user, "sitio.add_testimonio"),
        "puede_editar": _puede(user, "sitio.change_testimonio"),
    })


@solo_personal
def testimonio_form(request, pk: int | None = None):
    obj = get_object_or_404(Testimonio, pk=pk) if pk else None
    volver = reverse("sitio_panel:testimonios")
    guardado, respuesta = _guardar_form(
        request, TestimonioForm, obj,
        perm="sitio.change_testimonio" if obj else "sitio.add_testimonio",
        titulo="Editar testimonio" if obj else "Nuevo testimonio", volver=volver,
        al_crear=lambda t: setattr(t, "orden", _siguiente_orden(Testimonio.objects.filter(parte=t.parte))),
        extra={"objeto": obj, "tipo": "testimonios",
               "puede_borrar": obj and _puede(request.user, "sitio.delete_testimonio")},
    )
    return redirect(volver) if guardado else respuesta


# ===========================
# Portadas
# ===========================

@solo_personal
def portadas(request):
    user = request.user
    _exigir(user, "sitio.view_portada")
    cargadas = {p.parte: p for p in Portada.objects.all()}
    filas = [{"parte": valor, "nombre": nombre, "portada": cargadas.get(valor),
              "url_web": reverse({"taller": "sitio:inicio", "prepa": "sitio:prepa",
                                  "campeonatos": "sitio:campeonatos"}[valor])}
             for valor, nombre in Parte.choices]
    return render(request, "panel/sitio/portadas.html", {
        "titulo": "Portadas", "filas": filas,
        "puede_editar": _puede(user, "sitio.change_portada") or _puede(user, "sitio.add_portada"),
    })


@solo_personal
def portada_form(request, parte: str):
    if parte not in Parte.values:
        raise PermissionDenied
    obj = Portada.objects.filter(parte=parte).first()
    volver = reverse("sitio_panel:portadas")
    guardado, respuesta = _guardar_form(
        request, PortadaForm, obj,
        perm="sitio.change_portada" if obj else "sitio.add_portada",
        titulo=f"Portada de {Parte(parte).label}", volver=volver,
        al_crear=lambda p: setattr(p, "parte", parte),
        extra={"objeto": obj, "tipo": "portadas",
               "ayuda": "Lo que se ve arriba de todo en la página de inicio de esta parte. "
                        "Sin foto, se muestra el logo."},
    )
    return redirect(volver) if guardado else respuesta


# ===========================
# Consultas
# ===========================

ESTADOS_CONSULTA = [("nueva", "Nuevas"), ("respondida", "Respondidas"), ("archivada", "Archivadas"), ("todas", "Todas")]


@solo_personal
def consultas(request):
    user = request.user
    _exigir(user, "sitio.view_consulta")
    qs = Consulta.objects.all()
    estado = request.GET.get("estado") or "nueva"
    tipo = request.GET.get("tipo") or ""
    parte = request.GET.get("parte") or ""
    q = (request.GET.get("q") or "").strip()
    if estado in Consulta.Estado.values:
        qs = qs.filter(estado=estado)
    if tipo in Consulta.Tipo.values:
        qs = qs.filter(tipo=tipo)
    if parte in Parte.values:
        qs = qs.filter(parte=parte)
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q) | Q(email__icontains=q)
                       | Q(vehiculo__icontains=q) | Q(mensaje__icontains=q))
    conteo = dict(Consulta.objects.values_list("estado").annotate(n=Count("id")))
    return render(request, "panel/sitio/consultas.html", {
        "titulo": "Consultas del sitio", "pagina": _paginar(request, qs),
        "estado": estado, "tipo": tipo, "parte": parte, "q": q,
        "estados": [(v, n, conteo.get(v) if v != "todas" else sum(conteo.values())) for v, n in ESTADOS_CONSULTA],
        "tipos": Consulta.Tipo.choices, "partes": Parte.choices,
    })


@solo_personal
def consulta(request, pk: int):
    user = request.user
    _exigir(user, "sitio.view_consulta")
    obj = get_object_or_404(Consulta.objects.select_related("respondida_por"), pk=pk)
    puede_cambiar = _puede(user, "sitio.change_consulta")
    if request.method == "POST":
        _exigir(user, "sitio.change_consulta")
        form = ConsultaNotasForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            nuevo_estado = request.POST.get("estado")
            if nuevo_estado in Consulta.Estado.values and nuevo_estado != obj.estado:
                obj.marcar(nuevo_estado, user)
                messages.success(request, f"Consulta marcada como {obj.get_estado_display().lower()}.")
            else:
                messages.success(request, "Notas guardadas.")
            return redirect(_volver(request, reverse("sitio_panel:consulta", args=[obj.pk])))
    else:
        form = ConsultaNotasForm(instance=obj)
    texto_wa = f"Hola {obj.nombre}, te escribimos de {obj.get_parte_display()} por tu consulta en la web."
    from urllib.parse import quote

    wa = _whatsapp(obj.telefono)
    return render(request, "panel/sitio/consulta.html", {
        "titulo": f"Consulta de {obj.nombre}", "c": obj, "form": form, "puede_cambiar": puede_cambiar,
        "puede_borrar": _puede(user, "sitio.delete_consulta"),
        "whatsapp": f"{wa}?text={quote(texto_wa)}" if wa else "",
        "tel": re.sub(r"[^\d+]", "", obj.telefono or ""),
    })


@solo_personal
@require_POST
def consulta_borrar(request, pk: int):
    _exigir(request.user, "sitio.delete_consulta")
    obj = get_object_or_404(Consulta, pk=pk)
    obj.delete()
    messages.success(request, "Consulta borrada.")
    return redirect("sitio_panel:consultas")


# ===========================

def _url_publica(obj) -> str:
    """Dirección en la web, sólo si ya se ve (para el botón "Ver en la web")."""
    if isinstance(obj, Trabajo) and obj.publicado and obj.parte == Parte.TALLER:
        return reverse("sitio:trabajo", args=[obj.slug])
    if isinstance(obj, Trabajo) and obj.publicado:
        return reverse("sitio:prepa_proyecto", args=[obj.slug])
    if isinstance(obj, Publicacion) and obj.publicada and obj.fecha <= timezone.now():
        return reverse("sitio:publicacion", args=[obj.slug])
    return ""
