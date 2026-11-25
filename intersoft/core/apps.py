"""Configuración de la aplicación principal (core): registra señales y revisiones del sistema."""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configuración de la app core: al iniciar conecta señales y registra la revisión de la clave de cifrado."""
    name = 'core'

    def ready(self):
        from . import bienvenida  # noqa: F401  registra la señal user_logged_in
        from . import carrito  # noqa: F401  registra la fusión de carrito en user_logged_in
        from . import cifrado  # noqa: F401  registra el chequeo de la clave de cifrado
