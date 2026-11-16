from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import bienvenida  # noqa: F401  registra la señal user_logged_in
        from . import cifrado  # noqa: F401  registra el chequeo de la clave de cifrado
