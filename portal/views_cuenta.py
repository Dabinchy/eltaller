"""
Registro, perfil del piloto, palmarés y cambio de contraseña.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import PasswordChangeView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .acceso import piloto_requerido
from .forms import PalmaresForm, PerfilForm, RegistroForm
from .models_contenido import Palmares
from .servicios import registrar_cuenta
from .servicios_contenido import uso_cuota


def _ip(request) -> str:
    # Detrás de Cloudflare/nginx la IP real llega en CF-Connecting-IP (lo configura el despliegue).
    return request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR") or "desconocida"


def registro(request):
    if request.user.is_authenticated:
        return redirect("redireccion")
    form = RegistroForm(request.POST or None)
    clave_ip = f"registro-ip:{_ip(request)}"
    if request.method == "POST":
        if (cache.get(clave_ip) or 0) >= settings.PORTAL_REGISTROS_POR_IP_HORA:
            form.add_error(None, "Se hicieron demasiados registros desde esta conexión. Probá más tarde.")
        elif form.is_valid():
            d = form.cleaned_data
            if d.get("web"):
                # Campo trampa completado: es un robot. Se lo despide como si nada.
                messages.success(request, "Recibimos tu solicitud.")
                return redirect("login")
            try:
                usuario = registrar_cuenta(
                    username=d["username"], email=d["email"], password=d["password"],
                    nombre=d["nombre"], apellido=d["apellido"], dni=d["dni"],
                    fecha_nacimiento=d.get("fecha_nacimiento") if d.get("soy_piloto") else None,
                    asociacion=d.get("asociacion") if d.get("soy_piloto") else None,
                    licencia=d.get("licencia", ""), es_cliente=d.get("soy_cliente", False),
                    nota_cliente=d.get("nota_cliente", ""),
                )
            except ValidationError as e:
                for campo, errores in e.message_dict.items():
                    form.add_error(campo if campo in form.fields else None, errores)
            else:
                cache.set(clave_ip, (cache.get(clave_ip) or 0) + 1, 3600)
                login(request, usuario, backend="django.contrib.auth.backends.ModelBackend")
                messages.success(request, "¡Listo! Tu cuenta quedó creada y en revisión.")
                return redirect("portal:inicio")
    return render(request, "portal/registro.html", {"titulo": "Crear cuenta", "form": form})


@piloto_requerido
def perfil(request):
    perfil = request.perfil
    form = PerfilForm(request.POST or None, request.FILES or None, instance=perfil, prefix="perfil")
    if request.method == "POST" and form.is_valid():
        try:
            form.save()
        except ValidationError as e:
            form.add_error(None, "; ".join(e.messages))
        else:
            if perfil.aprobado and perfil.cambio_tras_aprobacion:
                messages.info(request, "Guardado. Los cambios públicos quedan marcados para que tu asociación los revise.")
            else:
                messages.success(request, "Perfil guardado.")
            return redirect("portal:perfil")
    usados, total = uso_cuota(perfil)
    return render(request, "portal/perfil.html", {
        "titulo": "Mi perfil", "perfil": perfil, "form": form, "form_palmares": PalmaresForm(),
        "palmares": perfil.palmares.all(), "asociaciones": perfil.asociaciones_aprobadas(),
        "usados_mb": usados / (1024 * 1024), "total_mb": total / (1024 * 1024),
        "porcentaje": min(100, round(usados * 100 / total)) if total else 0,
    })


@require_POST
@piloto_requerido
def palmares_agregar(request):
    form = PalmaresForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.piloto = request.perfil
        try:
            item.save()
            messages.success(request, "Resultado agregado al palmarés.")
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages))
    else:
        messages.error(request, "Revisá el resultado: " + "; ".join(f"{k}: {v[0]}" for k, v in form.errors.items()))
    return redirect(reverse("portal:perfil") + "#palmares")


@require_POST
@piloto_requerido
def palmares_borrar(request, pk):
    get_object_or_404(Palmares, pk=pk, piloto=request.perfil).delete()
    messages.success(request, "Resultado quitado del palmarés.")
    return redirect(reverse("portal:perfil") + "#palmares")


class CambiarClave(PasswordChangeView):
    """Cambio de contraseña (sirve para el portal y el panel; mientras no haya mail es la única vía)."""

    template_name = "cuenta/clave.html"

    def get_success_url(self):
        return reverse("portal:inicio" if self.request.user.es_portal else "panel:inicio")

    def form_valid(self, form):
        messages.success(self.request, "Contraseña actualizada.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "titulo": "Cambiar contraseña"}
