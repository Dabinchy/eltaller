from __future__ import annotations

from django.apps import AppConfig


class ClientesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clientes"
    verbose_name = "Clientes y cuenta corriente"

    def ready(self):
        from . import signals  # noqa: F401
