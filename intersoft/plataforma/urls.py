"""Rutas de la consola interna de plataforma (/plataforma/)."""
from django.urls import path

from datos_personales.views import PlataformaSolicitudDatosDetalleView, PlataformaSolicitudesDatosView
from pqrs.views import PlataformaPQRSDetalleView, PlataformaPQRSListView
from soporte.views import (
    PlataformaComentariosListView,
    PlataformaErrorDetalleView,
    PlataformaErroresListView,
    PlataformaIdeasListView,
)

from . import views

urlpatterns = [
    path("", views.InicioPlataformaView.as_view(), name="plataforma_inicio"),
    path("2fa/", views.PlataformaTOTPView.as_view(), name="plataforma_totp"),
    path(
        "negocios/",
        views.PlataformaNegociosView.as_view(),
        name="plataforma_negocios",
    ),
    path(
        "negocios/salir-soporte/",
        views.SalirModoSoporteView.as_view(),
        name="plataforma_salir_soporte",
    ),
    path(
        "planes-cobros/",
        views.PlanesCobrosPlataformaView.as_view(),
        name="plataforma_planes_cobros",
    ),
    path(
        "planes-cobros/planes/<uuid:pk>/",
        views.EditarPlanPlataformaView.as_view(),
        name="plataforma_editar_plan",
    ),
    path(
        "pqrs/",
        PlataformaPQRSListView.as_view(),
        name="plataforma_pqrs",
    ),
    path(
        "pqrs/<uuid:pk>/",
        PlataformaPQRSDetalleView.as_view(),
        name="plataforma_pqrs_detalle",
    ),
    path(
        "errores/",
        PlataformaErroresListView.as_view(),
        name="plataforma_errores",
    ),
    path(
        "errores/<uuid:pk>/",
        PlataformaErrorDetalleView.as_view(),
        name="plataforma_error_detalle",
    ),
    path(
        "comentarios/",
        PlataformaComentariosListView.as_view(),
        name="plataforma_comentarios",
    ),
    path(
        "ideas/",
        PlataformaIdeasListView.as_view(),
        name="plataforma_ideas",
    ),
    path("datos-personales/", PlataformaSolicitudesDatosView.as_view(), name="plataforma_datos"),
    path("datos-personales/<uuid:pk>/", PlataformaSolicitudDatosDetalleView.as_view(), name="plataforma_datos_detalle"),
    path("operacion/", views.OperacionPlataformaView.as_view(), name="plataforma_operacion"),
    path("auditoria/", views.AuditoriaPlataformaView.as_view(), name="plataforma_auditoria"),
]
