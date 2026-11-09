"""Compras del marketplace: pedidos con datos de envío y opiniones de productos."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from .base import ModeloTenant
from .ventas import Factura


class Pedido(ModeloTenant):
    """Lo que compró una persona en un negocio. Guarda sus líneas y su total: la factura nace al pagar."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de pago"
        PAGADO = "pagado", "Pagado"
        VENCIDO = "vencido", "Vencido"
        CANCELADO = "cancelado", "Cancelado"
        REQUIERE_REEMBOLSO = "requiere_reembolso", "Requiere reembolso"

    ETIQUETAS = {
        "por_pagar": "Por pagar",
        "procesando": "Confirmando pago",
        "pagado": "Pagado",
        "rechazado": "Pago no aprobado",
        "cancelado": "Cancelado",
    }

    comprador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pedidos")
    factura = models.OneToOneField(Factura, on_delete=models.PROTECT, related_name="pedido", null=True, blank=True)
    numero = models.PositiveIntegerField()  # Consecutivo por empresa, independiente del de facturas.
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    expira_en = models.DateTimeField()
    renovaciones = models.PositiveSmallIntegerField(default=0)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    iva = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    tipo_documento = models.CharField(max_length=5)
    numero_documento = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)
    departamento = models.CharField(max_length=60)
    ciudad = models.CharField(max_length=80)
    direccion = models.CharField(max_length=200)
    indicaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="uq_pedido_numero_por_empresa"),
            models.CheckConstraint(condition=Q(total__gte=0), name="ck_pedido_total_no_negativo"),
        ]
        indexes = [
            models.Index(fields=["comprador", "-creado_en"], name="ix_pedido_comprador_fecha"),
            models.Index(fields=["estado", "expira_en"], name="ix_pedido_estado_expira"),
        ]

    def __str__(self):
        return f"Pedido {self.numero} de {self.nombre}"

    @property
    def estado_compra(self):
        if self.factura.estado == Factura.Estado.ANULADA:
            return "cancelado"
        estados = list(self.factura.pagos.values_list("estado", flat=True))  # del más reciente al más viejo
        if "aprobado" in estados:
            return "pagado"
        if not estados:
            return "por_pagar"
        return "procesando" if estados[0] == "pendiente" else "rechazado"

    @property
    def primer_nombre(self):
        return self.nombre.split()[0]

    @property
    def estado_etiqueta(self):
        return self.ETIQUETAS[self.estado_compra]


class DetallePedido(ModeloTenant):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="lineas")
    producto = models.ForeignKey("Producto", on_delete=models.PROTECT, related_name="lineas_pedido")
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    # Se CONGELAN al confirmar: si mañana cambia el precio, este pedido no cambia.
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    iva_porcentaje = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = "línea de pedido"
        verbose_name_plural = "líneas de pedido"
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="ck_linea_pedido_cantidad_positiva"),
        ]

    def __str__(self):
        return f"{self.cantidad} × {self.producto}"


class Comentario(ModeloTenant):
    producto = models.ForeignKey("Producto", on_delete=models.CASCADE, related_name="comentarios")
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comentarios")
    calificacion = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    texto = models.TextField(max_length=1000)
    compra_verificada = models.BooleanField(default=False)  # La calcula el servidor, nunca el navegador.

    class Meta:
        verbose_name = "comentario"
        verbose_name_plural = "comentarios"
        ordering = ["-creado_en"]
        constraints = [
            models.UniqueConstraint(fields=["producto", "autor"], name="uq_comentario_por_autor"),
            models.CheckConstraint(condition=Q(calificacion__gte=1) & Q(calificacion__lte=5), name="ck_comentario_calificacion"),
        ]

    def __str__(self):
        return f"{self.producto} · {self.calificacion}/5"

    @property
    def nombre_publico(self):
        """Nombre e inicial del apellido: el correo de una persona nunca se publica."""
        nombre = self.autor.first_name.strip()
        apellido = self.autor.last_name.strip()
        if not nombre:
            return "Cliente de Intersoft"
        return f"{nombre} {apellido[0]}." if apellido else nombre
