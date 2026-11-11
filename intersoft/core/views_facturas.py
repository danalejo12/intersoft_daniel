"""Vistas de facturación, cobro con Wompi, simulador de pagos y webhook."""
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Exists, F, OuterRef
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import DetailView, ListView

from .facturacion_electronica import emitir_factura_electronica
from .forms import FacturaForm, LineasFacturaFormSet
from .mixins import PermisoRequeridoMixin
from .models import CuentaCartera, Factura, Pago, PagoCaja, Pedido
from .pagos import (
    PagoNoPermitido,
    aplicar_transaccion,
    crear_evento_simulado,
    crear_pago,
    evento_es_valido,
    pasarela_simulada,
    sincronizar_pago,
    sincronizar_pendientes,
    url_checkout,
)
from .services import StockInsuficiente, anular_factura, crear_factura


class FacturaListView(PermisoRequeridoMixin, ListView):
    model = Factura
    permiso_requerido = "ventas.ver"
    template_name = "core/facturas/lista.html"
    context_object_name = "facturas"
    paginate_by = 20

    def get_queryset(self):
        # select_related trae el cliente en la MISMA consulta (evita N+1)
        # pagada y pago_en_proceso se calculan en la misma consulta con EXISTS (no una por fila)
        pagos = Pago.objects.filter(factura=OuterRef("pk"))
        # Un intento de los últimos 30 min puede estar pagado en Wompi: primero hay que verificarlo
        recientes = timezone.now() - timedelta(minutes=30)
        return (
            super().get_queryset()
            .select_related("cliente")
            .annotate(
                pagada=Exists(pagos.filter(estado=Pago.Estado.APROBADO))
                | Exists(Pedido.objects.filter(factura=OuterRef("pk"), estado=Pedido.Estado.PAGADO))
                | Exists(PagoCaja.objects.filter(factura=OuterRef("pk")))
                | Exists(CuentaCartera.objects.filter(factura=OuterRef("pk"), abonado=F("total"))),
                en_cartera=Exists(
                    CuentaCartera.objects.filter(factura=OuterRef("pk"), abonado__lt=F("total"))
                ),
                pago_en_proceso=Exists(
                    pagos.filter(estado=Pago.Estado.PENDIENTE, creado_en__gte=recientes)
                ),
            )
            .order_by("-numero")
        )

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["puede_cobrar"] = self.request.membresia.tiene_permiso("ventas.cobrar")
        return contexto


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
            .prefetch_related("detalles__producto", "pagos")
        )

    def get_object(self, queryset=None):
        factura = super().get_object(queryset)
        if factura.pagos.filter(estado=Pago.Estado.PENDIENTE).exists():
            sincronizar_pendientes(factura)
            factura = super().get_object(queryset)  # recarga los pagos ya actualizados
        return factura

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["puede_emitir_dian"] = self.request.membresia.tiene_permiso("ventas.crear")
        return contexto


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


class FacturaAnularView(PermisoRequeridoMixin, View):
    http_method_names = ["post"]
    permiso_requerido = "facturas.anular"

    def post(self, request, pk):
        factura = get_object_or_404(Factura.objects.de_empresa(request.empresa), pk=pk)
        try:
            anular_factura(factura=factura, usuario=request.user)
            messages.success(request, f"Factura {factura.numero} anulada.")
        except ValueError as error:
            messages.error(request, str(error))
        return redirect("facturas_lista")


class FacturaEmitirDianView(PermisoRequeridoMixin, View):
    """Emite o sincroniza el documento electrónico de la factura ante el adaptador DIAN."""

    http_method_names = ["post"]
    permiso_requerido = "ventas.crear"

    def post(self, request, pk):
        factura = get_object_or_404(Factura.objects.de_empresa(request.empresa), pk=pk)
        try:
            factura = emitir_factura_electronica(factura=factura)
        except ValueError as error:
            messages.error(request, str(error))
        else:
            if factura.estado_dian == Factura.EstadoDian.ACEPTADA:
                messages.success(request, f"Factura #{factura.numero} validada ante DIAN (CUFE generado).")
            else:
                messages.warning(request, f"Respuesta DIAN: {factura.dian_respuesta}")
        return redirect("facturas_detalle", pk=factura.pk)


