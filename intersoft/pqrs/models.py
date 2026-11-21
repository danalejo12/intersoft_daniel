"""Modelos del módulo de PQRS (Peticiones, Quejas, Reclamos y Sugerencias)."""
from django.utils.translation import gettext, gettext_lazy
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from core.models.base import ModeloBase

from .dias_habiles import semaforo_pqrs, sumar_dias_habiles

EXTENSIONES_PERMITIDAS_PQRS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}
MAX_BYTES_ADJUNTO_PQRS = 5 * 1024 * 1024  # 5 MB


def validar_archivo_pqrs(archivo):
    """Valida que el adjunto sea imagen o PDF y no supere 5 MB."""
    if not archivo:
        return
    nombre = getattr(archivo, "name", "") or ""
    ext = os.path.splitext(nombre)[1].lower()
    if ext not in EXTENSIONES_PERMITIDAS_PQRS:
        raise ValidationError(
            gettext("Formato de archivo no permitido. Usa imágenes (JPG, PNG, WEBP, GIF) o PDF.")
        )
    if archivo.size > MAX_BYTES_ADJUNTO_PQRS:
        raise ValidationError(gettext("El archivo supera el tamaño máximo permitido de 5 MB."))


class SecuenciaRadicadoPQRS(ModeloBase):
    """Consecutivo anual para generar radicados únicos PQRS-AAAA-00001."""

    anio = models.PositiveSmallIntegerField(gettext_lazy("año"), unique=True)
    ultimo_consecutivo = models.PositiveIntegerField(gettext_lazy("último consecutivo"), default=0)

    class Meta:
        verbose_name = gettext_lazy("secuencia de radicado PQRS")
        verbose_name_plural = gettext_lazy("secuencias de radicado PQRS")

    def __str__(self):
        return f"{self.anio}: {self.ultimo_consecutivo}"


def generar_radicado(anio: int | None = None) -> str:
    """Genera un radicado único PQRS-AAAA-00001 bloqueando el consecutivo con select_for_update()."""
    anio = anio or timezone.localdate().year
    with transaction.atomic():
        seq = SecuenciaRadicadoPQRS.objects.select_for_update().filter(anio=anio).first()
        if seq is None:
            try:
                with transaction.atomic():
                    seq = SecuenciaRadicadoPQRS.objects.create(anio=anio, ultimo_consecutivo=0)
            except IntegrityError:
                pass
            seq = SecuenciaRadicadoPQRS.objects.select_for_update().get(anio=anio)
        seq.ultimo_consecutivo += 1
        seq.save(update_fields=["ultimo_consecutivo", "actualizado_en"])
        return f"PQRS-{anio}-{seq.ultimo_consecutivo:05d}"


