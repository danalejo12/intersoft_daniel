# 1. Imports de Python
from datetime import date, timedelta

# 2. Imports de Django
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

# 3. Imports de tu propia app
from .forms import ClienteForm, FacturaForm, LineasFacturaFormSet, MovimientoForm, ProductoForm
from .mixins import PermisoRequeridoMixin, TenantMixin
from .models import Cliente, Factura, MovimientoInventario, Producto
from .services import StockInsuficiente, crear_factura, registrar_movimiento
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

# ---------------------------------------------------------------
# Facturas
# ---------------------------------------------------------------
class FacturaListView(PermisoRequeridoMixin, ListView):
    model = Factura
    permiso_requerido = "ventas.ver"
    template_name = "core/facturas/lista.html"
    context_object_name = "facturas"
    paginate_by = 20

    def get_queryset(self):
        # select_related trae el cliente en la MISMA consulta (evita N+1)
        return super().get_queryset().select_related("cliente").order_by("-numero")


class FacturaDetailView(PermisoRequeridoMixin, DetailView):
    model = Factura
    permiso_requerido = "ventas.ver"
    template_name = "core/facturas/detalle.html"
    context_object_name = "factura"

    def get_queryset(self):
        # prefetch_related trae TODAS las líneas con su producto en una sola consulta extra
        return (
            super().get_queryset()
            .select_related("cliente", "creada_por")
            .prefetch_related("detalles__producto")
        )


class FacturaCreateView(PermisoRequeridoMixin, View):
    """Vista manual (View): maneja DOS formularios a la vez, algo que CreateView no hace."""

    permiso_requerido = "ventas.crear"
    template_name = "core/facturas/form.html"

    def get(self, request):
        form = FacturaForm(empresa=request.empresa)
        lineas = LineasFacturaFormSet(form_kwargs={"empresa": request.empresa})
        return self.mostrar(form, lineas)

    def post(self, request):
        empresa = request.empresa
        form = FacturaForm(request.POST, empresa=empresa)
        lineas = LineasFacturaFormSet(request.POST, form_kwargs={"empresa": empresa})

        # Validamos los dos POR SEPARADO para que ambos muestren sus errores
        form_ok = form.is_valid()
        lineas_ok = lineas.is_valid()

        if form_ok and lineas_ok:
            # Cada fila llena trae {"producto": <Producto>, "cantidad": n}: justo lo que pide el servicio
            items = [linea.cleaned_data for linea in lineas if linea.cleaned_data]
            try:
                factura = crear_factura(
                    empresa=empresa,
                    usuario=request.user,
                    cliente=form.cleaned_data["cliente"],
                    items=items,
                )
            except StockInsuficiente as error:
                messages.error(request, str(error))   # se muestra y se vuelve a pintar el formulario
            else:
                messages.success(request, f"Factura N.º {factura.numero} creada correctamente.")
                return redirect("facturas_detalle", pk=factura.pk)   # Post/Redirect/Get

        return self.mostrar(form, lineas)

    def mostrar(self, form, lineas):
        return render(self.request, self.template_name, {"form": form, "lineas": lineas})

# ---------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------
class ProductoListView(PermisoRequeridoMixin, ListView):
    model = Producto
    permiso_requerido = "inventario.ver"
    template_name = "core/productos/lista.html"
    context_object_name = "productos"
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().filter(activo=True).select_related("categoria").order_by("nombre")
        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            queryset = queryset.filter(Q(nombre__icontains=self.q) | Q(codigo__icontains=self.q))
        # ?bajo=1 -> solo productos en o por debajo del mínimo
        self.solo_bajo = self.request.GET.get("bajo") == "1"
        if self.solo_bajo:
            queryset = queryset.filter(stock__lte=F("stock_minimo"))
        return queryset

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        membresia = self.request.membresia
        contexto["q"] = self.q
        contexto["solo_bajo"] = self.solo_bajo
        contexto["puede_crear"] = membresia.tiene_permiso("inventario.crear")
        contexto["puede_editar"] = membresia.tiene_permiso("inventario.editar")
        return contexto


class ProductoFormMixin:
    model = Producto
    form_class = ProductoForm
    template_name = "core/productos/form.html"
    success_url = reverse_lazy("productos_lista")
    success_message = "Producto «%(nombre)s» guardado correctamente."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs


class ProductoCreateView(PermisoRequeridoMixin, ProductoFormMixin, SuccessMessageMixin, CreateView):
    permiso_requerido = "inventario.crear"

    def form_valid(self, form):
        # Producto + entrada inicial: TODO O NADA
        with transaction.atomic():
            respuesta = super().form_valid(form)   # guarda el producto (stock 0)
            cantidad = form.cleaned_data.get("stock_inicial") or 0
            if cantidad > 0:
                registrar_movimiento(
                    empresa=self.request.empresa,
                    producto=self.object,           # el producto recién creado
                    tipo=MovimientoInventario.Tipo.ENTRADA,
                    cantidad=cantidad,
                    usuario=self.request.user,
                    referencia="Stock inicial",
                )
        return respuesta


class ProductoUpdateView(PermisoRequeridoMixin, ProductoFormMixin, SuccessMessageMixin, UpdateView):
    permiso_requerido = "inventario.editar"


class ProductoKardexView(PermisoRequeridoMixin, DetailView):
    """El kardex: historial de TODOS los movimientos de un producto."""

    model = Producto
    permiso_requerido = "inventario.ver"
    template_name = "core/productos/kardex.html"
    context_object_name = "producto"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["movimientos"] = (
            self.object.movimientos.select_related("usuario").order_by("-creado_en")[:100]
        )
        contexto["puede_mover"] = self.request.membresia.tiene_permiso("inventario.movimientos")
        return contexto


class MovimientoCreateView(PermisoRequeridoMixin, View):
    """Registrar una entrada o un ajuste de stock para un producto."""

    permiso_requerido = "inventario.movimientos"
    template_name = "core/productos/movimiento.html"

    def obtener_producto(self, pk):
        # Filtramos por empresa: un producto de otra empresa responde 404
        return get_object_or_404(Producto, pk=pk, empresa=self.request.empresa, activo=True)

    def get(self, request, pk):
        return self.mostrar(self.obtener_producto(pk), MovimientoForm())

    def post(self, request, pk):
        producto = self.obtener_producto(pk)
        form = MovimientoForm(request.POST)
        if form.is_valid():
            try:
                # cleaned_data trae tipo, cantidad y referencia: justo lo que pide el servicio
                registrar_movimiento(
                    empresa=request.empresa, producto=producto, usuario=request.user, **form.cleaned_data
                )
            except StockInsuficiente as error:
                form.add_error("cantidad", str(error))
            else:
                messages.success(request, f"Movimiento registrado para «{producto.nombre}».")
                return redirect("productos_kardex", pk=producto.pk)
        return self.mostrar(producto, form)

    def mostrar(self, producto, form):
        return render(self.request, self.template_name, {"producto": producto, "form": form})