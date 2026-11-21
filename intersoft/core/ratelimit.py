"""Limitación de peticiones (rate limiting) basada en caché para webhooks y endpoints críticos."""
from django.utils.translation import gettext
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

REGLAS_POR_DEFECTO = (
    ("/webhooks/wompi/", ("POST",), 120, 60, "wompi_webhook"),
    ("/login/", ("POST",), 20, 60, "login"),
    ("/plataforma/login/", ("POST",), 20, 60, "plataforma_login"),
    ("/registro/", ("POST",), 10, 60, "registro"),
    ("/registrar-negocio/", ("POST",), 10, 60, "registrar_negocio"),
    ("/recuperar-contrasena/", ("POST",), 10, 60, "recuperar_contrasena"),
    ("/comprar/", ("POST",), 20, 60, "checkout"),
    ("/pqrs/", ("POST",), 15, 60, "pqrs_publico"),
)


def obtener_ip_cliente(request) -> str:
    """Extrae la IP real del cliente respetando X-Forwarded-For cuando existe."""
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if xff:
        return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "0.0.0.0").strip()


def verificar_limite(grupo: str, identificador: str, limite: int, ventana: int) -> tuple[bool, int]:
    """Incrementa el contador en caché y devuelve (permitido, segundos_espera)."""
    if limite <= 0 or ventana <= 0:
        return True, 0
    clave = f"rl:{grupo}:{identificador}"
    # add() inicializa en 1 solo si la clave no existe; incr() incrementa atómicamente.
    if cache.add(clave, 1, timeout=ventana):
        actual = 1
    else:
        try:
            actual = cache.incr(clave)
        except ValueError:
            cache.set(clave, 1, timeout=ventana)
            actual = 1
    return actual <= limite, ventana


class RateLimitMiddleware:
    """Aplica límites de tasa por IP en webhooks de Wompi y endpoints públicos críticos."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "RATELIMIT_ACTIVO", True):
            return self.get_response(request)

        reglas = getattr(settings, "RATELIMIT_REGLAS", REGLAS_POR_DEFECTO)
        ruta = request.path_info or request.path
        metodo = request.method.upper()

        for prefijo, metodos, limite, ventana, grupo in reglas:
            if metodo in metodos and ruta.startswith(prefijo):
                ip = obtener_ip_cliente(request)
                permitido, espera = verificar_limite(grupo, ip, limite, ventana)
                if not permitido:
                    return self._respuesta_429(request, espera)
                break

        return self.get_response(request)

    @staticmethod
    def _respuesta_429(request, espera: int) -> HttpResponse:
        mensaje = gettext("Demasiadas peticiones. Por favor espera un momento antes de intentarlo de nuevo.")
        acepta = request.META.get("HTTP_ACCEPT", "")
        if (
            request.path.startswith("/webhooks/")
            or request.path.startswith("/api/")
            or "application/json" in acepta
        ):
            resp = JsonResponse({"error": mensaje}, status=429)
        else:
            resp = HttpResponse(mensaje, status=429, content_type="text/plain; charset=utf-8")
        resp["Retry-After"] = str(espera)
        return resp
