"""Filtros de traducción para valores dinámicos (estados, roles y permisos guardados en español)."""
from django import template
from django.utils.translation import gettext

register = template.Library()


@register.filter
def traducir(valor):
    """Traduce un texto si existe en el catálogo; deja intactos números y textos propios del usuario."""
    if isinstance(valor, str) and valor:
        return gettext(valor)
    return valor
