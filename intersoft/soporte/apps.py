"""Configuración de la aplicación de soporte."""
from django.apps import AppConfig
from django.core.signals import got_request_exception


class SoporteConfig(AppConfig):
    """Configuración de la aplicación «Soporte, errores y feedback» (soporte)."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "soporte"
    verbose_name = "Soporte, errores y feedback"

    def ready(self):
        from .errores import capturar_excepcion_request

        got_request_exception.connect(
            capturar_excepcion_request,
            dispatch_uid="soporte.capturar_excepcion_request",
        )
