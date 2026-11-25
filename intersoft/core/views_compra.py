"""Carrito, compra, pedidos y opiniones del marketplace."""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from . import carrito, compras
from .forms_tienda import ComentarioForm, DatosEnvioForm
from .marketplace import empresas_publicas, productos_publicos
from .models import Comentario, Orden, Pedido
from .pagos import PagoNoPermitido, crear_pago_pedido, url_checkout
from .redirecciones import destino_seguro
from .services import StockInsuficiente

# ---------------------------------------------------------------
# Carrito
# ---------------------------------------------------------------


def _entero(valor, por_defecto):
    """Convierte a entero o devuelve el valor por defecto."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return por_defecto


def _avisar(request, avisos):
    """Muestra cada aviso (por ejemplo, cambios de stock) como mensaje de advertencia."""
    for aviso in avisos:
        messages.warning(request, aviso)


class CarritoView(TemplateView):
    """Carrito del marketplace agrupado por negocio; corrige cantidades si cambió el stock. Ruta: `/carrito/`
    («carrito»).
    """
    template_name = "core/tienda/carrito.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["grupos"], avisos = carrito.grupos(self.request)
        _avisar(self.request, avisos)
        return contexto


class AgregarAlCarritoView(View):
    """Agrega un producto al carrito sin pasar del stock (responde JSON si la petición es AJAX). Ruta:
    `/carrito/agregar/<uuid:pk>/` («carrito_agregar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        producto = get_object_or_404(productos_publicos(), pk=pk)
        if not producto.empresa.compra_en_linea:
            mensaje = "Compra en línea no disponible para este negocio."
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": False, "mensaje": mensaje,
                                     "cantidad_total": carrito.cantidad_total(request)}, status=409)
            messages.warning(request, mensaje)
            return redirect("tienda_producto", pk=producto.pk)
        pedida = max(_entero(request.POST.get("cantidad"), 1), 1)
        agregadas = carrito.agregar(request, producto, pedida)

        if agregadas == pedida:
            ok, mensaje = True, f"¡Listo! Agregamos {producto.nombre} a tu carrito."
        elif agregadas:
            ok, mensaje = True, f"Agregamos a tu carrito las unidades disponibles de {producto.nombre}."
        elif producto.disponible <= 0:
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
        return HttpResponseRedirect(destino_seguro(request) or reverse("carrito"))


