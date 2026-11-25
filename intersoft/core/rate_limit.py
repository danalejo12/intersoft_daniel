"""Limitación de tasa (rate limiting) basada en caché (LocMem en local, Redis en producción)."""
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


def ip_cliente(request) -> str:
    """Obtiene la IP real del cliente respetando RATELIMIT_PROXIES_DE_CONFIANZA."""
    proxies = getattr(settings, "RATELIMIT_PROXIES_DE_CONFIANZA", 0)
    if proxies > 0:
        reenviada = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
        if reenviada:
            return reenviada
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def verificar_limite(
    request,
    *,
    ambito: str,
    maximo: int,
    ventana_segundos: int = 900,
    por_usuario: bool = False,
) -> bool:
    """Incrementa el contador del ámbito y devuelve True si aún está dentro del límite permitido."""
    if not getattr(settings, "RATELIMIT_ACTIVO", True):
        return True
    usuario = getattr(request, "user", None)
    if por_usuario and usuario is not None and getattr(usuario, "is_authenticated", False):
        sujeto = f"u:{usuario.pk}"
    else:
        sujeto = f"ip:{ip_cliente(request)}"
    clave = f"rl:{ambito}:{sujeto}"
    cache.add(clave, 0, ventana_segundos)
    try:
        actual = cache.incr(clave)
    except ValueError:
        cache.set(clave, 1, ventana_segundos)
        actual = 1
    return actual <= maximo


def respuesta_limite_excedido(
    mensaje: str = "Demasiadas solicitudes en poco tiempo. Espera unos minutos e inténtalo de nuevo.",
    *,
    reintentar_en: int = 900,
) -> HttpResponse:
    """Respuesta estándar HTTP 429 Too Many Requests con cabecera Retry-After."""
    respuesta = HttpResponse(mensaje, status=429, content_type="text/plain; charset=utf-8")
    respuesta["Retry-After"] = str(reintentar_en)
    return respuesta
