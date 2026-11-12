"""Punto de venta del panel: ventas de mostrador con caja, varios medios de pago y ticket."""
import json
import re
import uuid
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView

from . import caja, erp_services
from .mixins import PermisoRequeridoMixin, TenantMixin
from .models import Cliente, CuentaTesoreria, DetalleFactura, Factura, MovimientoTesoreria, PagoCaja, Producto, TurnoCaja

MAXIMO_RESULTADOS = 20
PRODUCTOS_FRECUENTES = 12


def _cantidad_entera(valor):
    """Acepta solo enteros explícitos (int o cadena de dígitos); rechaza bool y decimales."""
    if isinstance(valor, bool):
        raise ValueError("Booleano no permitido")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str):
        texto = valor.strip()
        if re.fullmatch(r"-?\d+", texto):
            return int(texto)
    raise ValueError("Cantidad no entera")


def datos_producto(producto):
    """Lo que el POS necesita de un producto. En el panel el stock exacto sí se muestra."""
    return {
        "id": str(producto.pk),
        "codigo": producto.codigo,
        "nombre": producto.nombre,
        "precio": str(producto.precio),
        "iva": str(producto.iva_porcentaje),
        "stock": producto.stock,
        "imagen": producto.imagen.url if producto.imagen else "",
    }


def productos_frecuentes(empresa):
    """Los más vendidos de los últimos 30 días; si son pocos, se completan por nombre."""
    desde = timezone.now() - timedelta(days=30)
    activos = Producto.objects.de_empresa(empresa).filter(activo=True)
    ids = list(
        DetalleFactura.objects.filter(
            factura__empresa=empresa, factura__creado_en__gte=desde, producto__activo=True
        ).exclude(factura__estado=Factura.Estado.ANULADA)
        .values("producto").annotate(vendidos=Sum("cantidad")).order_by("-vendidos")
        .values_list("producto", flat=True)[:PRODUCTOS_FRECUENTES]
    )
    por_id = {p.pk: p for p in activos.filter(pk__in=ids)}
    lista = [por_id[i] for i in ids if i in por_id]
    if len(lista) < PRODUCTOS_FRECUENTES:
        lista += list(activos.exclude(pk__in=ids).order_by("nombre")[: PRODUCTOS_FRECUENTES - len(lista)])
    return lista


class PosMixin(PermisoRequeridoMixin):
    permiso_requerido = "ventas.crear"

    def turno(self):
        return caja.turno_abierto(self.request.empresa, self.request.user)


class PosView(PosMixin, View):
    def get(self, request):
        turno = self.turno()
        if turno is None:
            return render(request, "core/pos/abrir.html")
        frecuentes = productos_frecuentes(request.empresa)
        return render(request, "core/pos/pos.html", {
            "turno": turno,
            "frecuentes": frecuentes,
            "frecuentes_datos": [datos_producto(p) for p in frecuentes],
            "consumidor_final": caja.DOCUMENTO_CONSUMIDOR_FINAL,
        })


class AbrirTurnoView(PosMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            caja.abrir_turno(empresa=request.empresa, usuario=request.user, base=request.POST.get("base", "0"))
            messages.success(request, "Caja abierta. ¡Buenas ventas!")
        except caja.OperacionCaja as error:
            messages.error(request, str(error))
        return redirect("pos")


class BuscarProductosView(PosMixin, View):
    def get(self, request):
        q = request.GET.get("q", "").strip()
        if not q:
            return JsonResponse({"exacto": None, "productos": []})
        productos = Producto.objects.de_empresa(request.empresa).filter(activo=True)
        # Un lector de código de barras escribe el código exacto y pulsa Enter
        exacto = productos.filter(codigo__iexact=q).first()
        coincidencias = productos.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q)).order_by("nombre")[:MAXIMO_RESULTADOS]
        return JsonResponse({
            "exacto": datos_producto(exacto) if exacto else None,
            "productos": [datos_producto(p) for p in coincidencias],
        })


