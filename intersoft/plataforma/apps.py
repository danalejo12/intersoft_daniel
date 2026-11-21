"""Configuración de la aplicación plataforma."""
from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class PlataformaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plataforma"
    verbose_name = gettext_lazy("Consola de Plataforma")
