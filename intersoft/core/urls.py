from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("login/", auth_views.LoginView.as_view(template_name="core/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("quien-soy/", views.quien_soy, name="quien_soy"),
    path("clientes/", views.ClienteListView.as_view(), name="clientes_lista"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="clientes_crear"),
    path("clientes/<uuid:pk>/editar/", views.ClienteUpdateView.as_view(), name="clientes_editar"),
    path("facturas/", views.FacturaListView.as_view(), name="facturas_lista"),
    path("facturas/nueva/", views.FacturaCreateView.as_view(), name="facturas_crear"),
    path("facturas/<uuid:pk>/", views.FacturaDetailView.as_view(), name="facturas_detalle"),
    path("productos/", views.ProductoListView.as_view(), name="productos_lista"),
    path("productos/nuevo/", views.ProductoCreateView.as_view(), name="productos_crear"),
    path("productos/<uuid:pk>/", views.ProductoKardexView.as_view(), name="productos_kardex"),
    path("productos/<uuid:pk>/editar/", views.ProductoUpdateView.as_view(), name="productos_editar"),
    path("productos/<uuid:pk>/movimiento/", views.MovimientoCreateView.as_view(), name="productos_movimiento"),
]
