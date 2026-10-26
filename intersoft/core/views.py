# 1. Imports de Django
from django.db.models import F, Q
from django.http import JsonResponse
from django.views.generic import ListView, TemplateView

# 2. Imports de tu propia app
from .mixins import PermisoRequeridoMixin, TenantMixin
from .models import Cliente, Producto


# ---------------------------------------------------------------
# Vistas de prueba (las quitaremos más adelante)
# ---------------------------------------------------------------
def quien_soy(request):
    return JsonResponse({
        "usuario": str(request.user),
        "empresa": request.empresa.nombre if request.empresa else None,
        "rol": request.membresia.rol.nombre if request.membresia else None,
    })


# ---------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------
class DashboardView(TenantMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        empresa = self.request.empresa

        # TemplateView NO pasa por get_queryset: filtramos por empresa a mano
        productos = Producto.objects.de_empresa(empresa).filter(activo=True)

        contexto["total_clientes"] = Cliente.objects.de_empresa(empresa).filter(activo=True).count()
        contexto["total_productos"] = productos.count()
        # F("stock_minimo") compara dos columnas DENTRO de PostgreSQL
        contexto["stock_bajo"] = productos.filter(stock__lte=F("stock_minimo")).order_by("stock")
        return contexto


# ---------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------
class ClienteListView(PermisoRequeridoMixin, ListView):
    model = Cliente
    permiso_requerido = "clientes.ver"
    template_name = "core/clientes/lista.html"
    context_object_name = "clientes"   # en la