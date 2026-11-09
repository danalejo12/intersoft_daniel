from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views, views_tienda

# Todo lo que exige negocio vive bajo panel/. Los nombres de ruta no cambian.
panel_urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("quien-soy/", views.quien_soy, name="quien_soy"),

    # Clientes
    path("clientes/", views.ClienteListView.as_view(), name="clientes_lista"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="clientes_crear"),
    path("clientes/<uuid:pk>/editar/", views.ClienteUpdateView.as_view(), name="clientes_editar"),
    path("clientes/<uuid:pk>/eliminar/", views.ClienteDeleteView.as_view(), name="clientes_eliminar"),

    # Productos
    path("productos/", views.ProductoListView.as_view(), name="productos_lista"),
    path("productos/nuevo/", views.ProductoCreateView.as_view(), name="productos_crear"),
    path("productos/<uuid:pk>/", views.ProductoKardexView.as_view(), name="productos_kardex"),
    path("productos/<uuid:pk>/editar/", views.ProductoUpdateView.as_view(), name="productos_editar"),
    path("productos/<uuid:pk>/movimiento/", views.MovimientoCreateView.as_view(), name="productos_movimiento"),
    path("productos/<uuid:pk>/eliminar/", views.ProductoDeleteView.as_view(), name="productos_eliminar"),

    # Facturas
    path("facturas/", views.FacturaListView.as_view(), name="facturas_lista"),
    path("facturas/nueva/", views.FacturaCreateView.as_view(), name="facturas_crear"),
    path("facturas/<uuid:pk>/", views.FacturaDetailView.as_view(), name="facturas_detalle"),
    path("facturas/<uuid:pk>/anular/", views.FacturaAnularView.as_view(), name="facturas_anular"),
    path("facturas/<uuid:pk>/cobrar/", views.FacturaCobrarView.as_view(), name="facturas_cobrar"),

    # Pagos
    path("pagos/<uuid:pk>/resultado/", views.PagoResultadoView.as_view(), name="pagos_resultado"),
    path("pagos/<uuid:pk>/simulador/", views.PagoSimuladorView.as_view(), name="pagos_simulador"),
]

urlpatterns = [
    # Marketplace público
    path("", views_tienda.MarketplaceView.as_view(), name="marketplace"),
    path("tienda/producto/<uuid:pk>/", views_tienda.ProductoPublicoView.as_view(), name="tienda_producto"),
    path("tienda/<slug:slug>/", views_tienda.TiendaNegocioView.as_view(), name="tienda_negocio"),

    # Cuentas
    path("registro/", views_tienda.RegistroCompradorView.as_view(), name="registro"),
    path("negocio/registrar/", views_tienda.RegistrarNegocioView.as_view(), name="negocio_registrar"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("entrar/", views_tienda.despues_de_login, name="despues_login"),

    # Panel de cada negocio
    path("panel/", include(panel_urlpatterns)),

    # Wompi tiene esta dirección configurada: no se mueve
    path("webhooks/wompi/", views.WompiWebhookView.as_view(), name="wompi_webhook"),
]
