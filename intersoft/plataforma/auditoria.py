"""Utilidades de auditoría para registrar todas las acciones administrativas en /plataforma/."""
from .models import AuditoriaPlataforma

CLAVES_SENSIBLES = ("secreto", "llave_privada", "password", "clave", "token")


def _sanitizar_detalle(detalle) -> dict:
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
    if request is None:
        return None
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if reenviada:
        return reenviada.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


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
