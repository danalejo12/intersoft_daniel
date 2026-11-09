"""Carrito, compra, pedidos y opiniones del marketplace."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from . import carrito, compras
from .forms_tienda import ComentarioForm, DatosEnvioForm
from .marketplace import empresas_publicas, productos_publicos
from .models import Comentario, Pedido
from .pagos import PagoNoPermitido, crear_pago, url_checkout
from .services import StockInsuficiente
from .views_tienda import _destino_seguro

# ---------------------------------------------------------------
# Carrito
# ---------------------------------------------------------------


def _entero(valor, por_defecto):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return por_defecto


def _avisar(request, avisos):
    for aviso in avisos:
        messages.warning(request, aviso)


class CarritoView(TemplateView):
    template_name = "core/tienda/carrito.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["grupos"], avisos = carrito.grupos(self.request)
        _avisar(self.request, avisos)
        return contexto


class AgregarAlCarritoView(View):
    http_method_names = ["post"]

    def post(self, request, pk):
        producto = get_object_or_404(productos_publicos(), pk=pk)
        pedida = max(_entero(request.POST.get("cantidad"), 1), 1)
        agregadas = carrito.agregar(request, producto, pedida)

        if agregadas == pedida:
            ok, mensaje = True, f"¡Listo! Agregamos {producto.nombre} a tu carrito."
        elif agregadas:
            ok, mensaje = True, f"Agregamos a tu carrito las unidades disponibles de {producto.nombre}."
        elif producto.stock <= 0:
            ok, mensaje = False, f"Lo sentimos, {producto.nombre} se acaba de agotar."
        else:
            ok, mensaje = False, f"Ya tienes en tu carrito todas las unidades disponibles de {producto.nombre}."

        if request.POST.get("comprar_ahora") and carrito.cantidad_total(request):
            return redirect("checkout", slug=producto.empresa.slug)

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"ok": ok, "mensaje": mensaje, "cantidad_total": carrito.cantidad_total(request)},
                status=200 if ok else 409,
            )

        (messages.success if ok else messages.warning)(request, mensaje)
        return HttpResponseRedirect(_destino_seguro(request) or reverse("carrito"))


class ActualizarCarritoView(View):
    http_method_names = ["post"]

    def post(self, request, pk):
        producto = productos_publicos().filter(pk=pk).first()
        if producto is None:
            carrito.quitar(request, pk)
        elif not carrito.actualizar(request, producto, _entero(request.POST.get("cantidad"), 1)):
            if _entero(request.POST.get("cantidad"), 1) > 0:
                messages.warning(request, f"Ajustamos {producto.nombre} a las unidades disponibles.")
        return redirect("carrito")


class QuitarDelCarritoView(View):
    http_method_names = ["post"]

    def post(self, request, pk):
        carrito.quitar(request, pk)
        messages.info(request, "Quitamos el producto de tu carrito.")
        return redirect("carrito")


# ---------------------------------------------------------------
# Compra
# ---------------------------------------------------------------


class CheckoutView(LoginRequiredMixin, FormView):
    login_url = "registro"  # quien no tiene cuenta la crea y vuelve aquí con su carrito intacto
    template_name = "core/tienda/checkout.html"
    form_class = DatosEnvioForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.negocio = get_object_or_404(empresas_publicas(), slug=kwargs["slug"])
        self.grupo, avisos = carrito.grupo_de(request, self.negocio)
        _avisar(request, avisos)
        # Si algo cambió justo al confirmar, la persona debe ver el total nuevo antes de seguir
        if self.grupo is None or (avisos and request.method == "POST"):
            if self.grupo is None:
                messages.info(request, "Ya no tienes productos de este negocio en tu carrito.")
            return redirect("carrito")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        usuario = self.request.user
        ultimo = Pedido.objects.filter(comprador=usuario).select_related("factura__cliente").first()
        if ultimo is None:
            return {"nombre": usuario.get_full_name(), "email": usuario.email}
        # Quien ya compró no debería escribir todo otra vez
        cliente = ultimo.factura.cliente
        return {
            "nombre": ultimo.nombre, "email": ultimo.email, "telefono": ultimo.telefono,
            "tipo_documento": cliente.tipo_documento, "numero_documento": cliente.numero_documento,
            "departamento": ultimo.departamento, "ciudad": ultimo.ciudad,
            "direccion": ultimo.direccion, "indicaciones": ultimo.indicaciones,
        }

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["grupo"] = self.grupo
        contexto["negocio"] = self.negocio
        return contexto

    def form_valid(self, form):
        try:
            pedido = compras.crear_pedido(
                usuario=self.request.user,
                negocio=self.negocio,
                lineas=self.grupo["lineas"],
                datos=form.cleaned_data,
            )
        except (StockInsuficiente, ValueError):
            # El mensaje del servicio incluye el stock exacto, que es información interna del negocio
            messages.warning(
                self.request,
                "Otra persona acaba de llevarse alguno de tus productos. Revisa tu carrito y seguimos.",
            )
            return redirect("carrito")
        carrito.quitar_lineas(self.request, self.grupo["lineas"])
        return redirect("pedido_detalle", pk=pedido.pk)


# ---------------------------------------------------------------
# Pedidos: cada persona solo ve los suyos
# ---------------------------------------------------------------


def _mi_pedido(request, pk):
    return get_object_or_404(
        Pedido.objects.filter(comprador=request.user).select_related("factura", "empresa"), pk=pk
    )


class MisPedidosView(LoginRequiredMixin, ListView):
    template_name = "core/tienda/mis_pedidos.html"
    context_object_name = "pedidos"
    paginate_by = 10

    def get_queryset(self):
        return Pedido.objects.filter(comprador=self.request.user).select_related("factura", "empresa")


class PedidoDetalleView(LoginRequiredMixin, DetailView):
    template_name = "core/tienda/pedido.html"
    context_object_name = "pedido"

    def get_queryset(self):
        return (
            Pedido.objects.filter(comprador=self.request.user)
            .select_related("factura", "empresa")
            .prefetch_related("factura__detalles__producto")
        )

    def get_object(self, queryset=None):
        pedido = super().get_object(queryset)
        compras.actualizar_pagos(pedido, transaccion_id=self.request.GET.get("id", ""))
        return pedido


class EstadoPedidoView(LoginRequiredMixin, View):
    """La página del pedido lo consulta mientras la persona paga en la otra pestaña."""

    def get(self, request, pk):
        pedido = _mi_pedido(request, pk)
        compras.actualizar_pagos(pedido)
        return JsonResponse({"estado": pedido.estado_compra})


class PagarPedidoView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = _mi_pedido(request, pk)
        compras.actualizar_pagos(pedido)  # evita cobrar dos veces si un intento ya se aprobó
        try:
            pago = crear_pago(factura=pedido.factura)
        except PagoNoPermitido as error:
            messages.info(request, str(error))
            return redirect("pedido_detalle", pk=pedido.pk)
        volver = request.build_absolute_uri(reverse("pedido_detalle", args=[pedido.pk]))
        return redirect(url_checkout(pago=pago, redirect_url=volver))


class CancelarPedidoView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = _mi_pedido(request, pk)
        try:
            compras.cancelar_pedido(pedido)
            messages.info(request, "Cancelamos tu pedido. Aquí seguimos cuando quieras volver.")
        except ValueError as error:
            messages.warning(request, str(error))
        return redirect("pedido_detalle", pk=pedido.pk)


# ---------------------------------------------------------------
# Opiniones
# ---------------------------------------------------------------


class ComentarView(View):
    http_method_names = ["post"]

    def post(self, request, pk):
        producto = get_object_or_404(productos_publicos(), pk=pk)
        volver = reverse("tienda_producto", args=[producto.pk])
        if not request.user.is_authenticated:
            return redirect_to_login(volver)

        form = ComentarioForm(request.POST)
        if form.is_valid():
            compras.guardar_comentario(
                usuario=request.user,
                producto=producto,
                calificacion=form.cleaned_data["calificacion"],
                texto=form.cleaned_data["texto"],
            )
            messages.success(request, "¡Gracias por tu opinión! Ayuda a otras personas a decidir.")
        else:
            for errores in form.errors.values():
                messages.warning(request, errores[0])
                break
        return HttpResponseRedirect(f"{volver}#comentarios")


class EliminarComentarioView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        comentario = get_object_or_404(Comentario, pk=pk, autor=request.user)
        producto_id = comentario.producto_id
        comentario.delete()
        messages.info(request, "Eliminamos tu opinión.")
        return HttpResponseRedirect(f"{reverse('tienda_producto', args=[producto_id])}#comentarios")
