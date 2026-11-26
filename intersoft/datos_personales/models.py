"""Modelos de protección de datos personales: prueba de la autorización y solicitudes del titular."""
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from core.models.base import ModeloBase


class AutorizacionDatos(ModeloBase):
    """Prueba de la autorización previa, expresa e informada del titular (Ley 1581 art. 9; Decreto 1377 art. 7-8).

    Se guarda qué versión de la política aceptó, cuándo, desde dónde y por qué medio. Nunca se borra: si el titular
    revoca, se marca la fecha de revocatoria y la fila queda como prueba de lo que autorizó en su momento."""

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="autorizaciones_datos")
    version_politica = models.CharField("versión de la política", max_length=40)
    finalidades = models.JSONField("finalidades aceptadas", default=list)
    medio = models.CharField("medio", max_length=40, help_text="registro, aceptación en el panel, etc.")
    ip = models.GenericIPAddressField("IP", null=True, blank=True)
    navegador = models.CharField("navegador", max_length=300, blank=True)
    mayor_de_edad = models.BooleanField("declaró ser mayor de edad", default=False)
    aceptada_en = models.DateTimeField("aceptada en", default=timezone.now)
    revocada_en = models.DateTimeField("revocada en", null=True, blank=True)

    class Meta:
        verbose_name = "autorización de tratamiento de datos"
        verbose_name_plural = "autorizaciones de tratamiento de datos"
        ordering = ["-aceptada_en"]

    def __str__(self):
        estado = "revocada" if self.revocada_en else "vigente"
        return f"{self.usuario} · política {self.version_politica} · {estado}"


class SecuenciaSolicitudDatos(ModeloBase):
    """Consecutivo anual de radicados de solicitudes de datos personales (HD-AAAA-00001)."""

    anio = models.PositiveSmallIntegerField(unique=True)
    ultimo = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "secuencia de radicados de datos personales"
        verbose_name_plural = "secuencias de radicados de datos personales"


def generar_radicado(anio=None) -> str:
    """Radicado único y consecutivo por año; seguro ante peticiones simultáneas."""
    anio = anio or timezone.localdate().year
    with transaction.atomic():
        secuencia, _ = SecuenciaSolicitudDatos.objects.select_for_update().get_or_create(anio=anio)
        secuencia.ultimo += 1
        secuencia.save(update_fields=["ultimo", "actualizado_en"])
        return f"HD-{anio}-{secuencia.ultimo:05d}"


class SolicitudDatos(ModeloBase):
    """Solicitud del titular sobre sus datos (consulta o reclamo), con radicado y plazo legal.

    Consultas (conocer, prueba de autorización): 10 días hábiles, prorrogables 5 (Ley 1581 art. 14).
    Reclamos (actualizar, rectificar, revocar, suprimir): 15 días hábiles, prorrogables 8 (art. 15)."""

    class Tipo(models.TextChoices):
        CONOCER = "conocer", "Conocer qué datos tienen de mí"
        PRUEBA = "prueba", "Prueba de la autorización que di"
        ACTUALIZAR = "actualizar", "Actualizar mis datos"
        RECTIFICAR = "rectificar", "Corregir datos inexactos"
        REVOCAR = "revocar", "Revocar la autorización"
        SUPRIMIR = "suprimir", "Suprimir (eliminar) mis datos"

    class Estado(models.TextChoices):
        RADICADA = "radicada", "Radicada"
        EN_TRAMITE = "en_tramite", "En trámite"
        RESPONDIDA = "respondida", "Respondida"
        RECHAZADA = "rechazada", "Rechazada (con motivo)"

    CONSULTAS = {Tipo.CONOCER, Tipo.PRUEBA}

    radicado = models.CharField(max_length=20, unique=True, editable=False)
    titular = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes_datos")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    detalle = models.TextField("detalle de la solicitud", max_length=2000, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.RADICADA, db_index=True)
    fecha_limite = models.DateTimeField("fecha límite de respuesta", db_index=True)
    respuesta = models.TextField("respuesta al titular", blank=True, max_length=4000)
    atendida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    respondida_en = models.DateTimeField(null=True, blank=True)
    datos_suprimidos_en = models.DateTimeField("datos suprimidos en", null=True, blank=True)

    class Meta:
        verbose_name = "solicitud sobre datos personales"
        verbose_name_plural = "solicitudes sobre datos personales"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.radicado} · {self.get_tipo_display()}"

    @property
    def es_consulta(self) -> bool:
        """Consulta (art. 14) o reclamo (art. 15): define el plazo legal de respuesta."""
        return self.tipo in self.CONSULTAS

    @property
    def vencida(self) -> bool:
        """Indica si pasó el plazo legal sin respuesta."""
        return self.estado in (self.Estado.RADICADA, self.Estado.EN_TRAMITE) and timezone.now() > self.fecha_limite
