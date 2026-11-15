"""
Almacenamiento para archivos privados (facturas de compra, archivos INTERNO/PILOTO).

Se guardan en settings.PRIVATE_MEDIA_ROOT, fuera de MEDIA_ROOT, y NO tienen URL pública:
se sirven sólo por una vista que controla permisos (en producción con X-Accel-Redirect).
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class AlmacenamientoPrivado(FileSystemStorage):
    # La ubicación se lee de settings en cada uso (y no una sola vez al arrancar),
    # así respeta override_settings en los tests.
    @property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError("Los archivos privados no tienen URL pública; se sirven por una vista con permisos.")


def almacenamiento_privado() -> AlmacenamientoPrivado:
    """Callable para FileField(storage=...): evita fijar la ruta en las migraciones."""
    return AlmacenamientoPrivado()