class FacturaCobrarView(PermisoRequeridoMixin, View):
    """Crea el intento de pago y envía al cliente a la pasarela."""

    http_method_names = ["post"]
    permiso_requerido = "ventas.cobrar"

    def post(self, request, pk):
        factura = get_object_or_404(Factura.objects.de_empresa(request.empresa), pk=pk)
        sincronizar_pendientes(factura, forzar=True)  # evita cobrar dos veces si un intento ya se aprobó
        try:
            pago = crear_pago(factura=factura)
        except PagoNoPermitido as error:
            messages.error(request, str(error))
            return redirect("facturas_lista")

        if pasarela_simulada():
            return redirect("pagos_simulador", pk=pago.pk)

        redirect_url = request.build_absolute_uri(reverse("pagos_resultado", args=[pago.pk]))
        return redirect(url_checkout(pago=pago, redirect_url=redirect_url))


class PagoResultadoView(PermisoRequeridoMixin, View):
    """Muestra el estado guardado. Esta página nunca marca un pago como aprobado."""

    permiso_requerido = "ventas.ver"

    def get(self, request, pk):
        pago = get_object_or_404(
            Pago.objects.de_empresa(request.empresa).select_related("factura"), pk=pk
        )
        # Con ?id=<transacción> (redirect de Wompi) se consulta ese id; sin él, por referencia
        transaccion_id = request.GET.get("id", "")
        if not pasarela_simulada():
            pago = sincronizar_pago(pago=pago, transaccion_id=transaccion_id)
        return render(
            request, "core/pagos/resultado.html", {"pago": pago, "transaccion_id": transaccion_id}
        )


class PagoSimuladorView(PermisoRequeridoMixin, View):
    """Reemplaza el checkout solo en desarrollo. No mueve dinero real."""

    permiso_requerido = "ventas.cobrar"
    RESULTADOS = {"APPROVED", "DECLINED", "ERROR"}

    def dispatch(self, request, *args, **kwargs):
        if not pasarela_simulada():
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def obtener_pago(self, request, pk):
        return get_object_or_404(
            Pago.objects.de_empresa(request.empresa).select_related("factura"),
            pk=pk,
            estado=Pago.Estado.PENDIENTE,
            factura__isnull=False,  # el simulador solo cubre el cobro de facturas del panel
        )

    def get(self, request, pk):
        pago = self.obtener_pago(request, pk)
        return render(request, "core/pagos/simulador.html", {"pago": pago})

    def post(self, request, pk):
        pago = self.obtener_pago(request, pk)
        resultado = request.POST.get("resultado")
        if resultado not in self.RESULTADOS:
            return HttpResponseBadRequest("Resultado no válido.")

        evento = crear_evento_simulado(
            pago=pago, status=resultado, secreto=settings.WOMPI_EVENTS_SECRET
        )
        if evento_es_valido(evento, settings.WOMPI_EVENTS_SECRET):
            aplicar_transaccion(evento["data"]["transaction"])
        return redirect("pagos_resultado", pk=pago.pk)


@method_decorator(csrf_exempt, name="dispatch")  # Wompi no tiene tu token CSRF; lo protege la firma
class WompiWebhookView(View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            evento = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest("JSON no válido.")

        if not isinstance(evento, dict) or not evento_es_valido(evento, settings.WOMPI_EVENTS_SECRET):
            return HttpResponseBadRequest("Firma no válida.")

        if evento.get("event") == "transaction.updated":
            aplicar_transaccion(evento["data"]["transaction"])
        return HttpResponse(status=200)
