"""Utilidades de auditoría para registrar todas las acciones administrativas en /plataforma/."""
from .models import AuditoriaPlataforma

CLAVES_SENSIBLES = ("secreto", "llave_privada", "password", "clave", "token")


def _sanitizar_detalle(detalle) -> dict:
    """Quita del detalle las claves con nombres sensibles (llaves, secretos, contraseñas)."""
    if not isinstance(detalle, dict):
        return {}
    limpio = {}
    for k, v in detalle.items():
        clave_str = str(k).lower()
        if any(p in clave_str for p in CLAVES_SENSIBLES):
            continue
        limpio[str(k)] = v
    return limpio


def _obtener_ip(request) -> str | None:
    """IP del actor con la misma regla segura del límite de peticiones (no se confía en X-Forwarded-For)."""
    if request is None:
        return None
    from core.ratelimit import obtener_ip_cliente

    ip = obtener_ip_cliente(request)
    return None if ip in ("", "0.0.0.0") else ip


def registrar(
    *,
    actor,
    accion: str,
    objeto_tipo: str = "",
    objeto_id: str = "",
    detalle: dict | None = None,
    request=None,
    ip: str | None = None,
) -> AuditoriaPlataforma:
    """Registra una acción en la bitácora de auditoría sin almacenar secretos."""
    return AuditoriaPlataforma.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        accion=str(accion)[:80],
        objeto_tipo=str(objeto_tipo)[:60],
        objeto_id=str(objeto_id)[:60],
        detalle=_sanitizar_detalle(detalle or {}),
        ip=ip or _obtener_ip(request),
    )
