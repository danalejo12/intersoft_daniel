"""Inventario: categorías, productos y kardex de movimientos."""
from decimal import Decimal
 
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
 
from .base import ModeloTenant
 
 
class Categoria(ModeloTenant):
    nombre = models.CharField(max_length=80)
    activa = models.BooleanField(default=True)
 
    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "nombre"], name="uq_categoria_nombre_por_empresa"),
        ]
 
    def __str__(self):
        return self.nombre
 
 
class Producto(ModeloTenant):
    categoria = models.ForeignKey(
        Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name="productos"
    )
    codigo = models.CharField(max_length=30)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    iva_porcentaje = models.DecimalField(
        "IVA (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("19.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    stock = models.IntegerField(default=0)
    stock_minimo = models.IntegerField(default=0)  # Para alertas de reabastecimiento.
    activo = models.BooleanField(default=True)
 
    class Meta:
        verbose_name = "producto"
        verbose_name_plural = "productos"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "codigo"], name="uq_producto_codigo_por_empresa"),
            # La base de datos rechaza valores imposibles aunque el código falle.
            models.CheckConstraint(condition=Q(stock__gte=0), name="ck_producto_stock_no_negativo"),
            models.CheckConstraint(condition=Q(precio__gte=0), name="ck_producto_precio_no_negativo"),
            models.CheckConstraint(
                condition=Q(iva_porcentaje__gte=0) & Q(iva_porcentaje__lte=100),
                name="ck_producto_iva_rango",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "nombre"], name="ix_producto_empresa_nombre"),
        ]
 
    def __str__(self):
        return f"{self.codigo} · {self.nombre}"
 
    @property
    def stock_bajo(self):
        return self.stock <= self.stock_minimo
 
 
class MovimientoInventario(ModeloTenant):
    """Historial inmutable de cada cambio de stock (kardex)."""
 
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida"
        AJUSTE = "ajuste", "Ajuste"
 
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="movimientos")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    cantidad = models.IntegerField()  # Entrada/salida en positivo; un ajuste puede ser negativo.
    referencia = models.CharField(max_length=60, blank=True)  # Ej.: "Factura 15".
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos_inventario"
    )
 
    class Meta:
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        ordering = ["-creado_en"]
        indexes = [
            models.Index(fields=["empresa", "producto", "-creado_en"], name="ix_movimiento_producto_fecha"),
        ]
 
    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad} · {self.producto}"
 