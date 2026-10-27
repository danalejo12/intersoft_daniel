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
]
