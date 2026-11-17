"""Rutas API de la aplicación suscripciones."""
from django.urls import path

from . import views

urlpatterns = [
    path("planes/", views.PlanListAPIView.as_view(), name="api_planes_lista"),
    path("suscripcion/", views.SuscripcionDetalleAPIView.as_view(), name="api_suscripcion_detalle"),
    path("suscripcion/cambiar-plan/", views.CambiarPlanAPIView.as_view(), name="api_suscripcion_cambiar_plan"),
]
