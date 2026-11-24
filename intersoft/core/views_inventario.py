"""Vistas del módulo de inventario: categorías, productos, movimientos de kardex y eliminación lógica."""
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import CategoriaForm, MovimientoForm, ProductoForm
from .mixins import PermisoRequeridoMixin
from . import bodegas
from .models import Bodega, Categoria, FotoProducto, MovimientoInventario, Producto
from .services import StockInsuficiente, registrar_movimiento


class EliminarLogicoView(PermisoRequeridoMixin, View):
    """Desactiva un registro sin borrarlo. Solo acepta POST."""

    http_method_names = ["post"]
    model = None
    campo_activo = "activo"
    url_lista = None

    def motivo_bloqueo(self, objeto):
        return None  # Cada subclase puede impedir la eliminación

    def post(self, request, pk):
        # Filtrar por empresa impide tocar registros de otro tenant (da 404)
        objeto = get_object_or_404(
            self.model.objects.de_empresa(request.empresa),
            pk=pk,
            **{self.campo_activo: True},
        )
        motivo = self.motivo_bloqueo(objeto)
        if motivo:
            messages.error(request, motivo)
            return redirect(self.url_lista)

        setattr(objeto, self.campo_activo, False)
        objeto.save(update_fields=[self.campo_activo, "actualizado_en"])
        messages.success(request, f"«{objeto}» se eliminó correctamente.")
        return redirect(self.url_lista)


class CategoriaListView(PermisoRequeridoMixin, ListView):
    """Lista de categorías del negocio activo. Ruta: `/panel/categorias/` («categorias_lista»). Permiso:
    `inventario.ver`.
    """
    model = Categoria
    permiso_requerido = "inventario.ver"
    template_name = "core/categorias/lista.html"
    context_object_name = "categorias"
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(activa=True)
            .annotate(total_productos=Count("productos", filter=Q(productos__activo=True)))
            .order_by("nombre")
        )
        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            queryset = queryset.filter(nombre__icontains=self.q)
        return queryset

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        membresia = self.request.membresia
        contexto["q"] = self.q
        contexto["puede_crear"] = membresia.tiene_permiso("inventario.crear")
        contexto["puede_editar"] = membresia.tiene_permiso("inventario.editar")
        contexto["puede_eliminar"] = membresia.tiene_permiso("inventario.eliminar")
        return contexto


class CategoriaFormMixin:
    """Configuración común de los formularios de categoría (plantilla, mensajes y redirección)."""
    model = Categoria
    form_class = CategoriaForm
    template_name = "core/categorias/form.html"
    success_url = reverse_lazy("categorias_lista")
    success_message = "Categoría «%(nombre)s» guardada correctamente."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs


class CategoriaCreateView(PermisoRequeridoMixin, CategoriaFormMixin, SuccessMessageMixin, CreateView):
    """Crea una categoría. Ruta: `/panel/categorias/nueva/` («categorias_crear»). Permiso: `inventario.crear`."""
    permiso_requerido = "inventario.crear"


class CategoriaUpdateView(PermisoRequeridoMixin, CategoriaFormMixin, SuccessMessageMixin, UpdateView):
    """Edita una categoría. Ruta: `/panel/categorias/<uuid:pk>/editar/` («categorias_editar»). Permiso:
    `inventario.editar`.
    """
    permiso_requerido = "inventario.editar"


class CategoriaDeleteView(EliminarLogicoView):
    """Desactiva una categoría sin borrarla (eliminación lógica). Ruta: `/panel/categorias/<uuid:pk>/eliminar/`
    («categorias_eliminar»). Permiso: `inventario.eliminar`.
    """
    model = Categoria
    campo_activo = "activa"
    permiso_requerido = "inventario.eliminar"
    url_lista = "categorias_lista"

    def motivo_bloqueo(self, objeto):
        """Impide desactivar una categoría que todavía tiene productos activos."""
        if objeto.productos.filter(activo=True).exists():
            return f"No puedes eliminar la categoría «{objeto.nombre}» porque tiene productos activos asociados."
        return None


class ProductoListView(PermisoRequeridoMixin, ListView):
    """Lista de productos del negocio activo. Ruta: `/panel/productos/` («productos_lista»). Permiso:
    `inventario.ver`.
    """
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
        contexto["puede_mover"] = membresia.tiene_permiso("inventario.movimientos")
        contexto["puede_eliminar"] = membresia.tiene_permiso("inventario.eliminar")
        return contexto


