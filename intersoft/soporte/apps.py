from django.utils.translation import gettext_lazy
from django.apps import AppConfig
from django.core.signals import got_request_exception


class SoporteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "soporte"
    verbose_name = gettext_lazy("Soporte, errores y feedback")

    def ready(self):
        from .errores import capturar_excepcion_request

        got_request_exception.connect(
            capturar_excepcion_request,
            dispatch_uid="soporte.capturar_excepcion_request",
        )
