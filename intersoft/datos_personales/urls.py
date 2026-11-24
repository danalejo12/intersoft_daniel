"""Rutas públicas y del titular para la protección de datos personales."""
from django.urls import path

from . import views

urlpatterns = [
    path("privacidad/", views.PoliticaPrivacidadView.as_view(), name="legal_privacidad"),
    path("privacidad/autorizar/", views.AutorizarDatosView.as_view(), name="datos_autorizar"),
    path("mis-datos/", views.MisDatosView.as_view(), name="mis_datos"),
    path("mis-datos/descargar/", views.DescargarMisDatosView.as_view(), name="mis_datos_descargar"),
]
