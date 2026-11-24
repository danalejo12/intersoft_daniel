"""Modelos de planes, suscripciones por empresa (tenant) e historial de auditoría.

Decisiones de diseño:
1. Dinero y porcentajes usan exclusivamente DecimalField y Decimal (nunca float)
   para evitar errores de representación en coma flotante binaria.
2. Los límites y funcionalidades (features) se almacenan como datos en JSONField
   para que cambiar las capacidades de un plan no requiera redesplegar código.
3. Un límite ilimitado se representa como null (None en Python), nunca con números mágicos.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models.base import ModeloBase


class Plan(ModeloBase):
    """Catálogo de planes comerciales de Intersoft."""

    codigo = models.SlugField("código", max_length=40, unique=True)
    nombre = models.CharField("nombre", max_length=80)
    precio_mensual = models.DecimalField(
        "precio mensual (COP)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    precio_anual = models.DecimalField(
        "precio anual (COP)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    comision_porcentaje = models.DecimalField(
        "comisión marketplace (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    limites = models.JSONField(
        "límites por recurso",
        default=dict,
        blank=True,
        help_text='Diccionario de límites, ej. {"productos": 200, "usuarios": 2}. null significa ilimitado.',
    )
    features = models.JSONField(
        "funcionalidades habilitadas",
        default=list,
        blank=True,
        help_text='Lista de códigos de funcionalidad, ej. ["marketplace", "pos", "inventario"].',
    )
    orden = models.PositiveSmallIntegerField("orden de visualización", default=0)
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
        """Valores posibles de estado de suscripción: «Periodo de prueba», «Activa», «Vencida», «Cancelada»."""
        TRIAL = "TRIAL", "Periodo de prueba"
        ACTIVA = "ACTIVA", "Activa"
        VENCIDA = "VENCIDA", "Vencida"
        CANCELADA = "CANCELADA", "Cancelada"

    class Ciclo(models.TextChoices):
        """Valores posibles de ciclo de suscripción: «Mensual», «Anual»."""
        MENSUAL = "MENSUAL", "Mensual"
        ANUAL = "ANUAL", "Anual"

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
        "ciclo de cobro",
        max_length=10,
        choices=Ciclo.choices,
        default=Ciclo.MENSUAL,
    )
    inicia_en = models.DateTimeField("inicia en", default=timezone.now)
    vence_en = models.DateTimeField("vence en", null=True, blank=True, db_index=True)
    es_fundador = models.BooleanField(
        "es empresa fundadora",
        default=False,
        help_text="Las primeras 50 empresas con plan pago conservan 50% de descuento de por vida.",
    )
    descuento_porcentaje = models.DecimalField(
        "descuento permanente (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )

    class Meta:
        verbose_name = "suscripción"
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
        verbose_name="suscripción",
    )
    plan_anterior = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="plan anterior",
    )
    plan_nuevo = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name="plan nuevo",
    )
    estado_anterior = models.CharField(
        "estado anterior",
        max_length=15,
        choices=Suscripcion.Estado.choices,
        blank=True,
    )
    estado_nuevo = models.CharField(
        "estado nuevo",
        max_length=15,
        choices=Suscripcion.Estado.choices,
    )
    motivo = models.CharField("motivo", max_length=255, blank=True)
    fecha = models.DateTimeField("fecha del cambio", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "historial de suscripción"
        verbose_name_plural = "historial de suscripciones"
        ordering = ["-fecha", "-creado_en"]

    def __str__(self):
        anterior = self.plan_anterior.codigo if self.plan_anterior else "ninguno"
        return f"{self.suscripcion.empresa} · {anterior} -> {self.plan_nuevo.codigo} ({self.estado_nuevo})"


class CobroSuscripcion(ModeloBase):
    """Un intento de pagar un plan con la cuenta de Wompi de Intersoft.

    El plan SOLO se activa cuando Wompi confirma el pago (consulta del servidor o webhook firmado):
    el navegador nunca decide. Monto, plan y ciclo quedan congelados al crear el cobro."""

    class Estado(models.TextChoices):
        """Valores posibles de estado de cobro de suscripción: «Pendiente», «Aprobado», «Rechazado», «Anulado sin
        pago», «Requiere revisión».
        """
        PENDIENTE = "pendiente", "Pendiente"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"
        ANULADO = "anulado", "Anulado sin pago"
        REQUIERE_REVISION = "requiere_revision", "Requiere revisión"

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
    detalle = models.CharField("detalle del resultado", max_length=255, blank=True)
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
        verbose_name = "cobro de suscripción"
        verbose_name_plural = "cobros de suscripción"
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
        "cupos de fundador",
        default=50,
        help_text="Cantidad máxima de empresas que pueden obtener el descuento permanente de fundador.",
    )

    class Meta:
        verbose_name = "configuración de suscripciones"
        verbose_name_plural = "configuraciones de suscripciones"

    def __str__(self):
        return f"Configuración de suscripciones (cupos fundador: {self.cupos_fundador})"

    @classmethod
    def obtener(cls):
        """Configuración única de suscripciones (se crea si no existe)."""
        obj, _ = cls.objects.get_or_create(clave_unica=1, defaults={"cupos_fundador": 50})
        return obj

    @classmethod
    def obtener_cupos_fundador(cls, defecto: int = 50) -> int:
        """Cupos de fundador configurados (o el valor por defecto si la tabla aún no existe)."""
        from django.db import OperationalError, ProgrammingError

        try:
            obj = cls.objects.filter(clave_unica=1).only("cupos_fundador").first()
            return obj.cupos_fundador if obj is not None else defecto
        except (OperationalError, ProgrammingError):
            return defecto


class CuponPlan(ModeloBase):
    """Cupón de descuento aplicable al pago de planes de suscripción."""

    class Tipo(models.TextChoices):
        """Valores posibles de tipo de cupón de plan: «Porcentaje (%)», «Valor fijo (COP)»."""
        PORCENTAJE = "porcentaje", "Porcentaje (%)"
        VALOR_FIJO = "valor_fijo", "Valor fijo (COP)"

    codigo = models.CharField("código", max_length=40, unique=True)
    tipo = models.CharField("tipo de descuento", max_length=15, choices=Tipo.choices, default=Tipo.PORCENTAJE)
    valor = models.DecimalField(
        "valor",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    inicia_en = models.DateTimeField("vigente desde", default=timezone.now)
    vence_en = models.DateTimeField("vigente hasta", null=True, blank=True)
    usos_maximos = models.PositiveIntegerField("usos máximos", null=True, blank=True)
    usos_actuales = models.PositiveIntegerField("usos actuales", default=0)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "cupón de plan"
        verbose_name_plural = "cupones de planes"
        ordering = ["-creado_en"]

    def __str__(self):
        return f"{self.codigo} ({self.get_tipo_display()}: {self.valor})"

    def save(self, *args, **kwargs):
        self.codigo = (self.codigo or "").strip().upper()
        super().save(*args, **kwargs)

    def esta_vigente(self, ahora=None) -> bool:
        """Indica si el cupón está activo, en vigencia y con usos disponibles."""
        ahora = ahora or timezone.now()
        if not self.activo:
            return False
        if self.inicia_en and ahora < self.inicia_en:
            return False
        if self.vence_en and ahora > self.vence_en:
            return False
        return not (self.usos_maximos is not None and self.usos_actuales >= self.usos_maximos)


class RecordatorioVencimiento(ModeloBase):
    """Registro idempotente de recordatorios de vencimiento enviados por correo (7, 3 y 1 día)."""

    suscripcion = models.ForeignKey(
        Suscripcion,
        on_delete=models.CASCADE,
        related_name="recordatorios",
    )
    dias_antes = models.PositiveSmallIntegerField("días antes del vencimiento")
    fecha_objetivo = models.DateField("fecha de vencimiento objetivo")

    class Meta:
        verbose_name = "recordatorio de vencimiento"
        verbose_name_plural = "recordatorios de vencimiento"
        constraints = [
            models.UniqueConstraint(
                fields=["suscripcion", "dias_antes", "fecha_objetivo"],
                name="uq_recordatorio_suscripcion_dia_fecha",
            ),
        ]


