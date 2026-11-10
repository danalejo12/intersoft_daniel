from django.conf import settings
from django.test.runner import DiscoverRunner


class EjecutorPruebas(DiscoverRunner):
    """Ejecutor de pruebas del proyecto.

    El cliente de pruebas de Django habla HTTP. Con DEBUG=False la configuración activa
    la redirección a HTTPS y todas las peticiones responderían 301; aquí se apaga solo eso.
    El resto de la configuración de producción (cookies seguras, HSTS) sigue activa.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        settings.SECURE_SSL_REDIRECT = False
