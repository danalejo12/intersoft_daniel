"""Context processor para controlar la frecuencia de la encuesta NPS (máximo 1 cada 90 días)."""
from datetime import timedelta

from django.db import OperationalError, ProgrammingError
from django.utils import timezone

from .models import EncuestaNPS

DIAS_VENTANA_NPS = 90


def usuario_puede_responder_nps(usuario, ahora=None) -> bool:
    """Indica si el usuario puede responder la encuesta NPS (una vez cada DIAS_VENTANA_NPS días)."""
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    ahora = ahora or timezone.now()
    limite = ahora - timedelta(days=DIAS_VENTANA_NPS)
    try:
        return not EncuestaNPS.objects.filter(usuario=usuario, creado_en__gte=limite).exists()
    except (OperationalError, ProgrammingError):
        return False


def soporte_feedback(request):
    return {
        "soporte_mostrar_nps": usuario_puede_responder_nps(getattr(request, "user", None)),
    }
