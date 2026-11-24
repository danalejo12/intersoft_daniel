"""Exige la autorización vigente de tratamiento de datos antes de usar la cuenta (Ley 1581 art. 9).

Si el titular no ha aceptado la versión actual de la política (cuentas antiguas o cambio de política),
se le lleva a la página de autorización. Las páginas legales y «Mis datos» siguen abiertas: el titular
puede leer la política o pedir la supresión sin haber aceptado."""
from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect

from .services import autorizacion_vigente

RUTAS_LIBRES = (
    "/privacidad/", "/mis-datos/", "/terminos/", "/devoluciones/", "/logout/", "/static/", "/media/",
    "/admin/", "/webhooks/", "/api/", "/salud/", "/sw.js",
)


class ExigirAutorizacionDatosMiddleware:
    """Redirige a /privacidad/autorizar/ a quien inicia sesión sin autorización vigente."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._debe_autorizar(request):
            return redirect(f"/privacidad/autorizar/?next={quote(request.get_full_path())}")
        return self.get_response(request)

    @staticmethod
    def _debe_autorizar(request) -> bool:
        """Solo aplica a usuarios autenticados, en peticiones GET de páginas que no son libres."""
        if not getattr(settings, "PROTECCION_DATOS_EXIGIR_AUTORIZACION", True):
            return False
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated or request.method != "GET":
            return False
        if request.path.startswith(RUTAS_LIBRES):
            return False
        return autorizacion_vigente(usuario) is None