class BuscarClientesView(PosMixin, View):
    def get(self, request):
        q = request.GET.get("q", "").strip()
        clientes = []
        if q:
            clientes = (
                Cliente.objects.de_empresa(request.empresa).filter(activo=True)
                .filter(Q(nombre__icontains=q) | Q(numero_documento__icontains=q))
                .exclude(numero_documento=caja.DOCUMENTO_CONSUMIDOR_FINAL)
                .order_by("nombre")[:10]
            )
        return JsonResponse({"clientes": [
            {"id": str(c.pk), "nombre": c.nombre, "documento": f"{c.tipo_documento} {c.numero_documento}"} for c in clientes
        ]})


class VenderView(PosMixin, View):
    http_method_names = ["post"]

    def error(self, mensaje, estado=400):
        return JsonResponse({"ok": False, "error": mensaje}, status=estado)

    def post(self, request):
        turno = self.turno()
        if turno is None:
            return self.error("No tienes una caja abierta. Recarga la página para abrirla.", 409)
        try:
            datos = json.loads(request.body)
        except (ValueError, TypeError):
            return self.error("La venta no tiene un formato válido.")
        if not isinstance(datos, dict) or not isinstance(datos.get("lineas"), list):
            return self.error("La venta no tiene un formato válido.")
        lineas = datos["lineas"]

        operacion = datos.get("operacion")
        if operacion is not None:
            if not isinstance(operacion, str):
                return self.error("La clave de operación no es válida.")
            try:
                operacion = uuid.UUID(operacion)
            except (ValueError, AttributeError):
                return self.error("La clave de operación no es válida.")

        # Se suman las cantidades repetidas y se ignora cualquier precio que mande el navegador
        cantidades = {}
        for linea in lineas:
            if not isinstance(linea, dict):
                return self.error("Una línea de la venta no es válida.")
            producto_raw = linea.get("producto")
            if not isinstance(producto_raw, str) or not producto_raw.strip():
                return self.error("Una línea de la venta no es válida.")
            try:
                producto_id = producto_raw.strip()
                cantidad = _cantidad_entera(linea.get("cantidad"))
            except (KeyError, TypeError, ValueError):
                return self.error("Una línea de la venta no es válida.")
            if not 1 <= cantidad <= 9999:
                return self.error("Las cantidades deben estar entre 1 y 9.999.")
            acumulada = cantidades.get(producto_id, 0) + cantidad
            if not 1 <= acumulada <= 9999:
                return self.error("Las cantidades deben estar entre 1 y 9.999.")
            cantidades[producto_id] = acumulada
        try:
            productos = {
                str(p.pk): p
                for p in Producto.objects.de_empresa(request.empresa).filter(pk__in=list(cantidades), activo=True)
            }
        except (ValidationError, ValueError):  # un id que no es UUID
            return self.error("Un producto de la venta no existe.")
        if len(productos) != len(cantidades):
            return self.error("Un producto de la venta ya no está disponible.")

        cliente = None
        if datos.get("cliente"):
            try:
                cliente = Cliente.objects.de_empresa(request.empresa).filter(pk=datos["cliente"]).first()
            except (ValidationError, ValueError):
                cliente = None
            if cliente is None:
                return self.error("El cliente elegido no existe.")

        try:
            factura = caja.registrar_venta(
                turno=turno,
                usuario=request.user,
                items=[{"producto": productos[i], "cantidad": c} for i, c in cantidades.items()],
                pagos=datos.get("pagos"),
                cliente=cliente,
                operacion=operacion,
            )
        except caja.OperacionCaja as error:
            return self.error(str(error), 409)

        pagos_caja = list(factura.pagos_caja.all())
        cambio = sum((p.cambio for p in pagos_caja), 0)
        return JsonResponse({
            "ok": True,
            "numero": factura.numero,
            "total": str(factura.total),
            "cambio": str(cambio),
            "ticket": reverse("pos_ticket", args=[factura.pk]),
        })


