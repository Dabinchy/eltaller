"""
Producción (Raspberry Pi con Debian 13): se activa con DJANGO_ENV=prod en el archivo .env.

Todo lo que cambia entre equipos sale del archivo .env (en la carpeta del proyecto, no se sube a git):
- DJANGO_SECRET_KEY (obligatoria), DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS.
- POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT.

Detrás hay: Cloudflare (HTTPS y dominio) → túnel cloudflared → nginx (estáticos, fotos y archivos
privados) → gunicorn → Django.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import BASE_DIR


def _env(nombre: str, *, obligatoria: bool = False, defecto: str = "") -> str:
    valor = os.environ.get(nombre, defecto).strip()
    if obligatoria and not valor:
        raise ImproperlyConfigured(f"Falta {nombre} en el archivo .env de la carpeta del proyecto.")
    return valor


def _env_bool(nombre: str, defecto: bool) -> bool:
    return _env(nombre, defecto="1" if defecto else "0").lower() in ("1", "true", "si", "sí", "yes")


DEBUG = False

SECRET_KEY = _env("DJANGO_SECRET_KEY", obligatoria=True)
if SECRET_KEY.startswith("inseguro") or len(SECRET_KEY) < 40:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY tiene que ser larga y aleatoria: "
                               "python3 -c \"import secrets; print(secrets.token_urlsafe(50))\"")

# ALLOWED_HOSTS y CSRF_TRUSTED_ORIGINS se leen del .env en base.py.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _env("POSTGRES_DB", obligatoria=True),
        "USER": _env("POSTGRES_USER", obligatoria=True),
        "PASSWORD": _env("POSTGRES_PASSWORD"),
        "HOST": _env("POSTGRES_HOST", defecto="127.0.0.1"),
        "PORT": _env("POSTGRES_PORT", defecto="5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

# Archivos: nginx sirve /static/ y /media/; los privados los entrega nginx (X-Accel-Redirect)
# sólo después de que Django controla los permisos.
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = BASE_DIR / "media"
PRIVATE_MEDIA_ROOT = BASE_DIR / "privado"
PRIVATE_X_ACCEL_PREFIX = _env("PRIVATE_X_ACCEL_PREFIX", defecto="/_privado/")

# HTTPS lo pone Cloudflare; nginx avisa con X-Forwarded-Proto. La redirección a https también
# la hace Cloudflare ("Always Use HTTPS"), así que acá no se redirige (la red local entra por http).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = _env_bool("DJANGO_COOKIES_SEGURAS", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_HSTS_SECONDS = int(_env("DJANGO_HSTS_SEGUNDOS", defecto="0"))   # activar cuando todo ande (ver LEEME)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Errores al registro del sistema (journalctl -u eltaller).
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {name}: {message}", "style": "{"}},
    "handlers": {"consola": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["consola"], "level": "WARNING"},
    "loggers": {"django.request": {"handlers": ["consola"], "level": "ERROR", "propagate": False}},
}
