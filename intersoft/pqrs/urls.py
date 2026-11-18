"""Rutas públicas/comprador para PQRS (/pqrs/)."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.MisPQRSListView.as_view(), name="pqrs_mis_list"),
    path("nueva/", views.RadicarPQRSCompradorView.as_view(), name="pqrs_radicar"),
    path("<uuid:pk>/", views.DetallePQRSCompradorView.as_view(), name="pqrs_detalle"),
]
