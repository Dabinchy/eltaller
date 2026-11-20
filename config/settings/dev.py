import os

from .base import *  # noqa

DEBUG = True

# Si .env tiene POSTGRES_DB usa PostgreSQL; si no, usa SQLite.
if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
# Base de demostración aparte, para mostrar el sistema sin tocar los datos reales.
# Se activa con la variable de entorno DJANGO_DEMO=1 (ver demo/LEEME.md):
# usa demo.sqlite3 y sus propias carpetas de archivos (media_demo/ y privado_demo/).
DEMO = bool(os.environ.get("DJANGO_DEMO"))
if DEMO:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "demo.sqlite3"}}
    MEDIA_ROOT = BASE_DIR / "media_demo"
    PRIVATE_MEDIA_ROOT = BASE_DIR / "privado_demo"
