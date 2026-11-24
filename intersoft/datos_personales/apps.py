"""Configuración de la aplicación de protección de datos personales."""
from django.apps import AppConfig


class DatosPersonalesConfig(AppConfig):
    """Aplicación «Protección de datos personales» (Ley 1581 de 2012)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "datos_personales"
    verbose_name = "Protección de datos personales"
