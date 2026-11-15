"""
Quién entra a cada área.

- Panel interno (/panel/): personal del taller (Usuario.tipo = STAFF) activo.
- Portal (/portal/): usuarios del portal (Usuario.tipo = PORTAL) activos.
Quien entra al área equivocada es llevado a la suya (no ve un error).
"""
from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def solo_personal(vista):
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if request.user.es_portal:
            return redirect("portal:inicio")
        return vista(request, *args, **kwargs)

    return envoltura


def solo_portal(vista):
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.es_portal:
            return redirect("panel:inicio")
        return vista(request, *args, **kwargs)

    return envoltura
