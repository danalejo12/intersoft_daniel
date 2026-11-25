"""Utilidades HTTP seguras para validación de identificadores UUID sin errores 500."""
import uuid

from django.http import Http404
from django.shortcuts import get_object_or_404


def es_uuid_valido(valor) -> bool:
    """Devuelve True si el valor representa un UUID válido."""
    if not valor:
        return False
    try:
        uuid.UUID(str(valor).strip())
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def obtener_por_uuid_o_404(modelo_o_queryset, valor, **filtros):
    """Obtiene un objeto por UUID o lanza Http404 (nunca ValidationError 500 si el UUID viene corrupto)."""
    if not es_uuid_valido(valor):
        raise Http404("Identificador UUID no válido.")
    return get_object_or_404(modelo_o_queryset, pk=str(valor).strip(), **filtros)
