from django.contrib import admin

from .models import PQRS, MensajePQRS, SecuenciaRadicadoPQRS


@admin.register(SecuenciaRadicadoPQRS)
class SecuenciaRadicadoPQRSAdmin(admin.ModelAdmin):
    list_display = ("anio", "ultimo_consecutivo")
    readonly_fields = ("anio", "ultimo_consecutivo")


@admin.register(PQRS)
class PQRSAdmin(admin.ModelAdmin):
    list_display = ("radicado", "flujo", "tipo", "estado", "prioridad", "empresa", "autor", "fecha_limite")
    list_filter = ("flujo", "estado", "tipo", "prioridad")
    search_fields = ("radicado", "asunto", "autor__email", "empresa__nombre")
    readonly_fields = ("radicado", "creado_en", "actualizado_en")


@admin.register(MensajePQRS)
class MensajePQRSAdmin(admin.ModelAdmin):
    list_display = ("pqrs", "autor", "interno", "creado_en")
    list_filter = ("interno",)
