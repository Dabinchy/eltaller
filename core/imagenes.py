"""
Procesamiento de imágenes subidas por usuarios (fotos de perfil, galería de autos).

- Verifica que el archivo sea realmente una imagen (no sólo que tenga extensión .jpg).
- Rechaza imágenes gigantes en píxeles (protección contra "bombas" de descompresión).
- Endereza según la orientación EXIF y DESCARTA todos los metadatos (incluida la ubicación GPS).
- Achica a un máximo de MAX_LADO px y genera una miniatura de MINI_LADO px.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_LADO = 2000
MINI_LADO = 400
MAX_PIXELES = 40_000_000  # ~ 7000 x 5700
MAX_MB = 15
EXTENSIONES = ["jpg", "jpeg", "png", "webp"]
_FORMATOS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def validar_tamano(archivo) -> None:
    if archivo and archivo.size > MAX_MB * 1024 * 1024:
        raise ValidationError(f"La imagen no puede superar {MAX_MB} MB.")


def _guardar(img: Image.Image, formato: str) -> bytes:
    salida = BytesIO()
    opciones = {"optimize": True}
    if formato in ("JPEG", "WEBP"):
        opciones["quality"] = 85
    img.save(salida, format=formato, **opciones)  # sin exif=... → se guarda sin metadatos
    return salida.getvalue()


def procesar_imagen(archivo, nombre_base: str) -> tuple[ContentFile, ContentFile]:
    """
    Devuelve (imagen, miniatura) limpias y achicadas, listas para asignar a un ImageField.
    Lanza ValidationError si el archivo no es una imagen válida.
    """
    validar_tamano(archivo)
    try:
        archivo.seek(0)
        with Image.open(archivo) as prueba:
            prueba.verify()  # detecta archivos corruptos o falsos
            if prueba.width * prueba.height > MAX_PIXELES:
                raise ValidationError("La imagen tiene demasiados píxeles.")
        archivo.seek(0)
        img = Image.open(archivo)
        formato = img.format
        img.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValidationError("El archivo no es una imagen válida.") from e

    if formato not in _FORMATOS:
        raise ValidationError("Formato no permitido. Usá JPG, PNG o WEBP.")

    img = ImageOps.exif_transpose(img)  # aplica la rotación antes de descartar el EXIF
    if formato == "JPEG" and img.mode != "RGB":
        img = img.convert("RGB")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    ext = _FORMATOS[formato]
    base = Path(nombre_base).stem or "imagen"

    grande = img.copy()
    grande.thumbnail((MAX_LADO, MAX_LADO))
    mini = img.copy()
    mini.thumbnail((MINI_LADO, MINI_LADO))

    return (
        ContentFile(_guardar(grande, formato), name=f"{base}.{ext}"),
        ContentFile(_guardar(mini, formato), name=f"{base}_mini.{ext}"),
    )
