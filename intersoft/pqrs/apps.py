from django.utils.translation import gettext_lazy
from django.apps import AppConfig


class PqrsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pqrs"
    verbose_name = gettext_lazy("PQRS")
