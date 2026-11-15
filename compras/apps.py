from __future__ import annotations

from django.apps import AppConfig


class ComprasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "compras"
    verbose_name = "Compras y proveedores"

    def ready(self):
        from . import signals  # noqa: F401
