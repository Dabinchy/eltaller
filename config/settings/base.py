import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "inseguro-solo-para-desarrollo")
DEBUG = False

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Librerías
    "widget_tweaks",
    "crispy_forms",
    "crispy_bootstrap5",
    "django_filters",
    # Apps del proyecto
    "core",
    "productos",
    "clientes",
    "ventas",
    "compras",
    "taller",
    "portal",
    "campeonatos",
    "sitio",
    "panel",

]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.empresa",
                "core.context_processors.menu",
            ],
        },
    },
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Archivos privados (facturas, archivos internos): fuera de MEDIA_ROOT y sin URL pública.
PRIVATE_MEDIA_ROOT = BASE_DIR / "privado"
# En producción nginx entrega los archivos privados (X-Accel-Redirect) después de que Django
# verifica los permisos. Ej.: "/_privado/" (location internal en nginx). Vacío = los sirve Django.
PRIVATE_X_ACCEL_PREFIX = os.environ.get("PRIVATE_X_ACCEL_PREFIX", "")

# Ingreso único: cada uno va a su lugar según su tipo de usuario.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "redireccion"
LOGOUT_REDIRECT_URL = "sitio:inicio"

# Marcas (se pueden cambiar sin tocar templates). Siempre se usan éstas, aunque Empresa tenga logo.
TALLER_MARCA_NOMBRE = "El Taller"
TALLER_MARCA_LOGO = "img/brand/el-taller.jpg"
PORTAL_MARCA_NOMBRE = "El Prepa"
PORTAL_MARCA_LOGO = "img/brand/el-prepa.jpg"

SECURE_CONTENT_TYPE_NOSNIFF = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.Usuario"

# Caché en base de datos: compartida entre los procesos de gunicorn (límite de registros por IP).
# Requiere una vez: python manage.py createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache_django",
    }
}

# Portal de pilotos
PORTAL_CUOTA_MB_POR_DEFECTO = 500   # si la asociación no define cuota
PORTAL_EDAD_MAYORIA = 18            # menores necesitan consentimiento del tutor para publicar
PORTAL_REGISTROS_POR_IP_HORA = 3    # anti-spam en el registro
