from __future__ import annotations

from django.apps import AppConfig


class TallerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "taller"
    verbose_name = "Taller"

    def ready(self):
        from . import signals  # noqa: F401
