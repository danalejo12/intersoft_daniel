"""Configuración de la aplicación de PQRS."""
from django.apps import AppConfig


class PqrsConfig(AppConfig):
    """Configuración de la aplicación «PQRS» (pqrs)."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "pqrs"
    verbose_name = "PQRS"
