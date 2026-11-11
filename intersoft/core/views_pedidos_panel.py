"""Panel del comercio para gestionar pedidos del marketplace: liquidación, logística y reembolsos."""
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import redirect
from django.views.generic import DetailView, ListView

from . import reservas
from .mixins import PermisoRequeridoMixin
from .models import Pedido


def _puede_reembolsar(membresia):
    return membresia.tiene_permiso("ventas.anular") or membresia.tiene_permiso("tesoreria.gestionar")


def _puede_gestionar_envio(membresia):
    return any(
        membresia.tiene_permiso(p)
        for p in ("ventas.crear", "inventario.movimientos", "ventas.anular")
    )


class PedidoPanelListView(PermisoRequeridoMixin, ListView):
    model = Pedido
    permiso_requerido = "ventas.ver"
    template_name = "core/pedidos_panel/lista.html"
    context_object_name = "pedidos"
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("comprador", "factura")
            .order_by("-numero")
        )
        self.estado_filtro = self.request.GET.get("estado", "").strip()
        self.envio_filtro = self.request.GET.get("envio", "").strip()
        if self.estado_filtro in Pedido.Estado.values:
            queryset = queryset.filter(estado=self.estado_filtro)
        if self.envio_filtro in Pedido.EstadoEnvio.values:
            queryset = queryset.filter(estado_envio=self.envio_filtro)
        return queryset

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        empresa = self.request.empresa
        todos = Pedido.objects.de_empresa(empresa)
        pagados = todos.filter(estado=Pedido.Estado.PAGADO)
        resumen = pagados.aggregate(
            bruto=Sum("total"),
            comision=Sum("comision_valor"),
            neto=Sum("neto_vendedor"),
            envio=Sum("costo_envio"),
            cantidad=Count("id"),
        )
        contexto["liquidacion"] = {
            "bruto": resumen["bruto"] or Decimal("0.00"),
            "comision": resumen["comision"] or Decimal("0.00"),
            "neto": resumen["neto"] or Decimal("0.00"),
            "envio": resumen["envio"] or Decimal("0.00"),
            "cantidad": resumen["cantidad"] or 0,
            "comision_actual": empresa.comision_porcentaje,
        }
        contexto["pendientes_reembolso"] = todos.filter(estado=Pedido.Estado.REQUIERE_REEMBOLSO).count()
        contexto["reembolsados_total"] = todos.filter(estado=Pedido.Estado.REEMBOLSADO).count()
        contexto["pendientes_despacho"] = pagados.filter(
            estado_envio__in=[Pedido.EstadoEnvio.PENDIENTE, Pedido.EstadoEnvio.PREPARANDO]
        ).count()
        contexto["estado_filtro"] = self.estado_filtro
        contexto["envio_filtro"] = self.envio_filtro
        contexto["estados_pedido"] = Pedido.Estado.choices
        contexto["estados_envio"] = Pedido.EstadoEnvio.choices
        return contexto


class PedidoPanelDetailView(PermisoRequeridoMixin, DetailView):
    model = Pedido
    permiso_requerido = "ventas.ver"
    template_name = "core/pedidos_panel/detalle.html"
    context_object_name = "pedido"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("comprador", "factura", "reembolsado_por")
            .prefetch_related("lineas__producto", "pagos")
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        membresia = self.request.membresia
        contexto["puede_reembolsar"] = _puede_reembolsar(membresia)
        contexto["puede_gestionar_envio"] = _puede_gestionar_envio(membresia)
        contexto["estados_envio"] = Pedido.EstadoEnvio.choices
        contexto["estados_dispersion"] = Pedido.EstadoDispersion.choices
        return contexto

    def post(self, request, *args, **kwargs):
        pedido = self.get_object()
        membresia = request.membresia
        accion = (request.POST.get("accion") or "").strip()

        if accion == "reembolsar":
            if not _puede_reembolsar(membresia):
                raise PermissionDenied("No tienes permiso para registrar reembolsos.")
            try:
                reservas.registrar_reembolso(
                    pedido=pedido,
                    usuario=request.user,
                    referencia=request.POST.get("referencia", ""),
                    nota=request.POST.get("nota", ""),
                )
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"Reembolso del pedido #{pedido.numero} registrado correctamente.")
            return redirect("pedidos_panel_detalle", pk=pedido.pk)

        if accion == "actualizar_envio":
            if not _puede_gestionar_envio(membresia):
                raise PermissionDenied("No tienes permiso para actualizar el despacho de pedidos.")
            try:
                reservas.actualizar_envio_pedido(
                    pedido=pedido,
                    estado_envio=request.POST.get("estado_envio", ""),
                    transportadora=request.POST.get("transportadora", ""),
                    numero_guia=request.POST.get("numero_guia", ""),
                )
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(request, f"Estado de envío del pedido #{pedido.numero} actualizado.")
            return redirect("pedidos_panel_detalle", pk=pedido.pk)

        if accion == "registrar_dispersion":
            if not _puede_reembolsar(membresia):
                raise PermissionDenied("No tienes permiso para registrar la dispersión del pedido.")
            try:
                reservas.registrar_dispersion_pedido(
                    pedido=pedido,
                    referencia=request.POST.get("dispersion_referencia", ""),
                    estado_dispersion=request.POST.get(
                        "estado_dispersion", Pedido.EstadoDispersion.LIQUIDADA
                    ),
                )
            except ValueError as error:
                messages.error(request, str(error))
            else:
                messages.success(
                    request,
                    f"Dispersión del pedido #{pedido.numero} registrada correctamente.",
                )
            return redirect("pedidos_panel_detalle", pk=pedido.pk)

        messages.error(request, "Acción no reconocida.")
        return redirect("pedidos_panel_detalle", pk=pedido.pk)
