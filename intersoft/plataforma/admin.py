"""Registro en Django Admin para los modelos de plataforma."""
from django.contrib import admin

from .models import AuditoriaPlataforma, ConfiguracionCobroPlataforma, RolPlataforma


@admin.register(RolPlataforma)
class RolPlataformaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "rol", "activo", "creado_en")
    list_filter = ("rol", "activo")
    search_fields = ("usuario__email", "usuario__first_name", "usuario__last_name")


@admin.register(AuditoriaPlataforma)
class AuditoriaPlataformaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "accion", "actor", "objeto_tipo", "objeto_id", "ip")
    list_filter = ("accion", "objeto_tipo")
    search_fields = ("accion", "actor__email", "objeto_id")
    readonly_fields = ("id", "actor", "accion", "objeto_tipo", "objeto_id", "detalle", "ip", "fecha", "creado_en")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfiguracionCobroPlataforma)
class ConfiguracionCobroPlataformaAdmin(admin.ModelAdmin):
    list_display = ("modo", "llave_publica", "activa", "verificada_en", "actualizada_por")
    readonly_fields = (
        "id",
        "llave_privada_final",
        "secreto_integridad_final",
        "secreto_eventos_final",
        "verificada_en",
        "comercio_verificado",
        "ultimo_intento_verificacion",
        "creado_en",
        "actualizado_en",
    )
    exclude = ("llave_privada_cifrada", "secreto_integridad_cifrado", "secreto_eventos_cifrado")
