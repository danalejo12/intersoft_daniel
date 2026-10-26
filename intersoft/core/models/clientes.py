"""Clientes de cada empresa."""
from django.db import models
 
from .base import ModeloTenant
 
 
class Cliente(ModeloTenant):
    class TipoDocumento(models.TextChoices):
        CC = "CC", "Cédula de ciudadanía"
        NIT = "NIT", "NIT"
        CE = "CE", "Cédula de extranjería"
        PP = "PP", "Pasaporte"
 
    tipo_documento = models.CharField(max_length=5, choices=TipoDocumento.choices)
    numero_documento = models.CharField(max_length=20)
    nombre = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    activo = models.BooleanField(default=True)  # Borrado lógico: nunca se elimina un cliente con facturas.
 
    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "tipo_documento", "numero_documento"],
                name="uq_cliente_documento_por_empresa",
            ),
        ]
        indexes = [
            models.Index(fields=["empresa", "nombre"], name="ix_cliente_empresa_nombre"),
        ]
 
    def __str__(self):
        return f"{self.nombre} ({self.tipo_documento} {self.numero_documento})"
 