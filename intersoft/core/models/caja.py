"""Punto de venta: turnos de caja y pagos recibidos en el mostrador."""
from django.utils.translation import gettext, gettext_lazy
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from .base import ModeloTenant


class TurnoCaja(ModeloTenant):
    """Desde que un cajero abre caja con una base hasta que la cierra contando el efectivo."""

    cajero = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="turnos_caja")
    base_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    # La caja vende desde esta bodega (se elige al abrir el turno)
    bodega = models.ForeignKey("Bodega", on_delete=models.PROTECT, related_name="turnos", null=True, blank=True)
    cerrado_en = models.DateTimeField(null=True, blank=True)
    # Se guardan al cerrar: así el arqueo no cambia aunque luego se corrija algo
    efectivo_esperado = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    efectivo_contado = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    diferencia = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = gettext_lazy("turno de caja")
        verbose_name_plural = gettext_lazy("turnos de caja")
        ordering = ["-creado_en"]
        constraints = [
            # Un cajero no puede tener dos cajas abiertas en el mismo negocio
            models.UniqueConstraint(
                fields=["empresa", "cajero"], condition=Q(cerrado_en__isnull=True), name="uq_un_turno_abierto_por_cajero"
            ),
            models.CheckConstraint(condition=Q(base_inicial__gte=0), name="ck_turno_base_no_negativa"),
        ]

    def __str__(self):
        return gettext("Caja de {cajero} · {creado_en:%d/%m/%Y %H:%M}").format(cajero=self.cajero, creado_en=self.creado_en)

    @property
    def abierto(self):
        return self.cerrado_en is None


class PagoCaja(ModeloTenant):
    """Lo que entra a la caja por una venta. Una venta puede pagarse con varios medios."""

    class Metodo(models.TextChoices):
        EFECTIVO = "efectivo", gettext_lazy("Efectivo")
        TARJETA = "tarjeta", gettext_lazy("Tarjeta (datáfono)")
        TRANSFERENCIA = "transferencia", gettext_lazy("Transferencia o Nequi")

    turno = models.ForeignKey(TurnoCaja, on_delete=models.PROTECT, related_name="pagos")
    factura = models.ForeignKey("Factura", on_delete=models.PROTECT, related_name="pagos_caja")
    metodo = models.CharField(max_length=15, choices=Metodo.choices)
    monto = models.DecimalField(max_digits=14, decimal_places=2)  # lo que se abona a la venta
    recibido = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)  # solo efectivo
    cambio = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    referencia = models.CharField(max_length=60, blank=True)  # comprobante de tarjeta o transferencia

    class Meta:
        verbose_name = gettext_lazy("pago de caja")
        verbose_name_plural = gettext_lazy("pagos de caja")
        ordering = ["creado_en"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="ck_pago_caja_monto_positivo"),
            models.CheckConstraint(condition=Q(cambio__gte=0), name="ck_pago_caja_cambio_no_negativo"),
        ]

    def __str__(self):
        return f"{self.get_metodo_display()} {self.monto}"
