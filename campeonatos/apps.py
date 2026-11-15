from __future__ import annotations

from django.apps import AppConfig


class CampeonatosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "campeonatos"
    verbose_name = "Campeonatos"

    def ready(self):
        from . import signals  # noqa: F401
