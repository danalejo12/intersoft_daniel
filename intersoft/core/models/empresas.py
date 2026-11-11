"""Empresa: el tenant del SaaS."""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import ModeloBase


class Empresa(ModeloBase):
    class Plan(models.TextChoices):
        GRATIS = "gratis", "Gratis"
        PRO = "pro", "Pro"
        EMPRESARIAL = "empresarial", "Empresarial"

    nombre = models.CharField(max_length=150)
    nit = models.CharField("NIT", max_length=20, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.GRATIS)
    activa = models.BooleanField(default=True)
    comision_porcentaje = models.DecimalField(
        "Comisión plataforma (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("50"))],
    )
    tarifa_envio_base = models.DecimalField(
        "Tarifa base de envío",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    tarifa_envio_por_kg = models.DecimalField(
        "Tarifa de envío por kg",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    envio_gratis_desde = models.DecimalField(
        "Envío gratis desde",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
 
    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["nombre"]
 
    def __str__(self):
        return self.nombre

    @property
    def datos_completos(self):
        """Ley 1480, art. 53: sin dirección de notificaciones y teléfono, el negocio no puede vender."""
        return bool(self.direccion.strip() and self.telefono.strip())
 