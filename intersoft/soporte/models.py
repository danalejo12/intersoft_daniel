"""Modelos de errores automáticos, reportes de usuarios, comentarios, NPS e ideas."""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models.base import ModeloBase

EXTENSIONES_CAPTURA = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_BYTES_CAPTURA = 5 * 1024 * 1024


def validar_captura_soporte(archivo):
    """Valida que la captura sea una imagen permitida de máximo 5 MB."""
    if not archivo:
        return
    ext = os.path.splitext(getattr(archivo, "name", "") or "")[1].lower()
    if ext not in EXTENSIONES_CAPTURA:
        raise ValidationError("Formato no permitido. Sube una imagen (JPG, PNG, WEBP o GIF).")
    if archivo.size > MAX_BYTES_CAPTURA:
        raise ValidationError("La captura supera el máximo permitido de 5 MB.")


class ErrorRegistrado(ModeloBase):
    """Error 500 capturado automáticamente y agrupado por huella."""

    class Estado(models.TextChoices):
        """Valores posibles de estado de error registrado: «Nuevo», «Investigando», «Resuelto», «Ignorado»."""
        NUEVO = "nuevo", "Nuevo"
        INVESTIGANDO = "investigando", "Investigando"
        RESUELTO = "resuelto", "Resuelto"
        IGNORADO = "ignorado", "Ignorado"

    huella = models.CharField("huella", max_length=64, unique=True)
    tipo_excepcion = models.CharField("tipo de excepción", max_length=120, db_index=True)
    mensaje = models.TextField("mensaje", blank=True)
    archivo = models.CharField("archivo", max_length=255, blank=True)
    linea = models.PositiveIntegerField("línea", default=0)
    traza = models.TextField("traza sanitizada", blank=True)
    url = models.CharField("URL", max_length=500, blank=True)
    metodo = models.CharField("método HTTP", max_length=12, blank=True)
    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="errores_registrados",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="errores_registrados",
    )
    contador = models.PositiveIntegerField("ocurrencias", default=1)
    primera_vez = models.DateTimeField("primera vez", default=timezone.now, db_index=True)
    ultima_vez = models.DateTimeField("última vez", default=timezone.now, db_index=True)
    estado = models.CharField(
        "estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.NUEVO,
        db_index=True,
    )
    notas_internas = models.TextField("notas internas", blank=True)

    class Meta:
        verbose_name = "error registrado"
        verbose_name_plural = "errores registrados"
        ordering = ["-ultima_vez"]

    def __str__(self):
        return f"{self.tipo_excepcion} ({self.archivo}:{self.linea}) × {self.contador}"


class ReporteProblema(ModeloBase):
    """Reporte manual enviado desde el panel con contexto automático del navegador y empresa."""

    class Estado(models.TextChoices):
        """Valores posibles de estado de reporte de problema: «Nuevo», «En revisión», «Resuelto»."""
        NUEVO = "nuevo", "Nuevo"
        EN_REVISION = "en_revision", "En revisión"
        RESUELTO = "resuelto", "Resuelto"

    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reportes_problema",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reportes_problema",
    )
    url = models.CharField("URL de origen", max_length=500, blank=True)
    navegador = models.CharField("navegador", max_length=300, blank=True)
    fecha_reporte = models.DateTimeField("hora del reporte", default=timezone.now)
    descripcion = models.TextField("descripción del problema")
    captura = models.FileField(
        "captura de pantalla",
        upload_to="soporte/capturas/%Y/%m/",
        blank=True,
        null=True,
        validators=[validar_captura_soporte],
    )
    estado = models.CharField(
        "estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.NUEVO,
        db_index=True,
    )

    class Meta:
        verbose_name = "reporte de problema"
        verbose_name_plural = "reportes de problemas"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"Reporte {self.usuario or 'anónimo'} · {self.url[:60]}"


class ComentarioWidget(ModeloBase):
    """Retroalimentación rápida (pulgar arriba/abajo + comentario opcional) por pantalla."""

    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comentarios_widget",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comentarios_widget",
    )
    util = models.BooleanField("¿fue útil?")
    comentario = models.TextField("comentario opcional", blank=True)
    pantalla = models.CharField("pantalla de origen", max_length=500, blank=True)

    class Meta:
        verbose_name = "comentario rápido"
        verbose_name_plural = "comentarios rápidos"
        ordering = ["-creado_en"]

    def __str__(self):
        marca = "👍" if self.util else "👎"
        return f"{marca} {self.pantalla}"


class EncuestaNPS(ModeloBase):
    """Encuesta Net Promoter Score (0 a 10), máximo una cada 90 días por usuario."""

    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="encuestas_nps",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="encuestas_nps",
    )
    puntaje = models.PositiveSmallIntegerField(
        "puntaje NPS",
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    comentario = models.TextField("comentario opcional", blank=True)
    pantalla = models.CharField("pantalla de origen", max_length=500, blank=True)

    class Meta:
        verbose_name = "encuesta NPS"
        verbose_name_plural = "encuestas NPS"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"NPS {self.puntaje} · {self.usuario}"


class Idea(ModeloBase):
    """Propuesta de mejora enviada por un negocio y votada por otros usuarios."""

    class Estado(models.TextChoices):
        """Valores posibles de estado de idea: «En evaluación», «Planeada», «Lanzada», «Descartada»."""
        EN_EVALUACION = "en_evaluacion", "En evaluación"
        PLANEADA = "planeada", "Planeada"
        LANZADA = "lanzada", "Lanzada"
        DESCARTADA = "descartada", "Descartada"

    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ideas_propuestas",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ideas_propuestas",
    )
    titulo = models.CharField("título", max_length=160)
    descripcion = models.TextField("descripción")
    estado = models.CharField(
        "estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.EN_EVALUACION,
        db_index=True,
    )

    class Meta:
        verbose_name = "idea"
        verbose_name_plural = "ideas"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.titulo} ({self.get_estado_display()})"


class VotoIdea(ModeloBase):
    """Voto único de un usuario sobre una idea."""

    idea = models.ForeignKey(Idea, on_delete=models.CASCADE, related_name="votos")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="votos_ideas",
    )

    class Meta:
        verbose_name = "voto de idea"
        verbose_name_plural = "votos de ideas"
        constraints = [
            models.UniqueConstraint(fields=["idea", "usuario"], name="uq_voto_idea_usuario"),
        ]
