"""Configuración de la aplicación suscripciones."""
from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class SuscripcionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "suscripciones"
    verbose_name = gettext_lazy("Suscripciones y planes")

    def ready(self):
        from . import signals  # noqa: F401
