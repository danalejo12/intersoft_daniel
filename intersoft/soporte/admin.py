"""Registro de los modelos de soporte (errores, reportes, NPS, ideas) en el admin de Django."""
from django.contrib import admin

from .models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, Idea, ReporteProblema, VotoIdea


@admin.register(ErrorRegistrado)
class ErrorRegistradoAdmin(admin.ModelAdmin):
    """Administración de errores registrados en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("tipo_excepcion", "archivo", "linea", "estado", "contador", "ultima_vez")
    list_filter = ("estado", "tipo_excepcion")
    search_fields = ("tipo_excepcion", "archivo", "url", "mensaje")
    readonly_fields = ("huella", "traza", "primera_vez", "ultima_vez", "contador")


@admin.register(ReporteProblema)
class ReporteProblemaAdmin(admin.ModelAdmin):
    """Administración de reportes de problemas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("usuario", "empresa", "url", "estado", "fecha_reporte")
    list_filter = ("estado",)


@admin.register(ComentarioWidget)
class ComentarioWidgetAdmin(admin.ModelAdmin):
    """Administración de comentarios rápidos en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("util", "pantalla", "usuario", "empresa", "creado_en")
    list_filter = ("util",)


@admin.register(EncuestaNPS)
class EncuestaNPSAdmin(admin.ModelAdmin):
    """Administración de encuestas NPS en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("puntaje", "usuario", "empresa", "creado_en")


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    """Administración de ideas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("titulo", "estado", "autor", "empresa", "creado_en")
    list_filter = ("estado",)


@admin.register(VotoIdea)
class VotoIdeaAdmin(admin.ModelAdmin):
    """Administración de votos de ideas en /admin/ (columnas, filtros y campos de solo lectura)."""
    list_display = ("idea", "usuario", "creado_en")
