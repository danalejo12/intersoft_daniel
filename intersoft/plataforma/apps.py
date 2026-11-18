"""Configuración de la aplicación plataforma."""
from django.apps import AppConfig


class PlataformaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plataforma"
    verbose_name = "Consola de Plataforma"
