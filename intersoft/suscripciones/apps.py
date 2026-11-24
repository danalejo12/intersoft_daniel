"""Configuración de la aplicación suscripciones."""
from django.apps import AppConfig


class SuscripcionesConfig(AppConfig):
    """Configuración de la aplicación «Suscripciones y planes» (suscripciones)."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "suscripciones"
    verbose_name = "Suscripciones y planes"

    def ready(self):
        from . import signals  # noqa: F401
