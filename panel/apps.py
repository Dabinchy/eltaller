from __future__ import annotations

from django.apps import AppConfig


class PanelConfig(AppConfig):
    """
    Pantallas del panel interno que combinan varias apps (taller + portal + ventas...).
    No tiene modelos: ninguna app de negocio depende de ella.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "panel"
    verbose_name = "Panel interno"
