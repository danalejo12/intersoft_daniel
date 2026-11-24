"""Administración de Django: autorizaciones (solo lectura, son prueba legal) y solicitudes."""
from django.contrib import admin

from .models import AutorizacionDatos, SolicitudDatos


@admin.register(AutorizacionDatos)
class AutorizacionDatosAdmin(admin.ModelAdmin):
    """Las autorizaciones son prueba de lo que aceptó el titular: no se editan ni se borran."""

    list_display = ("usuario", "version_politica", "medio", "aceptada_en", "revocada_en")
    list_filter = ("version_politica", "medio")
    search_fields = ("usuario__email",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(SolicitudDatos)
class SolicitudDatosAdmin(admin.ModelAdmin):
    """Consulta de solicitudes; se atienden desde la consola /plataforma/datos-personales/."""

    list_display = ("radicado", "tipo", "titular", "estado", "fecha_limite")
    list_filter = ("tipo", "estado")
    search_fields = ("radicado", "titular__email")
    readonly_fields = ("radicado", "fecha_limite", "datos_suprimidos_en")
