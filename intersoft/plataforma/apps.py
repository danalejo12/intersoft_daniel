"""Configuración de la aplicación plataforma."""
from django.apps import AppConfig


class PlataformaConfig(AppConfig):
    """Configuración de la aplicación «Consola de Plataforma» (plataforma)."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "plataforma"
    verbose_name = "Consola de Plataforma"