class ActualizarCarritoView(View):
    """Cambia la cantidad de un producto del carrito, ajustándola a lo disponible. Ruta:
    `/carrito/actualizar/<uuid:pk>/` («carrito_actualizar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        producto = productos_publicos().filter(pk=pk).first()
        if producto is None:
            carrito.quitar(request, pk)
        elif (not carrito.actualizar(request, producto, _entero(request.POST.get("cantidad"), 1))
              and _entero(request.POST.get("cantidad"), 1) > 0):
            messages.warning(request, f"Ajustamos {producto.nombre} a las unidades disponibles.")
        return redirect("carrito")


class QuitarDelCarritoView(View):
    """Quita un producto del carrito. Ruta: `/carrito/quitar/<uuid:pk>/` («carrito_quitar»)."""
    http_method_names = ["post"]

    def post(self, request, pk):
        carrito.quitar(request, pk)
        messages.info(request, "Quitamos el producto de tu carrito.")
        return redirect("carrito")


# ---------------------------------------------------------------
# Compra
# ---------------------------------------------------------------


class DatosEnvioMixin(LoginRequiredMixin):
    """Comparte la carga de datos de envío entre los checkouts (recuerda los de la última compra)."""
    login_url = "registro"  # quien no tiene cuenta la crea y vuelve aquí con su carrito intacto
    form_class = DatosEnvioForm

    def get_initial(self):
        usuario = self.request.user
        ultimo = Pedido.objects.filter(comprador=usuario).first()
        if ultimo is None:
            return {"nombre": usuario.get_full_name(), "email": usuario.email}
        # Quien ya compró no debería escribir todo otra vez
        return {
            "nombre": ultimo.nombre, "email": ultimo.email, "telefono": ultimo.telefono,
            "tipo_documento": ultimo.tipo_documento, "numero_documento": ultimo.numero_documento,
            "departamento": ultimo.departamento, "ciudad": ultimo.ciudad,
            "direccion": ultimo.direccion, "indicaciones": ultimo.indicaciones,
        }

    def stock_cambio(self):
        # El mensaje del servicio puede incluir el stock exacto, que es información interna del negocio
        """Avisa que alguien se llevó el stock y vuelve al carrito (sin revelar cantidades)."""
        messages.warning(
            self.request,
            "Otra persona acaba de llevarse alguno de tus productos. Revisa tu carrito y seguimos.",
        )
        return redirect("carrito")


class CheckoutTodoView(DatosEnvioMixin, FormView):
    """Un solo checkout para todos los negocios del carrito que venden en línea."""
    template_name = "core/tienda/checkout_todo.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        grupos, avisos = carrito.grupos(request)
        _avisar(request, avisos)
        self.grupos = [g for g in grupos if g["negocio"].compra_en_linea]
        self.sin_compra_en_linea = [g for g in grupos if not g["negocio"].compra_en_linea]
        if not self.grupos or (avisos and request.method == "POST"):
            if not self.grupos:
                messages.info(request, "No tienes productos que se puedan comprar en línea.")
            return redirect("carrito")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["grupos"] = self.grupos
        contexto["sin_compra_en_linea"] = self.sin_compra_en_linea
        contexto["total"] = sum((g["total"] for g in self.grupos), Decimal("0"))
        return contexto

    def form_valid(self, form):
        try:
            orden = compras.crear_orden(usuario=self.request.user, grupos=self.grupos, datos=form.cleaned_data)
        except PagoNoPermitido as error:
            messages.warning(self.request, str(error))
            return redirect("carrito")
        except (StockInsuficiente, ValueError):
            return self.stock_cambio()
        for grupo in self.grupos:
            carrito.quitar_lineas(self.request, grupo["lineas"])
        pedidos = list(orden.pedidos.all())
        if len(pedidos) == 1:
            return redirect("pedido_detalle", pk=pedidos[0].pk)
        return redirect("orden_detalle", pk=orden.pk)


class CheckoutView(DatosEnvioMixin, FormView):
    """Checkout de un solo negocio."""
    template_name = "core/tienda/checkout.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.negocio = get_object_or_404(empresas_publicas(), slug=kwargs["slug"])
        if not self.negocio.compra_en_linea:
            messages.warning(request, "Compra en línea no disponible para este negocio.")
            return redirect("carrito")
        self.grupo, avisos = carrito.grupo_de(request, self.negocio)
        _avisar(request, avisos)
        # Si algo cambió justo al confirmar, la persona debe ver el total nuevo antes de seguir
        if self.grupo is None or (avisos and request.method == "POST"):
            if self.grupo is None:
                messages.info(request, "Ya no tienes productos de este negocio en tu carrito.")
            return redirect("carrito")
        return super().dispatch(request, *args, **kwargs)

    def _resumen_con_cupon(self, codigo_cupon):
        """Evalúa el cupón (si hay) y calcula el resumen actualizado para el checkout."""
        from .impuestos import CENTAVOS
        from .pasarelas import configuracion_activa
        from .tarifas import cargo_pasarela

        codigo = (codigo_cupon or "").strip().upper()
        grupo = dict(self.grupo)
        cupon_obj = None
        descuento = Decimal("0.00")
        cupon_error = ""
        if codigo:
            total_productos = (grupo["subtotal"] + grupo["iva"]).quantize(CENTAVOS)
            try:
                cupon_obj, descuento = compras.evaluar_cupon(
                    negocio=self.negocio,
                    codigo=codigo,
                    total_productos=total_productos,
                )
            except compras.OperacionNoPermitida as error:
                cupon_error = str(error)
            else:
                total_neto = max(total_productos - descuento, Decimal("0.00")).quantize(CENTAVOS)
                peso = sum((l["producto"].peso_gramos or 0) * l["cantidad"] for l in grupo["lineas"])
                costo_envio = compras.calcular_costo_envio(
                    negocio=self.negocio,
                    total_productos=total_neto,
                    peso_total_gramos=peso,
                )
                antes = (total_neto + costo_envio).quantize(CENTAVOS)
                config = configuracion_activa(self.negocio.pk)
                cargo = cargo_pasarela(antes, config=config) if antes > 0 else Decimal("0.00")
                grupo["costo_envio"] = costo_envio
                grupo["cargo_pasarela"] = cargo
                grupo["total"] = (antes + cargo).quantize(CENTAVOS)
        return grupo, cupon_obj, descuento, codigo, cupon_error

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        codigo_req = self.request.POST.get("cupon") if self.request.method == "POST" else self.request.GET.get("cupon", "")
        grupo, cupon_obj, descuento, codigo, cupon_error = self._resumen_con_cupon(codigo_req)
        contexto["grupo"] = grupo
        contexto["negocio"] = self.negocio
        contexto["cupon_aplicado"] = cupon_obj
        contexto["cupon_codigo"] = cupon_obj.codigo if cupon_obj else codigo
        contexto["descuento"] = descuento
        contexto["cupon_error"] = cupon_error
        return contexto

    def form_valid(self, form):
        codigo_cupon = (self.request.POST.get("cupon") or "").strip().upper()
        try:
            pedido = compras.crear_pedido(
                usuario=self.request.user,
                negocio=self.negocio,
                lineas=self.grupo["lineas"],
                datos=form.cleaned_data,
                codigo_cupon=codigo_cupon,
            )
        except compras.OperacionNoPermitida as error:
            messages.warning(self.request, str(error))
            return self.render_to_response(self.get_context_data(form=form))
        except PagoNoPermitido as error:
            messages.warning(self.request, str(error))
            return redirect("carrito")
        except (StockInsuficiente, ValueError):
            return self.stock_cambio()
        carrito.quitar_lineas(self.request, self.grupo["lineas"])
        return redirect("pedido_detalle", pk=pedido.pk)


# ---------------------------------------------------------------
# Pedidos: cada persona solo ve los suyos
# ---------------------------------------------------------------


def _mi_pedido(request, pk):
    return get_object_or_404(Pedido.objects.filter(comprador=request.user).select_related("empresa"), pk=pk)


class MisPedidosView(LoginRequiredMixin, ListView):
    """Listado. Ruta: `/pedidos/` («mis_pedidos»)."""
    template_name = "core/tienda/mis_pedidos.html"
    context_object_name = "pedidos"
    paginate_by = 10

    def get_queryset(self):
        qs = (
            Pedido.objects.filter(comprador=self.request.user)
            .select_related("empresa")
            .prefetch_related("lineas__producto", "pagos")
            .order_by("-creado_en")
        )
        self.estado_filtro = self.request.GET.get("estado", "").strip()
        self.q = self.request.GET.get("q", "").strip()
        if self.estado_filtro == "pendiente":
            qs = qs.filter(estado=Pedido.Estado.PENDIENTE)
        elif self.estado_filtro == "pagado":
            qs = qs.filter(estado=Pedido.Estado.PAGADO)
        elif self.estado_filtro == "enviado":
            qs = qs.filter(estado=Pedido.Estado.PAGADO, estado_envio=Pedido.EstadoEnvio.ENVIADO)
        elif self.estado_filtro == "entregado":
            qs = qs.filter(estado=Pedido.Estado.PAGADO, estado_envio=Pedido.EstadoEnvio.ENTREGADO)

        if self.q:
            filtro_q = Q(empresa__nombre__icontains=self.q) | Q(ciudad__icontains=self.q)
            if self.q.lstrip("#").isdigit():
                filtro_q |= Q(numero=int(self.q.lstrip("#")))
            qs = qs.filter(filtro_q)
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        base = Pedido.objects.filter(comprador=self.request.user)
        contexto["estado_filtro"] = self.estado_filtro
        contexto["q"] = self.q
        contexto["resumen_pedidos"] = {
            "total": base.count(),
            "pendientes": base.filter(estado=Pedido.Estado.PENDIENTE).count(),
            "pagados": base.filter(estado=Pedido.Estado.PAGADO).count(),
            "entregados": base.filter(estado=Pedido.Estado.PAGADO, estado_envio=Pedido.EstadoEnvio.ENTREGADO).count(),
        }
        return contexto


class PedidoDetalleView(LoginRequiredMixin, DetailView):
    """Detalle. Ruta: `/pedidos/<uuid:pk>/` («pedido_detalle»)."""
    template_name = "core/tienda/pedido.html"
    context_object_name = "pedido"

    def get_queryset(self):
        return (
            Pedido.objects.filter(comprador=self.request.user)
            .select_related("factura", "empresa")
            .prefetch_related("lineas__producto")
        )

    def get_object(self, queryset=None):
        pedido = super().get_object(queryset)
        compras.actualizar_pagos(pedido, transaccion_id=self.request.GET.get("id", ""))
        return pedido


class OrdenDetalleView(LoginRequiredMixin, DetailView):
    """Una compra de varios negocios: un botón Pagar por negocio y el estado de cada uno."""
    template_name = "core/tienda/orden.html"
    context_object_name = "orden"

    def get_queryset(self):
        return Orden.objects.filter(comprador=self.request.user)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        pedidos = list(self.object.pedidos.select_related("empresa").prefetch_related("lineas__producto")
                       .order_by("empresa__nombre"))
        # Wompi devuelve ?id=<transacción>; solo se usa con el pedido que se acaba de pagar
        recien_pagado = self.request.GET.get("pedido", "")
        for pedido in pedidos:
            transaccion = self.request.GET.get("id", "") if str(pedido.pk) == recien_pagado else ""
            compras.actualizar_pagos(pedido, transaccion_id=transaccion)
            pedido.refresh_from_db()
        contexto["pedidos"] = pedidos
        contexto["total"] = sum((p.total for p in pedidos), Decimal("0"))
        contexto["por_pagar"] = [p for p in pedidos if p.estado == Pedido.Estado.PENDIENTE]
        contexto["pagados"] = [p for p in pedidos if p.estado == Pedido.Estado.PAGADO]
        return contexto


class EstadoPedidoView(LoginRequiredMixin, View):
    """La página del pedido lo consulta mientras la persona paga en la otra pestaña."""

    def get(self, request, pk):
        pedido = _mi_pedido(request, pk)
        compras.actualizar_pagos(pedido)
        return JsonResponse({"estado": pedido.estado_compra})


class PagarPedidoView(LoginRequiredMixin, View):
    """Crea el intento de pago del pedido y redirige al checkout de Wompi del negocio. Ruta:
    `/pedidos/<uuid:pk>/pagar/` («pedido_pagar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = _mi_pedido(request, pk)
        compras.actualizar_pagos(pedido, forzar=True)  # evita cobrar dos veces si un intento ya se aprobó
        try:
            pago = crear_pago_pedido(pedido=pedido)
        except PagoNoPermitido as error:
            messages.info(request, str(error))
            return redirect("pedido_detalle", pk=pedido.pk)
        if pedido.orden_id and pedido.orden.pedidos.count() > 1:
            # Compra de varios negocios: al volver de Wompi sigue con los demás pagos
            volver = request.build_absolute_uri(
                f"{reverse('orden_detalle', args=[pedido.orden_id])}?pedido={pedido.pk}")
        else:
            volver = request.build_absolute_uri(reverse("pedido_detalle", args=[pedido.pk]))
        return redirect(url_checkout(pago=pago, redirect_url=volver))


class CancelarPedidoView(LoginRequiredMixin, View):
    """Cancela un pedido pendiente y devuelve su stock (si Wompi no lo aprobó ya). Ruta:
    `/pedidos/<uuid:pk>/cancelar/` («pedido_cancelar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = _mi_pedido(request, pk)
        try:
            compras.cancelar_pedido(pedido)
            messages.info(request, "Cancelamos tu pedido. Aquí seguimos cuando quieras volver.")
        except compras.OperacionNoPermitida as error:
            messages.warning(request, str(error))
        return redirect("pedido_detalle", pk=pedido.pk)


class RenovarReservaView(LoginRequiredMixin, View):
    """Renueva la reserva de stock de un pedido pendiente o vencido, dentro del máximo permitido. Ruta:
    `/pedidos/<uuid:pk>/renovar/` («pedido_renovar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = _mi_pedido(request, pk)
        try:
            compras.renovar_reserva(pedido)
            messages.success(request, "¡Listo! Renovamos tu reserva. Ya puedes pagar con calma.")
        except compras.OperacionNoPermitida as error:
            messages.warning(request, str(error))
        return redirect("pedido_detalle", pk=pedido.pk)


# ---------------------------------------------------------------
# Opiniones
# ---------------------------------------------------------------


class ComentarView(View):
    """Publica la opinión de un comprador sobre un producto (la compra verificada la calcula el servidor). Ruta:
    `/tienda/producto/<uuid:pk>/comentar/` («comentar»).
    """
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
    """Eliminación lógica: desactiva sin borrar. Ruta: `/comentarios/<uuid:pk>/eliminar/` («comentario_eliminar»)."""
    http_method_names = ["post"]

    def post(self, request, pk):
        comentario = get_object_or_404(Comentario, pk=pk, autor=request.user)
        producto_id = comentario.producto_id
        comentario.delete()
        messages.info(request, "Eliminamos tu opinión.")
        return HttpResponseRedirect(f"{reverse('tienda_producto', args=[producto_id])}#comentarios")


class FavoritosListView(LoginRequiredMixin, View):
    """Lista los productos guardados como favoritos por el comprador."""

    def get(self, request):
        from .models import Favorito

        favoritos = (
            Favorito.objects.filter(usuario=request.user, producto__activo=True, producto__empresa__activa=True)
            .select_related("producto", "producto__empresa")
            .order_by("-creado_en")
        )
        return render(request, "core/tienda/favoritos.html", {"favoritos": favoritos})


class ToggleFavoritoView(LoginRequiredMixin, View):
    """Agrega o quita un producto de los favoritos del usuario."""

    http_method_names = ["post"]

    def post(self, request, pk):
        from .models import Favorito

        producto = get_object_or_404(productos_publicos(), pk=pk)
        fav, creado = Favorito.objects.get_or_create(usuario=request.user, producto=producto)
        if creado:
            messages.success(request, f"Guardamos «{producto.nombre}» en tus favoritos.")
        else:
            fav.delete()
            messages.info(request, f"Quitamos «{producto.nombre}» de tus favoritos.")
        return redirect("tienda_producto", pk=producto.pk)


class VolverAComprarView(LoginRequiredMixin, View):
    """Recarga al carrito los ítems disponibles de un pedido anterior del comprador."""

    http_method_names = ["post"]

    def post(self, request, pk):
        pedido = get_object_or_404(Pedido, pk=pk, comprador=request.user)
        detalles = list(pedido.lineas.all())
        disponibles = {
            p.pk: p for p in productos_publicos().filter(pk__in=[d.producto_id for d in detalles])
        }
        agregados = 0
        sin_stock = 0
        for d in detalles:
            prod = disponibles.get(d.producto_id)
            if not prod or (prod.disponible or 0) <= 0:
                sin_stock += 1
                continue
            cantidad = min(d.cantidad, prod.disponible)
            if cantidad > 0:
                carrito.agregar(request, prod, cantidad)
                agregados += 1

        if agregados:
            msg = f"Agregamos {agregados} producto(s) de tu pedido #{pedido.numero} al carrito."
            if sin_stock:
                msg += f" ({sin_stock} sin disponibilidad actual)."
            messages.success(request, msg)
        else:
            messages.warning(request, "Ninguno de los productos de este pedido tiene stock disponible en este momento.")
        return redirect("carrito")