class PQRS(ModeloBase):
    """Solicitud PQRS en flujo A (Negocio -> Intersoft) o flujo B (Comprador -> Negocio)."""

    class Tipo(models.TextChoices):
        PETICION = "peticion", gettext_lazy("Petición")
        QUEJA = "queja", gettext_lazy("Queja")
        RECLAMO = "reclamo", gettext_lazy("Reclamo")
        SUGERENCIA = "sugerencia", gettext_lazy("Sugerencia")

    class Flujo(models.TextChoices):
        NEGOCIO_INTERSOFT = "A", gettext_lazy("Negocio → Intersoft")
        COMPRADOR_NEGOCIO = "B", gettext_lazy("Comprador → Negocio")

    class Estado(models.TextChoices):
        RADICADA = "radicada", gettext_lazy("Radicada")
        EN_TRAMITE = "en_tramite", gettext_lazy("En trámite")
        RESPONDIDA = "respondida", gettext_lazy("Respondida")
        CERRADA = "cerrada", gettext_lazy("Cerrada")
        ESCALADA = "escalada", gettext_lazy("Escalada a Intersoft")

    class Prioridad(models.TextChoices):
        BAJA = "baja", gettext_lazy("Baja")
        MEDIA = "media", gettext_lazy("Media")
        ALTA = "alta", gettext_lazy("Alta")
        URGENTE = "urgente", gettext_lazy("Urgente")

    radicado = models.CharField("radicado", max_length=24, unique=True, editable=False)
    tipo = models.CharField("tipo", max_length=20, choices=Tipo.choices)
    flujo = models.CharField("flujo", max_length=1, choices=Flujo.choices, db_index=True)
    empresa = models.ForeignKey(
        "core.Empresa",
        on_delete=models.PROTECT,
        related_name="pqrs",
        null=True,
        blank=True,
        verbose_name="negocio",
    )
    pedido = models.ForeignKey(
        "core.Pedido",
        on_delete=models.PROTECT,
        related_name="pqrs",
        null=True,
        blank=True,
        verbose_name="pedido",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="pqrs_radicadas",
        verbose_name="autor",
    )
    asunto = models.CharField("asunto", max_length=160)
    descripcion = models.TextField(gettext_lazy("descripción"))
    adjunto = models.FileField(
        "adjunto",
        upload_to="pqrs/adjuntos/%Y/%m/",
        blank=True,
        null=True,
        validators=[validar_archivo_pqrs],
    )
    estado = models.CharField(
        "estado",
        max_length=20,
        choices=Estado.choices,
        default=Estado.RADICADA,
        db_index=True,
    )
    prioridad = models.CharField(
        "prioridad",
        max_length=15,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
    )
    asignado_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pqrs_asignadas",
        verbose_name=gettext_lazy("asignado a"),
    )
    fecha_limite = models.DateTimeField(gettext_lazy("fecha límite de respuesta"), db_index=True)
    escalada_en = models.DateTimeField(gettext_lazy("escalada en"), null=True, blank=True)
    respondida_en = models.DateTimeField(gettext_lazy("respondida en"), null=True, blank=True)
    cerrada_en = models.DateTimeField(gettext_lazy("cerrada en"), null=True, blank=True)
    calificacion = models.PositiveSmallIntegerField(
        gettext_lazy("calificación de satisfacción"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comentario_satisfaccion = models.CharField(
        gettext_lazy("comentario de satisfacción"),
        max_length=255,
        blank=True,
    )

    class Meta:
        verbose_name = gettext_lazy("PQRS")
        verbose_name_plural = gettext_lazy("PQRS")
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["empresa", "estado", "-creado_en"], name="ix_pqrs_emp_est_fec"),
            models.Index(fields=["flujo", "estado", "fecha_limite"], name="ix_pqrs_flujo_lim"),
        ]

    def __str__(self):
        return f"{self.radicado} · {self.asunto}"

    def save(self, *args, **kwargs):
        if not self.radicado:
            self.radicado = generar_radicado()
        if not self.fecha_limite:
            dias = getattr(settings, "PQRS_DIAS_RESPUESTA", 15)
            self.fecha_limite = sumar_dias_habiles(timezone.now(), dias)
        super().save(*args, **kwargs)

    @property
    def semaforo(self) -> str:
        return semaforo_pqrs(self)


class MensajePQRS(ModeloBase):
    """Hilo de conversación asociado a una PQRS; soporta notas internas ocultas al ciudadano."""

    pqrs = models.ForeignKey(
        PQRS,
        on_delete=models.CASCADE,
        related_name="mensajes",
        verbose_name=gettext_lazy("PQRS"),
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="mensajes_pqrs",
        verbose_name="autor",
    )
    texto = models.TextField("mensaje")
    adjunto = models.FileField(
        "adjunto",
        upload_to="pqrs/mensajes/%Y/%m/",
        blank=True,
        null=True,
        validators=[validar_archivo_pqrs],
    )
    interno = models.BooleanField(gettext_lazy("nota interna"), default=False)

    class Meta:
        verbose_name = gettext_lazy("mensaje de PQRS")
        verbose_name_plural = gettext_lazy("mensajes de PQRS")
        ordering = ["creado_en"]

    def __str__(self):
        marca = gettext(" [Interna]") if self.interno else ""
        return f"{self.pqrs.radicado} · {self.autor}{marca}"
