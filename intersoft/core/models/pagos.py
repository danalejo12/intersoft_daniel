from django.db import models
from django.db.models import Q

from .base import ModeloTenant


class Pago(ModeloTenant):
    """Un intento de cobro de una factura a través de la pasarela."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"
        ANULADO = "anulado", "Anulado"
        ERROR = "error", "Error"

    # Exactamente uno: el panel cobra facturas; el marketplace cobra pedidos.
    factura = models.ForeignKey("Factura", on_delete=models.PROTECT, related_name="pagos", null=True, blank=True)
    pedido = models.ForeignKey("Pedido", on_delete=models.PROTECT, related_name="pagos", null=True, blank=True)
    referencia = models.CharField(max_length=60, unique=True)
    monto_centavos = models.BigIntegerField()
    moneda = models.CharField(max_length=3, default="COP")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    wompi_transaccion_id = models.CharField(max_length=60, blank=True)
    metodo_pago = models.CharField(max_length=30, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado_en"]
        constraints = [
            models.CheckConstraint(condition=Q(monto_centavos__gt=0), name="ck_pago_monto_positivo"),
            models.UniqueConstraint(
                fields=["factura"],
                condition=Q(estado="aprobado"),
                name="uq_un_pago_aprobado_por_factura",
            ),
            models.UniqueConstraint(
                fields=["pedido"],
                condition=Q(estado="aprobado"),
                name="uq_un_pago_aprobado_por_pedido",
            ),
            models.CheckConstraint(
                condition=(Q(factura__isnull=False) & Q(pedido__isnull=True))
                | (Q(factura__isnull=True) & Q(pedido__isnull=False)),
                name="ck_pago_factura_o_pedido",
            ),
        ]

    def __str__(self):
        return f"{self.referencia} ({self.get_estado_display()})"