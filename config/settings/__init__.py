import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

DJANGO_ENV = os.environ.get("DJANGO_ENV", "dev").lower()

if DJANGO_ENV == "prod":
    from .prod import *  # noqa  (prod.py lo creamos al desplegar)
else:
    from .dev import *  # noqa

    