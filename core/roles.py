# core/roles.py
"""
Nombres de los grupos (roles) del personal y utilidad para sincronizar sus permisos.
Los usuarios del portal (pilotos, clientes, moderadores) NO usan grupos: se distinguen por Usuario.tipo = PORTAL.
"""
from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.auth.models import Group, Permission

logger = logging.getLogger(__name__)

GRUPO_GERENTE = "gerente"
GRUPO_JEFE = "jefe"
GRUPO_ADMINISTRACION = "administracion"
GRUPO_MECANICO = "mecanico"

GRUPOS_PERSONAL = (GRUPO_GERENTE, GRUPO_JEFE, GRUPO_ADMINISTRACION, GRUPO_MECANICO)


def sincronizar_permisos_grupo(nombre_grupo: str, app_label: str, labels: Iterable[str]) -> None:
    """
    Deja en el grupo exactamente los permisos indicados PARA ESA APP.

    - Crea el grupo si no existe.
    - `labels` son strings 'app.codename' (ej. 'core.abrir_caja'). Se ignoran los de otras apps.
    - No toca los permisos que el grupo tenga de otras apps.
    - Es idempotente: se puede correr en cada migración sin acumular permisos viejos.
    """
    group, _ = Group.objects.get_or_create(name=nombre_grupo)

    prefijo = app_label + "."
    codenames = {label[len(prefijo):] for label in labels if label.startswith(prefijo)}

    deseados = list(
        Permission.objects.filter(
            content_type__app_label=app_label,
            codename__in=codenames,
        )
    )

    faltan = codenames - {p.codename for p in deseados}
    if faltan:
        logger.warning(
            "Permisos inexistentes en '%s' para el grupo '%s': %s",
            app_label, nombre_grupo, ", ".join(sorted(faltan)),
        )

    otros = list(group.permissions.exclude(content_type__app_label=app_label))
    group.permissions.set(otros + deseados)