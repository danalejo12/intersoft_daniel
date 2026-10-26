"""Ventas: facturas y su detalle."""
from decimal import Decimal
 
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
 
from .base import ModeloTenant
 
 
class Factura(ModeloTenant):
    class Estado(models.TextChoices):
        EMITIDA = "emitida", "Emitida"
        ANULADA = "anulada", "Anulada"
 
    numero = models.PositiveIntegerField()  # Consecutivo por empresa (lo asigna el servicio de ventas).
    cliente = models.ForeignKey("Cliente", on_delete=models.PROTECT, related_name="facturas")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EMITIDA)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    iva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    observaciones = models.TextField(blank=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="facturas_creadas"
    )
    anulada_en = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        verbose_name = "factura"
        verbose_name_plural = "facturas"
        ordering = ["-numero"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_factura_numero_por_empresa"),
            models.CheckConstraint(condition=Q(total__gte=0), name="ck_factura_total_no_negativo"),
        ]
        indexes = [
            models.Index(fields=["empresa", "-creado_en"], name="ix_factura_empresa_fecha"),
            models.Index(fields=["empresa", "estado"], name="ix_factura_empresa_estado"),
        ]
 
    def __str__(self):
        return f"Factura {self.numero}"
 
 
class DetalleFactura(ModeloTenant):
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="detalles_factura")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Precio e IVA se CONGELAN al vender: si mañana cambia el precio, la factura no cambia.
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2)
 
    class Meta:
        verbose_name = "detalle de factura"
        verbose_name_plural = "detalles de factura"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_detalle_cantidad_positiva"),
        ]
 
    def __str__(self):
        return f"{self.cantidad} × {self.producto}"
 
    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad
 
    @property
    def valor_iva(self):
        return (self.subtotal * self.iva_porcentaje / 100).quantize(Decimal("0.01"))
 