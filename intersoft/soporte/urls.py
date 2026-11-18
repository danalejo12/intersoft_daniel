"""Rutas de soporte, reportes, comentarios, NPS e ideas (/soporte/)."""
from django.urls import path

from . import views

urlpatterns = [
    path("reportar/", views.ReportarProblemaView.as_view(), name="soporte_reportar_problema"),
    path("comentario/", views.EnviarComentarioWidgetView.as_view(), name="soporte_comentario"),
    path("nps/", views.EnviarNPSView.as_view(), name="soporte_nps"),
    path("ideas/", views.IdeasListaView.as_view(), name="soporte_ideas"),
    path("ideas/<uuid:pk>/votar/", views.VotarIdeaView.as_view(), name="soporte_votar_idea"),
]
