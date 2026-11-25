"""Pruebas de seguridad de archivos: validación por magic bytes y eliminación de metadatos EXIF."""
import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from core.archivos_seguros import sanitizar_imagen, validar_firma_archivo
from pqrs.models import validar_archivo_pqrs
from soporte.models import validar_captura_soporte


def _jpeg_con_exif() -> SimpleUploadedFile:
    """Crea un JPEG válido en memoria con metadatos EXIF (cámara/software) incrustados."""
    img = Image.new("RGB", (120, 90), color=(37, 99, 235))
    exif = img.getexif()
    exif[271] = "CameraCorp"
    exif[272] = "SecretPhone 99"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return SimpleUploadedFile("foto.jpg", buf.getvalue(), content_type="image/jpeg")


class ArchivosSegurosTests(SimpleTestCase):
    """Valida firma binaria (magic bytes), rechazo de archivos falsificados y limpieza de EXIF."""

    def test_rechaza_script_renombrado_como_imagen_o_pdf(self):
        """Un archivo PHP/HTML renombrado a .jpg o .pdf debe ser rechazado por magic bytes."""
        falso_jpg = SimpleUploadedFile("exploit.jpg", b"<?php system($_GET['c']); ?>", content_type="image/jpeg")
        falso_pdf = SimpleUploadedFile("trampa.pdf", b"<script>alert(1)</script>", content_type="application/pdf")

        with self.assertRaises(ValidationError):
            validar_archivo_pqrs(falso_jpg)
        with self.assertRaises(ValidationError):
            validar_archivo_pqrs(falso_pdf)
        with self.assertRaises(ValidationError):
            validar_captura_soporte(falso_jpg)

    def test_pdf_valido_permitido_en_pqrs_y_bloqueado_en_soporte(self):
        """Un PDF con firma %PDF- pasa en PQRS pero se rechaza en capturas de soporte."""
        pdf_real = SimpleUploadedFile("soporte.pdf", b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF", content_type="application/pdf")
        validar_archivo_pqrs(pdf_real)
        with self.assertRaises(ValidationError):
            validar_captura_soporte(pdf_real)

    def test_sanitizar_imagen_elimina_metadatos_exif_y_conserva_imagen_valida(self):
        """Recodificar con Pillow elimina EXIF (cámara/GPS) y produce un JPEG limpio."""
        original = _jpeg_con_exif()
        validar_firma_archivo(original)
        limpia = sanitizar_imagen(original)

        with Image.open(limpia) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (120, 90))
            self.assertEqual(len(img.getexif()), 0)