class CerrarTurnoView(PosMixin, View):
    def get(self, request):
        turno = self.turno()
        if turno is None:
            messages.info(request, "No tienes una caja abierta.")
            return redirect("pos")
        # Arqueo a ciegas: se muestran las ventas, pero no el efectivo esperado
        return render(request, "core/pos/cerrar.html", {"turno": turno, "ventas": turno.facturas.count()})

    def post(self, request):
        turno = self.turno()
        if turno is None:
            return redirect("pos")
        try:
            turno = caja.cerrar_turno(
                turno=turno, usuario=request.user,
                contado=request.POST.get("contado", ""), observaciones=request.POST.get("observaciones", ""),
            )
        except caja.OperacionCaja as error:
            messages.error(request, str(error))
            return redirect("pos_cerrar")
        messages.success(request, "Caja cerrada.")
        return redirect("pos_turno", pk=turno.pk)


class TurnosView(PermisoRequeridoMixin, ListView):
    permiso_requerido = "ventas.ver"
    model = TurnoCaja
    template_name = "core/pos/turnos.html"
    context_object_name = "turnos"
    paginate_by = 20

    def get_queryset(self):
        return super().get_queryset().select_related("cajero")


class TurnoView(PermisoRequeridoMixin, DetailView):
    permiso_requerido = "ventas.ver"
    model = TurnoCaja
    template_name = "core/pos/turno.html"
    context_object_name = "turno"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        turno = self.object
        empresa = self.request.empresa
        membresia = self.request.membresia
        movimiento_tesoreria = (
            MovimientoTesoreria.objects.filter(empresa=empresa, operacion=turno.pk)
            .select_related("cuenta")
            .first()
        )
        puede_trasladar_tesoreria = bool(membresia and membresia.tiene_permiso("tesoreria.gestionar"))
        contexto["resumen"] = caja.resumen_turno(turno)
        contexto["facturas"] = turno.facturas.select_related("cliente").order_by("-numero")
        contexto["movimiento_tesoreria"] = movimiento_tesoreria
        contexto["puede_trasladar_tesoreria"] = puede_trasladar_tesoreria
        contexto["cuentas_tesoreria"] = (
            CuentaTesoreria.objects.filter(empresa=empresa, activa=True).order_by("nombre")
            if (puede_trasladar_tesoreria and not turno.abierto and movimiento_tesoreria is None)
            else []
        )
        return contexto

    def post(self, request, pk):
        if not (request.membresia and request.membresia.tiene_permiso("tesoreria.gestionar")):
            raise PermissionDenied("No tienes permiso para trasladar fondos a tesorería.")
        turno = self.get_object()
        cuenta = get_object_or_404(
            CuentaTesoreria,
            empresa=request.empresa,
            activa=True,
            pk=request.POST.get("cuenta_tesoreria"),
        )
        try:
            mov = erp_services.trasladar_turno_a_tesoreria(
                empresa=request.empresa,
                turno=turno,
                cuenta_tesoreria=cuenta,
                usuario=request.user,
            )
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, f"Efectivo trasladado a tesorería ({mov.cuenta.nombre}).")
        return redirect("pos_turno", pk=turno.pk)


class TicketView(TenantMixin, View):
    """Permite abrir el recibo tanto a quien consulta ventas como al cajero que cobra en el POS."""
    permisos_permitidos = ("ventas.ver", "ventas.crear")

    def dispatch(self, request, *args, **kwargs):
        membresia = request.membresia
        if membresia and not any(membresia.tiene_permiso(p) for p in self.permisos_permitidos):
            raise PermissionDenied("No tienes permiso para esta acción.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        factura = get_object_or_404(
            Factura.objects.de_empresa(request.empresa).select_related("cliente", "creada_por"), pk=pk
        )
        pagos = list(factura.pagos_caja.all())
        documento_cliente = factura.cliente_documento or f"{factura.cliente.tipo_documento} {factura.cliente.numero_documento}"
        return render(request, "core/pos/ticket.html", {
            "factura": factura,
            "empresa": request.empresa,
            "detalles": factura.detalles.select_related("producto"),
            "pagos": pagos,
            "cambio": sum((p.cambio for p in pagos), 0),
            "imprimir": request.GET.get("imprimir") == "1",
            "consumidor_final": documento_cliente.endswith(caja.DOCUMENTO_CONSUMIDOR_FINAL),
        })
