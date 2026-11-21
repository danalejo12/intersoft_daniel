"""Empresa: el tenant del SaaS."""
from django.utils.translation import gettext_lazy
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import ModeloBase


class Empresa(ModeloBase):
    class Plan(models.TextChoices):
        GRATIS = "gratis", gettext_lazy("Gratis")
        PRO = "pro", gettext_lazy("Pro")
        EMPRESARIAL = "empresarial", gettext_lazy("Empresarial")

    nombre = models.CharField(max_length=150)
    nit = models.CharField("NIT", max_length=20, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(gettext_lazy("logo del negocio"), upload_to="negocios/", blank=True, null=True)
    descripcion = models.TextField(gettext_lazy("descripción del negocio"), max_length=500, blank=True)
    sitio_web = models.URLField(gettext_lazy("sitio web o red social"), blank=True)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.GRATIS)
    activa = models.BooleanField(default=True)
    comision_porcentaje = models.DecimalField(
        gettext_lazy("Comisión plataforma (%)"),
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("50"))],
    )
    tarifa_envio_base = models.DecimalField(
        gettext_lazy("Tarifa base de envío"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    tarifa_envio_por_kg = models.DecimalField(
        gettext_lazy("Tarifa de envío por kg"),
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    envio_gratis_desde = models.DecimalField(
        gettext_lazy("Envío gratis desde"),
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

    @property
    def configuracion_pagos(self):
        return getattr(self, "pasarela", None)

    @property
    def compra_en_linea(self):
        config = self.configuracion_pagos
        return bool(config and config.lista_para_cobrar)

