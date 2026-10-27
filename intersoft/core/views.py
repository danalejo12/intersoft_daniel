# 1. Imports de Django
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import F, Q
from django.http import JsonResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

# 2. Imports de tu propia app
from .forms import ClienteForm
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
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        # super() ya trae solo los clientes de la empresa activa (TenantMixin)
        queryset = super().get_queryset().filter(activo=True).order_by("nombre")
        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            queryset = queryset.filter(
                Q(nombre__icontains=self.q) | Q(numero_documento__icontains=self.q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        membresia = self.request.membresia
        contexto["q"] = self.q
        # La plantilla no puede llamar tiene_permiso("..."): se lo damos ya resuelto
        contexto["puede_crear"] = membresia.tiene_permiso("clientes.crear")
        contexto["puede_editar"] = membresia.tiene_permiso("clientes.editar")
        return contexto


class ClienteFormMixin:
    """Configuración compartida por crear y editar (no repetir código)."""

    model = Cliente
    form_class = ClienteForm
    template_name = "core/clientes/form.html"
    success_url = reverse_lazy("clientes_lista")
    success_message = "Cliente «%(nombre)s» guardado correctamente."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa   # llega al __init__ del formulario
        return kwargs


class ClienteCreateView(PermisoRequeridoMixin, ClienteFormMixin, SuccessMessageMixin, CreateView):
    permiso_requerido = "clientes.crear"


class ClienteUpdateView(PermisoRequeridoMixin, ClienteFormMixin, SuccessMessageMixin, UpdateView):
    permiso_requerido = "clientes.editar"