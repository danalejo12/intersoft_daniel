"""Compras del marketplace: pedidos con datos de envío y opiniones de productos."""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from .base import ModeloTenant
from .ventas import Factura


class Pedido(ModeloTenant):
    """Lo que compró una persona en un negocio. La factura guarda productos, precios y pagos."""

    ETIQUETAS = {
        "por_pagar": "Por pagar",
        "procesando": "Confirmando pago",
        "pagado": "Pagado",
        "rechazado": "Pago no aprobado",
        "cancelado": "Cancelado",
    }

    comprador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pedidos")
    factura = models.OneToOneField(Factura, on_delete=models.PROTECT, related_name="pedido")
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
        indexes = [models.Index(fields=["comprador", "-creado_en"], name="ix_pedido_comprador_fecha")]

    def __str__(self):
        return f"Pedido de {self.nombre} · {self.factura}"

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
