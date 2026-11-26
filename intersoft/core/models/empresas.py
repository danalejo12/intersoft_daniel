"""Empresa: el tenant del SaaS."""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from ..validadores import exigir_letra_o_numero, validar_direccion, validar_nit, validar_usuario_del_correo
from .base import ModeloBase


class Empresa(ModeloBase):
    """Negocio registrado en Intersoft: datos legales, logo, envíos y su pasarela de pagos."""
    class Plan(models.TextChoices):
        """Valores posibles de plan de empresa: «Gratis», «Pro», «Empresarial»."""
        GRATIS = "gratis", "Gratis"
        PRO = "pro", "Pro"
        EMPRESARIAL = "empresarial", "Empresarial"

    nombre = models.CharField(max_length=150, validators=[exigir_letra_o_numero])
    nit = models.CharField("NIT", max_length=20, unique=True, validators=[validar_nit])
    slug = models.SlugField(max_length=160, unique=True)
    email = models.EmailField(blank=True, validators=[validar_usuario_del_correo])
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.CharField(max_length=200, blank=True, validators=[validar_direccion])
    logo = models.ImageField("logo del negocio", upload_to="negocios/", blank=True, null=True)
    descripcion = models.TextField("descripción del negocio", max_length=500, blank=True)
    sitio_web = models.URLField("sitio web o red social", blank=True)
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

    @property
    def configuracion_pagos(self):
        return getattr(self, "pasarela", None)

    @property
    def compra_en_linea(self):
        """Indica si el negocio tiene la pasarela activa y verificada para vender en línea."""
        config = self.configuracion_pagos
        return bool(config and config.lista_para_cobrar)

