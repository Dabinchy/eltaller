"""
Quién entra a cada sección del portal.

- piloto_requerido: cuenta del portal con perfil de piloto y al menos una membresía aprobada.
  La vista recibe request.perfil.
- cliente_requerido: cuenta del portal con un acceso de cliente aprobado.
Quien todavía está en revisión vuelve al inicio del portal con un aviso (no ve un error).
"""
from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from core.acceso import solo_portal

from .models import AccesoCliente, PerfilPiloto
from .models_contenido import piloto_habilitado


def piloto_requerido(vista):
    @solo_portal
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        perfil = PerfilPiloto.objects.filter(usuario=request.user).first()
        if perfil is None or not piloto_habilitado(perfil):
            messages.info(request, "Esta sección se habilita cuando tu asociación aprueba tu cuenta de piloto.")
            return redirect("portal:inicio")
        request.perfil = perfil
        return vista(request, *args, **kwargs)

    return envoltura


def cliente_requerido(vista):
    @solo_portal
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not AccesoCliente.objects.filter(usuario=request.user, estado=AccesoCliente.Estado.APROBADO).exists():
            messages.info(request, "Esta sección se habilita cuando el taller aprueba tu acceso como cliente.")
            return redirect("portal:inicio")
        return vista(request, *args, **kwargs)

    return envoltura
