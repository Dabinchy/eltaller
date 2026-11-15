# core/apps.py
from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Empresa y caja"

    def ready(self):
        """
        Carga de señales (post_migrate, pre_save, pre_delete).
        Los receivers usan dispatch_uid, así que registrarlos más de una vez es inofensivo.
        """
        from . import signals  # noqa: F401