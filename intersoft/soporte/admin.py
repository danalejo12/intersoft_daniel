from django.contrib import admin

from .models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, Idea, ReporteProblema, VotoIdea


@admin.register(ErrorRegistrado)
class ErrorRegistradoAdmin(admin.ModelAdmin):
    list_display = ("tipo_excepcion", "archivo", "linea", "estado", "contador", "ultima_vez")
    list_filter = ("estado", "tipo_excepcion")
    search_fields = ("tipo_excepcion", "archivo", "url", "mensaje")
    readonly_fields = ("huella", "traza", "primera_vez", "ultima_vez", "contador")


@admin.register(ReporteProblema)
class ReporteProblemaAdmin(admin.ModelAdmin):
    list_display = ("usuario", "empresa", "url", "estado", "fecha_reporte")
    list_filter = ("estado",)


@admin.register(ComentarioWidget)
class ComentarioWidgetAdmin(admin.ModelAdmin):
    list_display = ("util", "pantalla", "usuario", "empresa", "creado_en")
    list_filter = ("util",)


@admin.register(EncuestaNPS)
class EncuestaNPSAdmin(admin.ModelAdmin):
    list_display = ("puntaje", "usuario", "empresa", "creado_en")


@admin.register(Idea)
class IdeaAdmin(admin.ModelAdmin):
    list_display = ("titulo", "estado", "autor", "empresa", "creado_en")
    list_filter = ("estado",)


@admin.register(VotoIdea)
class VotoIdeaAdmin(admin.ModelAdmin):
    list_display = ("idea", "usuario", "creado_en")
