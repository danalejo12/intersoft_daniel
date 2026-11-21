"""Modelos de planes, suscripciones por empresa (tenant) e historial de auditoría.

Decisiones de diseño:
1. Dinero y porcentajes usan exclusivamente DecimalField y Decimal (nunca float)
   para evitar errores de representación en coma flotante binaria.
2. Los límites y funcionalidades (features) se almacenan como datos en JSONField
   para que cambiar las capacidades de un plan no requiera redesplegar código.
3. Un límite ilimitado se representa como null (None en Python), nunca con números mágicos.
"""
from django.utils.translation import gettext, gettext_lazy
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models.base import ModeloBase


class Plan(ModeloBase):
    """Catálogo de planes comerciales de Intersoft."""

    codigo = models.SlugField(gettext_lazy("código"), max_length=40, unique=True)
    nombre = models.CharField("nombre", max_length=80)
    precio_mensual = models.DecimalField(
        gettext_lazy("precio mensual (COP)"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    precio_anual = models.DecimalField(
        gettext_lazy("precio anual (COP)"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    comision_porcentaje = models.DecimalField(
        gettext_lazy("comisión marketplace (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    limites = models.JSONField(
        gettext_lazy("límites por recurso"),
        default=dict,
        blank=True,
        help_text=gettext_lazy('Diccionario de límites, ej. {"productos": 200, "usuarios": 2}. null significa ilimitado.'),
    )
    features = models.JSONField(
        gettext_lazy("funcionalidades habilitadas"),
        default=list,
        blank=True,
        help_text=gettext_lazy('Lista de códigos de funcionalidad, ej. ["marketplace", "pos", "inventario"].'),
    )
    orden = models.PositiveSmallIntegerField(gettext_lazy("orden de visualización"), default=0)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "plan"
        verbose_name_plural = "planes"
        ordering = ["orden", "precio_mensual"]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Suscripcion(ModeloBase):
    """Estado de suscripción vigente de una empresa (relación 1 a 1 con core.Empresa)."""

    class Estado(models.TextChoices):
        TRIAL = "TRIAL", gettext_lazy("Periodo de prueba")
        ACTIVA = "ACTIVA", gettext_lazy("Activa")
        VENCIDA = "VENCIDA", gettext_lazy("Vencida")
        CANCELADA = "CANCELADA", gettext_lazy("Cancelada")

    class Ciclo(models.TextChoices):
        MENSUAL = "MENSUAL", gettext_lazy("Mensual")
        ANUAL = "ANUAL", gettext_lazy("Anual")

    empresa = models.OneToOneField(
        "core.Empresa",
        on_delete=models.CASCADE,
        related_name="suscripcion",
        verbose_name="empresa",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="suscripciones",
        verbose_name="plan",
    )
    estado = models.CharField(
        "estado",
        max_length=15,
        choices=Estado.choices,
        default=Estado.TRIAL,
        db_index=True,
    )
    ciclo = models.CharField(
        gettext_lazy("ciclo de cobro"),
        max_length=10,
        choices=Ciclo.choices,
        default=Ciclo.MENSUAL,
    )
    inicia_en = models.DateTimeField(gettext_lazy("inicia en"), default=timezone.now)
    vence_en = models.DateTimeField(gettext_lazy("vence en"), null=True, blank=True, db_index=True)
    es_fundador = models.BooleanField(
        gettext_lazy("es empresa fundadora"),
        default=False,
        help_text=gettext_lazy("Las primeras 50 empresas con plan pago conservan 50% de descuento de por vida."),
    )
    descuento_porcentaje = models.DecimalField(
        gettext_lazy("descuento permanente (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )

    class Meta:
        verbose_name = gettext_lazy("suscripción")
        verbose_name_plural = "suscripciones"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.empresa} · {self.plan.nombre} ({self.estado})"

    def puede(self, feature: str) -> bool:
        """Indica si la suscripción está vigente y su plan (o FeatureFlag del negocio) incluye la funcionalidad."""
        if self.estado not in (self.Estado.TRIAL, self.Estado.ACTIVA):
            return False
        from django.db import OperationalError, ProgrammingError
        from plataforma.models import FeatureFlag

        try:
            flag = FeatureFlag.objects.filter(empresa_id=self.empresa_id, codigo=feature).only("habilitado").first()
            if flag is not None:
                return bool(flag.habilitado)
        except (OperationalError, ProgrammingError):
            pass
        features_plan = self.plan.features or []
        return feature in features_plan

    def dentro_del_limite(self, recurso: str, uso_actual: int) -> bool:
        """Verifica si un nivel de uso (uso_actual) cabe dentro del límite del plan para ese recurso.

        - Si el límite en JSON es null (None en Python) o el recurso no tiene tope definido, es ilimitado (True).
        - Si tiene un tope numérico, devuelve True cuando uso_actual <= limite.
        """
        limites_plan = self.plan.limites or {}
        limite = limites_plan.get(recurso)
        if limite is None:
            return True
        return int(uso_actual) <= int(limite)


class HistorialSuscripcion(ModeloBase):
    """Registro inmutable de auditoría para cada transición de plan o estado de una suscripción."""

    suscripcion = models.ForeignKey(
        Suscripcion,
        on_delete=models.CASCADE,
        related_name="historial",
        verbose_name=gettext_lazy("suscripción"),
    )
    plan_anterior = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=gettext_lazy("plan anterior"),
    )
    plan_nuevo = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=gettext_lazy("plan nuevo"),
    )
    estado_anterior = models.CharField(
        gettext_lazy("estado anterior"),
        max_length=15,
        choices=Suscripcion.Estado.choices,
        blank=True,
    )
    estado_nuevo = models.CharField(
        gettext_lazy("estado nuevo"),
        max_length=15,
        choices=Suscripcion.Estado.choices,
    )
    motivo = models.CharField("motivo", max_length=255, blank=True)
    fecha = models.DateTimeField(gettext_lazy("fecha del cambio"), default=timezone.now, db_index=True)

    class Meta:
        verbose_name = gettext_lazy("historial de suscripción")
        verbose_name_plural = gettext_lazy("historial de suscripciones")
        ordering = ["-fecha", "-creado_en"]

    def __str__(self):
        anterior = self.plan_anterior.codigo if self.plan_anterior else "ninguno"
        return f"{self.suscripcion.empresa} · {anterior} -> {self.plan_nuevo.codigo} ({self.estado_nuevo})"


class CobroSuscripcion(ModeloBase):
    """Un intento de pagar un plan con la cuenta de Wompi de Intersoft.

    El plan SOLO se activa cuando Wompi confirma el pago (consulta del servidor o webhook firmado):
    el navegador nunca decide. Monto, plan y ciclo quedan congelados al crear el cobro."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", gettext_lazy("Pendiente")
        APROBADO = "aprobado", gettext_lazy("Aprobado")
        RECHAZADO = "rechazado", gettext_lazy("Rechazado")
        ANULADO = "anulado", gettext_lazy("Anulado sin pago")
        REQUIERE_REVISION = "requiere_revision", gettext_lazy("Requiere revisión")

    empresa = models.ForeignKey("core.Empresa", on_delete=models.PROTECT, related_name="cobros_suscripcion")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="cobros")
    ciclo = models.CharField(max_length=10, choices=Suscripcion.Ciclo.choices)
    referencia = models.CharField(max_length=60, unique=True)
    precio_lista = models.DecimalField(max_digits=12, decimal_places=2)
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    moneda = models.CharField(max_length=3, default="COP")
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    transaccion_id = models.CharField(max_length=60, blank=True)
    metodo_pago = models.CharField(max_length=30, blank=True)
    detalle = models.CharField(gettext_lazy("detalle del resultado"), max_length=255, blank=True)
    creado_por = models.ForeignKey(
        "core.Usuario", on_delete=models.PROTECT, related_name="cobros_suscripcion", null=True, blank=True
    )
    resuelto_en = models.DateTimeField(null=True, blank=True)
    ultima_consulta_en = models.DateTimeField(null=True, blank=True)
    cupon = models.ForeignKey(
        "CuponPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cobros",
    )

    class Meta:
        verbose_name = gettext_lazy("cobro de suscripción")
        verbose_name_plural = gettext_lazy("cobros de suscripción")
        ordering = ["-creado_en"]
        constraints = [
            models.CheckConstraint(condition=models.Q(monto__gt=0), name="ck_cobro_suscripcion_monto_positivo"),
        ]
        indexes = [models.Index(fields=["empresa", "-creado_en"], name="ix_cobro_sus_empresa_fecha")]

    def __str__(self):
        return f"{self.referencia} · {self.empresa} · {self.plan.codigo} ({self.estado})"

    @property
    def monto_centavos(self) -> int:
        return int((self.monto * 100).to_integral_value())


class ConfiguracionSuscripciones(ModeloBase):
    """Parámetros globales de suscripciones editables desde /plataforma/."""

    clave_unica = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    cupos_fundador = models.PositiveIntegerField(
        gettext_lazy("cupos de fundador"),
        default=50,
        help_text=gettext_lazy("Cantidad máxima de empresas que pueden obtener el descuento permanente de fundador."),
    )

    class Meta:
        verbose_name = gettext_lazy("configuración de suscripciones")
        verbose_name_plural = gettext_lazy("configuraciones de suscripciones")

    def __str__(self):
        return gettext("Configuración de suscripciones (cupos fundador: {cupos_fundador})").format(cupos_fundador=self.cupos_fundador)

    @classmethod
    def obtener(cls):
        obj, _ = cls.objects.get_or_create(clave_unica=1, defaults={"cupos_fundador": 50})
        return obj

    @classmethod
    def obtener_cupos_fundador(cls, defecto: int = 50) -> int:
        from django.db import OperationalError, ProgrammingError

        try:
            obj = cls.objects.filter(clave_unica=1).only("cupos_fundador").first()
            return obj.cupos_fundador if obj is not None else defecto
        except (OperationalError, ProgrammingError):
            return defecto


class CuponPlan(ModeloBase):
    """Cupón de descuento aplicable al pago de planes de suscripción."""

    class Tipo(models.TextChoices):
        PORCENTAJE = "porcentaje", gettext_lazy("Porcentaje (%)")
        VALOR_FIJO = "valor_fijo", gettext_lazy("Valor fijo (COP)")

    codigo = models.CharField(gettext_lazy("código"), max_length=40, unique=True)
    tipo = models.CharField(gettext_lazy("tipo de descuento"), max_length=15, choices=Tipo.choices, default=Tipo.PORCENTAJE)
    valor = models.DecimalField(
        "valor",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    inicia_en = models.DateTimeField(gettext_lazy("vigente desde"), default=timezone.now)
    vence_en = models.DateTimeField(gettext_lazy("vigente hasta"), null=True, blank=True)
    usos_maximos = models.PositiveIntegerField(gettext_lazy("usos máximos"), null=True, blank=True)
    usos_actuales = models.PositiveIntegerField(gettext_lazy("usos actuales"), default=0)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = gettext_lazy("cupón de plan")
        verbose_name_plural = gettext_lazy("cupones de planes")
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.codigo} ({self.get_tipo_display()}: {self.valor})"

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or "").strip().upper()
        super().save(*args, **kwargs)

    def esta_vigente(self, ahora=None) -> bool:
        ahora = ahora or timezone.now()
        if not self.activo:
            return False
        if self.inicia_en and ahora < self.inicia_en:
            return False
        if self.vence_en and ahora > self.vence_en:
            return False
        if self.usos_maximos is not None and self.usos_actuales >= self.usos_maximos:
            return False
        return True


class RecordatorioVencimiento(ModeloBase):
    """Registro idempotente de recordatorios de vencimiento enviados por correo (7, 3 y 1 día)."""

    suscripcion = models.ForeignKey(
        Suscripcion,
        on_delete=models.CASCADE,
        related_name="recordatorios",
    )
    dias_antes = models.PositiveSmallIntegerField(gettext_lazy("días antes del vencimiento"))
    fecha_objetivo = models.DateField(gettext_lazy("fecha de vencimiento objetivo"))

    class Meta:
        verbose_name = gettext_lazy("recordatorio de vencimiento")
        verbose_name_plural = gettext_lazy("recordatorios de vencimiento")
        constraints = [
            models.UniqueConstraint(
                fields=["suscripcion", "dias_antes", "fecha_objetivo"],
                name="uq_recordatorio_suscripcion_dia_fecha",
            ),
        ]


