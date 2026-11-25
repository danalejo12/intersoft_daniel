"""Validación de archivos por firma binaria (magic bytes) y sanitización de imágenes sin metadatos EXIF."""
import io
import os

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXTENSIONES_PDF = {".pdf"}

FORMATOS_PIL_POR_EXT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".gif": "GIF",
}


def _leer_cabecera(archivo, n: int = 16) -> bytes:
    """Lee los primeros n bytes de un archivo subido restaurando el puntero al inicio."""
    pos = archivo.tell() if hasattr(archivo, "tell") else 0
    try:
        if hasattr(archivo, "seek"):
            archivo.seek(0)
        return archivo.read(n) or b""
    finally:
        if hasattr(archivo, "seek"):
            archivo.seek(pos)


def _firma_imagen_valida(cabecera: bytes) -> bool:
    """Comprueba magic bytes reales para JPEG, PNG, WEBP o GIF."""
    if cabecera.startswith(b"\xff\xd8\xff"):
        return True
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if cabecera.startswith((b"GIF87a", b"GIF89a")):
        return True
    if len(cabecera) >= 12 and cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return True
    return False


def validar_firma_archivo(archivo, *, permitir_pdf: bool = False, max_bytes: int = 5 * 1024 * 1024) -> None:
    """Valida extensión, tamaño y firma binaria real (magic bytes + Pillow) contra archivos falsificados."""
    if not archivo:
        return
    nombre = getattr(archivo, "name", "") or ""
    ext = os.path.splitext(nombre)[1].lower()
    permitidas = EXTENSIONES_IMAGEN | (EXTENSIONES_PDF if permitir_pdf else set())
    if ext not in permitidas:
        if permitir_pdf:
            raise ValidationError("Formato de archivo no permitido. Usa imágenes (JPG, PNG, WEBP, GIF) o PDF.")
        raise ValidationError("Formato no permitido. Sube una imagen válida (JPG, PNG, WEBP o GIF).")
    if getattr(archivo, "size", 0) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise ValidationError(f"El archivo supera el tamaño máximo permitido de {mb} MB.")

    cabecera = _leer_cabecera(archivo, 16)
    if ext == ".pdf":
        if not cabecera.startswith(b"%PDF-"):
            raise ValidationError("El archivo no es un PDF válido (firma binaria incorrecta).")
        return

    if not _firma_imagen_valida(cabecera):
        raise ValidationError("El archivo no corresponde a una imagen real válida.")

    pos = archivo.tell() if hasattr(archivo, "tell") else 0
    try:
        if hasattr(archivo, "seek"):
            archivo.seek(0)
        with Image.open(archivo) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("La imagen está dañada o no es válida.") from exc
    finally:
        if hasattr(archivo, "seek"):
            archivo.seek(pos)


def sanitizar_imagen(archivo, *, max_lado: int = 2000):
    """Recodifica una imagen con Pillow eliminando metadatos EXIF/GPS y normalizando su orientación."""
    if not archivo:
        return archivo
    nombre = getattr(archivo, "name", "") or "imagen.jpg"
    ext = os.path.splitext(nombre)[1].lower()
    formato = FORMATOS_PIL_POR_EXT.get(ext)
    if not formato or formato == "GIF":
        return archivo

    pos = archivo.tell() if hasattr(archivo, "tell") else 0
    try:
        if hasattr(archivo, "seek"):
            archivo.seek(0)
        with Image.open(archivo) as original:
            limpia = ImageOps.exif_transpose(original)
            if limpia.width > max_lado or limpia.height > max_lado:
                limpia.thumbnail((max_lado, max_lado), Image.Resampling.LANCZOS)
            if formato == "JPEG" and limpia.mode not in ("RGB", "L"):
                limpia = limpia.convert("RGB")
            salida = io.BytesIO()
            kwargs = {"quality": 88, "optimize": True} if formato in ("JPEG", "WEBP") else {"optimize": True}
            limpia.save(salida, format=formato, **kwargs)
    finally:
        if hasattr(archivo, "seek"):
            archivo.seek(pos)

    salida.seek(0)
    content_type = f"image/{'jpeg' if formato == 'JPEG' else formato.lower()}"
    return InMemoryUploadedFile(
        file=salida,
        field_name=getattr(archivo, "field_name", None),
        name=os.path.basename(nombre),
        content_type=content_type,
        size=salida.getbuffer().nbytes,
        charset=None,
    )
