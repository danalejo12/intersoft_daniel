"""Clientes de cada empresa."""
from django.db import models

from .base import ModeloTenant


class Cliente(ModeloTenant):
    """Cliente de un negocio (persona o empresa a la que se le factura), único por tipo y número de documento."""
    class TipoDocumento(models.TextChoices):
        """Valores posibles de tipodocumento de cliente: «Cédula de ciudadanía», «NIT», «Cédula de extranjería»,
        «Pasaporte».
        """
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
    # Ley 1581: el negocio es responsable de los datos de sus clientes y debe poder probar la autorización
    autoriza_datos = models.BooleanField(
        "autorizó el tratamiento de datos", default=False,
        help_text="Marca solo si el cliente autorizó usar sus datos (por escrito, de forma verbal grabada o en un formato firmado).",
    )
    autoriza_datos_en = models.DateTimeField("autorización registrada en", null=True, blank=True)

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
