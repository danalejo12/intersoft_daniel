"""Rutas API de la aplicación suscripciones y documentación OpenAPI/Swagger."""
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from . import views

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api_schema"), name="api_docs"),
    path("planes/", views.PlanListAPIView.as_view(), name="api_planes_lista"),
    path("suscripcion/", views.SuscripcionDetalleAPIView.as_view(), name="api_suscripcion_detalle"),
    path("suscripcion/cambiar-plan/", views.CambiarPlanAPIView.as_view(), name="api_suscripcion_cambiar_plan"),
]