class ProductoFormMixin:
    """Configuración común de los formularios de producto, incluida la galería de fotos."""
    model = Producto
    form_class = ProductoForm
    template_name = "core/productos/form.html"
    success_url = reverse_lazy("productos_lista")
    success_message = "Producto «%(nombre)s» guardado correctamente."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa
        return kwargs

    def form_valid(self, form):
        # Producto y galería se guardan juntos: si algo falla no queda nada a medias
        with transaction.atomic():
            respuesta = super().form_valid(form)
            self.guardar_galeria(form)
        return respuesta

    def guardar_galeria(self, form):
        """Guarda las fotos nuevas de la galería y borra las quitadas (los archivos, al confirmar la transacción)."""
        quitar = list(form.cleaned_data.get("quitar_fotos") or [])
        archivos_viejos = [foto.imagen.name for foto in quitar]
        FotoProducto.objects.filter(pk__in=[foto.pk for foto in quitar], producto=self.object).delete()
        siguiente = (self.object.fotos.aggregate(m=Max("orden"))["m"] or -1) + 1
        for i, archivo in enumerate(form.cleaned_data.get("fotos_extra") or []):
            FotoProducto.objects.create(
                empresa=self.request.empresa, producto=self.object, imagen=archivo, orden=siguiente + i
            )
        # Los archivos se borran solo si la transacción se confirmó
        almacen = FotoProducto._meta.get_field("imagen").storage
        transaction.on_commit(lambda: [almacen.delete(nombre) for nombre in archivos_viejos])


class ProductoCreateView(PermisoRequeridoMixin, ProductoFormMixin, SuccessMessageMixin, CreateView):
    """Crea un producto. Ruta: `/panel/productos/nuevo/` («productos_crear»). Permiso: `inventario.crear`."""
    permiso_requerido = "inventario.crear"

    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and getattr(request, "empresa", None) is not None
            and request.membresia
            and request.membresia.tiene_permiso(self.permiso_requerido)
        ):
            from suscripciones.exceptions import LimitePlanExcedido, verificar_limite

            try:
                verificar_limite(request.empresa, "productos")
            except LimitePlanExcedido as exc:
                messages.error(
                    request,
                    f"Alcanzaste el límite de {exc.limite} productos activos de tu plan ({exc.plan_actual}). "
                    "Mejora tu plan para agregar más productos.",
                )
                return redirect("suscripcion_panel")
        return super().dispatch(request, *args, **kwargs)

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
    """Edita un producto. Ruta: `/panel/productos/<uuid:pk>/editar/` («productos_editar»). Permiso:
    `inventario.editar`.
    """
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
            self.object.movimientos.select_related("usuario", "bodega").order_by("-creado_en")[:100]
        )
        activas = list(Bodega.objects.de_empresa(self.request.empresa).filter(activa=True))
        if len(activas) > 1:
            disponibles = bodegas.existencias_por_producto
            contexto["existencias"] = [(b, disponibles(b, [self.object])[self.object.pk]) for b in activas]
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
        return self.mostrar(self.obtener_producto(pk), MovimientoForm(empresa=request.empresa))

    def post(self, request, pk):
        producto = self.obtener_producto(pk)
        form = MovimientoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            try:
                # cleaned_data trae tipo, cantidad y referencia: justo lo que pide el servicio
                registrar_movimiento(
                    empresa=request.empresa, producto=producto, usuario=request.user, **form.cleaned_data
                )
            except (StockInsuficiente, ValueError) as error:
                form.add_error("cantidad", str(error))
            else:
                messages.success(request, f"Movimiento registrado para «{producto.nombre}».")
                return redirect("productos_kardex", pk=producto.pk)
        return self.mostrar(producto, form)

    def mostrar(self, producto, form):
        return render(self.request, self.template_name, {"producto": producto, "form": form})


class ProductoDeleteView(EliminarLogicoView):
    """Desactiva un producto sin borrarlo (eliminación lógica). Ruta: `/panel/productos/<uuid:pk>/eliminar/`
    («productos_eliminar»). Permiso: `inventario.eliminar`.
    """
    model = Producto
    permiso_requerido = "inventario.eliminar"
    url_lista = "productos_lista"
