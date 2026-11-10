# 1. Imports de Python
import json
from datetime import date, timedelta

# 2. Imports de Django
from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.formats import date_format
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

# 3. Imports de tu propia app
from .forms import ClienteForm, DatosNegocioForm, FacturaForm, LineasFacturaFormSet, MovimientoForm, ProductoForm
from .mixins import PermisoRequeridoMixin, TenantMixin
from .models import Cliente, Factura, MovimientoInventario, Pago, PagoCaja, Pedido, Producto
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
from .services import StockInsuficiente, anular_factura, crear_factura, registrar_movimiento


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
        total_productos = productos.count()
        contexto["total_productos"] = total_productos
        # F("stock_minimo") compara dos columnas DENTRO de PostgreSQL
        stock_bajo = productos.filter(stock__lte=F("stock_minimo")).order_by("stock")
        contexto["stock_bajo"] = stock_bajo
        contexto["puede_mover"] = self.request.membresia.tiene_permiso("inventario.movimientos")

        # Salud del inventario: porcentaje de productos por encima de su mínimo
        n_stock_bajo = stock_bajo.count()
        contexto["n_stock_bajo"] = n_stock_bajo
        contexto["productos_sanos"] = total_productos - n_stock_bajo
        contexto["salud_inventario"] = (
            round(100 * (total_productos - n_stock_bajo) / total_productos) if total_productos else 100
        )

        # Ventas: solo facturas de esta empresa, sin las anuladas
        ventas = Factura.objects.de_empresa(empresa).exclude(estado=Factura.Estado.ANULADA)
        ahora = timezone.localtime()
        inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        del_mes = ventas.filter(creado_en__gte=inicio_mes).aggregate(total=Sum("total"), cantidad=Count("id"))
        contexto["ventas_mes"] = del_mes["total"] or 0
        contexto["facturas_mes"] = del_mes["cantidad"]
        contexto["ultimas_facturas"] = ventas.select_related("cliente").order_by("-numero")[:5]
        contexto["serie_meses"] = self.serie_meses(ventas, inicio_mes)
        contexto["serie_dias"] = self.serie_dias(ventas, ahora.date())
        return contexto

    @staticmethod
    def serie_meses(ventas, inicio_mes, cantidad=6):
        """Total facturado en los últimos 6 meses, incluido el actual; los meses sin ventas valen 0."""
        meses = []
        anio, mes = inicio_mes.year, inicio_mes.month
        for _ in range(cantidad):
            meses.append((anio, mes))
            anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
        meses.reverse()
        desde = inicio_mes.replace(year=meses[0][0], month=meses[0][1])
        totales = {
            (fila["mes"].year, fila["mes"].month): fila["total"]
            for fila in ventas.filter(creado_en__gte=desde)
            .annotate(mes=TruncMonth("creado_en")).values("mes").annotate(total=Sum("total"))
        }
        return {
            "etiquetas": [date_format(date(anio, mes, 1), "M Y") for anio, mes in meses],
            "valores": [float(totales.get(clave, 0)) for clave in meses],
        }

    @staticmethod
    def serie_dias(ventas, hoy, cantidad=7):
        """Total facturado en los últimos 7 días, incluido hoy."""
        dias = [hoy - timedelta(days=atras) for atras in range(cantidad - 1, -1, -1)]
        totales = {
            fila["dia"]: fila["total"]
            for fila in ventas.filter(creado_en__date__gte=dias[0])
            .annotate(dia=TruncDate("creado_en")).values("dia").annotate(total=Sum("total"))
        }
        return {
            "etiquetas": [date_format(dia, "j M") for dia in dias],
            "valores": [float(totales.get(dia, 0)) for dia in dias],
        }


class DatosNegocioView(PermisoRequeridoMixin, SuccessMessageMixin, UpdateView):
    """Dirección y teléfono legales del negocio. Sin ellos, sus productos no salen en el marketplace."""

    permiso_requerido = "negocio.editar"  # solo el rol administrador, que tiene todos los permisos
    form_class = DatosNegocioForm
    template_name = "core/negocio/datos.html"
    success_url = reverse_lazy("dashboard")
    success_message = "¡Listo! Guardamos los datos de tu negocio."

    def get_object(self, queryset=None):
        # El negocio es siempre el activo: nunca se recibe un id desde la URL
        return self.request.empresa

    def form_valid(self, form):
        # Se salta TenantMixin.form_valid: Empresa no tiene campo empresa
        return super(TenantMixin, self).form_valid(form)


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
        contexto["puede_eliminar"] = self.request.membresia.tiene_permiso("clientes.eliminar")  # ← nueva
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
                | Exists(PagoCaja.objects.filter(factura=OuterRef("pk"))),
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
        contexto["puede_mover"] = membresia.tiene_permiso("inventario.movimientos")
        contexto["puede_eliminar"] = membresia.tiene_permiso("inventario.eliminar")
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

# Eliminar -- Eliminar -- Eliminar 
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


class ClienteDeleteView(EliminarLogicoView):
    model = Cliente
    permiso_requerido = "clientes.eliminar"
    url_lista = "clientes_lista"


class ProductoDeleteView(EliminarLogicoView):
    model = Producto
    permiso_requerido = "inventario.eliminar"
    url_lista = "productos_lista"


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