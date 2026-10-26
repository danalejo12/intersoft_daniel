"""Empresa: el tenant del SaaS."""
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
 
    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["nombre"]
 
    def __str__(self):
        return self.nombre
 