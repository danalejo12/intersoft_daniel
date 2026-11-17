"""Configuración del Django Admin para Planes, Suscripciones e Historial."""
from django.contrib import admin

from .models import CobroSuscripcion, HistorialSuscripcion, Plan, Suscripcion


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "orden",
        "codigo",
        "nombre",
        "precio_mensual",
        "precio_anual",
        "comision_porcentaje",
        "activo",
    )
    list_display_links = ("codigo", "nombre")
    list_filter = ("activo",)
    search_fields = ("codigo", "nombre")
    ordering = ("orden", "precio_mensual")
    readonly_fields = ("id", "creado_en", "actualizado_en")


class HistorialSuscripcionInline(admin.TabularInline):
    """Inline de solo lectura: la bitácora de auditoría no debe alterarse manualmente."""

    model = HistorialSuscripcion
    extra = 0
    can_delete = False
    readonly_fields = (
        "plan_anterior",
        "plan_nuevo",
        "estado_anterior",
        "estado_nuevo",
        "motivo",
        "fecha",
        "creado_en",
    )
    ordering = ("-fecha", "-creado_en")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Suscripcion)
class SuscripcionAdmin(admin.ModelAdmin):
    list_display = (
        "empresa",
        "plan",
        "estado",
        "ciclo",
        "inicia_en",
        "vence_en",
        "es_fundador",
        "descuento_porcentaje",
    )
    list_filter = ("plan", "estado", "ciclo", "es_fundador")
    search_fields = ("empresa__nombre", "empresa__nit", "plan__nombre", "plan__codigo")
    autocomplete_fields = ()
    readonly_fields = ("id", "creado_en", "actualizado_en")
    inlines = [HistorialSuscripcionInline]


@admin.register(HistorialSuscripcion)
class HistorialSuscripcionAdmin(admin.ModelAdmin):
    list_display = (
        "suscripcion",
        "plan_anterior",
        "plan_nuevo",
        "estado_anterior",
        "estado_nuevo",
        "motivo",
        "fecha",
    )
    list_filter = ("plan_nuevo", "estado_nuevo", "estado_anterior")
    search_fields = ("suscripcion__empresa__nombre", "suscripcion__empresa__nit", "motivo")
    readonly_fields = (
        "id",
        "suscripcion",
        "plan_anterior",
        "plan_nuevo",
        "estado_anterior",
        "estado_nuevo",
        "motivo",
        "fecha",
        "creado_en",
        "actualizado_en",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CobroSuscripcion)
class CobroSuscripcionAdmin(admin.ModelAdmin):
    """Los cobros los decide Wompi: aquí solo se consultan (y se filtran los que requieren revisión)."""

    list_display = ("creado_en", "empresa", "plan", "ciclo", "monto", "estado", "referencia")
    list_filter = ("estado", "plan", "ciclo")
    search_fields = ("referencia", "transaccion_id", "empresa__nombre")
    list_select_related = ("empresa", "plan")
    readonly_fields = [f.name for f in CobroSuscripcion._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
