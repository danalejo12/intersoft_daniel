"""Panel operativo ERP: catálogos, documentos, transiciones y reportes."""
import csv
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views import View

from . import models as m, erp_services as s
from .caja import pesos
from .erp_forms import formulario, MovimientoForm, CarteraFacturaForm
from .mixins import TenantMixin
from .services import StockInsuficiente


MODULOS = {
    "proveedores": dict(model=m.Proveedor, titulo="Proveedores", permiso="compras", campos=["nombre", "documento", "email", "telefono", "direccion", "activo"], columnas=["nombre", "documento", "telefono", "activo"], buscar=["nombre", "documento"]),
    "compras": dict(model=m.Compra, titulo="Compras", permiso="compras", campos=["proveedor", "referencia", "fecha", "vencimiento", "observaciones"], columnas=["referencia", "proveedor", "fecha", "total", "recibida"], buscar=["referencia", "proveedor__nombre"], linea=m.LineaCompra, relacion="compra", campos_linea=["producto", "cantidad", "costo", "iva_porcentaje"], accion="recibir", etiqueta="Recibir mercancía", cerrado="recibida"),
    "cartera": dict(model=m.CuentaCartera, titulo="Cuentas por cobrar y pagar", permiso="cartera", campos=["tipo", "tercero", "concepto", "fecha", "vencimiento", "total"], columnas=["tipo", "tercero", "concepto", "vencimiento", "total", "saldo", "estado"], buscar=["tercero", "concepto"]),
    "cuentas": dict(model=m.CuentaTesoreria, titulo="Cajas y bancos", permiso="tesoreria", campos=["nombre", "tipo", "activa"], columnas=["nombre", "tipo", "activa"], buscar=["nombre"]),
    "tesoreria": dict(model=m.MovimientoTesoreria, titulo="Ingresos y egresos", permiso="tesoreria", campos=[], columnas=["fecha", "cuenta", "tipo", "concepto", "monto", "conciliado"], buscar=["concepto", "referencia"], accion="conciliar", etiqueta="Marcar conciliado", cerrado="conciliado"),
    "plan-contable": dict(model=m.CuentaContable, titulo="Plan de cuentas", permiso="contabilidad", campos=["codigo", "nombre", "naturaleza"], columnas=["codigo", "nombre", "naturaleza"], buscar=["codigo", "nombre"]),
    "contabilidad": dict(model=m.AsientoContable, titulo="Comprobantes contables", permiso="contabilidad", campos=["fecha", "concepto", "referencia"], columnas=["fecha", "concepto", "referencia", "confirmado"], buscar=["concepto", "referencia"], linea=m.LineaAsiento, relacion="asiento", campos_linea=["cuenta", "debito", "credito"], accion="confirmar", etiqueta="Confirmar comprobante", cerrado="confirmado"),
    "empleados": dict(model=m.Empleado, titulo="Empleados y profesionales", permiso="nomina", campos=["nombre", "documento", "cargo", "salario_base", "fecha_ingreso", "activo"], columnas=["nombre", "documento", "cargo", "salario_base", "activo"], buscar=["nombre", "documento"]),
    "nomina": dict(model=m.LiquidacionNomina, titulo="Liquidaciones de nómina", permiso="nomina", campos=["empleado", "desde", "hasta", "base", "adicionales", "deducciones", "observaciones"], columnas=["empleado", "desde", "hasta", "neto", "aprobada"], buscar=["empleado__nombre"], accion="aprobar", etiqueta="Aprobar y generar cuenta por pagar", cerrado="aprobada", ayuda="Registra los valores revisados de cada período. Base, adicionales y deducciones se ingresan manualmente; no se calculan aportes ni prestaciones automáticamente."),
    "produccion": dict(model=m.OrdenProduccion, titulo="Órdenes de producción", permiso="produccion", campos=["producto", "cantidad", "fecha", "observaciones"], columnas=["producto", "cantidad", "fecha", "completada"], buscar=["producto__nombre"], linea=m.InsumoProduccion, relacion="orden", campos_linea=["producto", "cantidad"], accion="producir", etiqueta="Consumir insumos y recibir producto", cerrado="completada", ayuda="Indica las cantidades totales de insumos para esta orden, en unidades enteras."),
    "servicios": dict(model=m.Servicio, titulo="Catálogo de servicios", permiso="agenda", campos=["nombre", "precio", "iva_porcentaje", "duracion_minutos", "activo"], columnas=["nombre", "precio", "iva_porcentaje", "duracion_minutos", "activo"], buscar=["nombre"]),
    "agenda": dict(model=m.Cita, titulo="Agenda de servicios", permiso="agenda", campos=["cliente", "empleado", "servicio", "inicio", "observaciones"], columnas=["inicio", "fin", "cliente", "empleado", "servicio", "total", "estado"], buscar=["cliente__nombre", "empleado__nombre", "servicio__nombre"], ayuda="Al atender una cita se genera una cuenta por cobrar. Registra su cobro desde Ingresos y egresos."),
}

DINERO = {"total", "subtotal", "iva", "abonado", "saldo", "monto", "precio", "salario_base", "base", "adicionales", "deducciones", "neto", "costo", "debito", "credito"}
ETIQUETAS = {"saldo": "Saldo", "estado": "Estado", "iva_porcentaje": "IVA (%)"}


def etiqueta(modelo, campo):
    if campo in ETIQUETAS:
        return ETIQUETAS[campo]
    return str(modelo._meta.get_field(campo).verbose_name).capitalize()


def valor(objeto, campo):
    dato = getattr(objeto, campo)
    if campo in DINERO:
        return pesos(dato)
    if isinstance(dato, bool):
        return "Sí" if dato else "No"
    if hasattr(objeto, f"get_{campo}_display"):
        return getattr(objeto, f"get_{campo}_display")()
    if hasattr(dato, "hour"):
        return date_format(timezone.localtime(dato), "d/m/Y H:i")
    if hasattr(dato, "year"):
        return date_format(dato, "d/m/Y")
    return str(dato or "—")


class AccesoERP(TenantMixin, View):
    def dispatch(self, request, *args, **kwargs):
        self.config = MODULOS.get(kwargs.get("modulo"))
        if kwargs.get("modulo") and self.config is None:
            raise Http404
        if request.user.is_authenticated and request.membresia and self.config:
            accion = "ver" if request.method == "GET" else "gestionar"
            if not request.membresia.tiene_permiso(f"{self.config['permiso']}.{accion}"):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def puede_gestionar(self):
        return self.request.membresia.tiene_permiso(f"{self.config['permiso']}.gestionar")


class InicioERP(AccesoERP):
    def get(self, request):
        tarjetas = []
        for slug, config in MODULOS.items():
            if request.membresia.tiene_permiso(f"{config['permiso']}.ver"):
                tarjetas.append(dict(slug=slug, titulo=config["titulo"], cantidad=config["model"].objects.filter(empresa=request.empresa).count()))
        puede_ver_reportes = request.membresia.tiene_permiso("reportes.ver")
        if not tarjetas and not puede_ver_reportes:
            raise PermissionDenied
        return render(
            request,
            "core/erp/inicio.html",
            {"tarjetas": tarjetas, "puede_ver_reportes": puede_ver_reportes},
        )


class ListaERP(AccesoERP):
    def get(self, request, modulo):
        config = self.config
        qs = config["model"].objects.filter(empresa=request.empresa)
        relaciones = [f.name for f in config["model"]._meta.fields if f.is_relation and f.name != "empresa"]
        qs = qs.select_related(*relaciones)
        q = request.GET.get("q", "").strip()[:150]
        if q:
            filtro = Q()
            for campo in config["buscar"]:
                filtro |= Q(**{f"{campo}__icontains": q})
            qs = qs.filter(filtro)
        estado = request.GET.get("estado", "")
        if modulo == "cartera":
            if estado == "pendiente":
                qs = qs.filter(abonado__lt=F("total"))
            elif estado == "vencida":
                qs = qs.filter(abonado__lt=F("total"), vencimiento__lt=timezone.localdate())
            elif estado == "pagada":
                qs = qs.filter(abonado=F("total"))
        columnas = config["columnas"]
        cabeceras = [etiqueta(config["model"], c) for c in columnas]
        if request.GET.get("exportar") == "csv":
            respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
            respuesta["Content-Disposition"] = f'attachment; filename="{modulo}.csv"'
            respuesta.write("\ufeff")
            escritor = csv.writer(respuesta, delimiter=";")
            escritor.writerow(cabeceras)
            for obj in qs.iterator():
                fila = [valor(obj, c) for c in columnas]
                escritor.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in fila])
            return respuesta
        pagina = Paginator(qs, 25).get_page(request.GET.get("page"))
        puede_gestionar = self.puede_gestionar()
        return render(request, "core/erp/lista.html", dict(config=config, modulo=modulo, cabeceras=cabeceras,
            filas=[dict(pk=o.pk, valores=[valor(o, c) for c in columnas]) for o in pagina], pagina=pagina,
            q=q, estado=estado, puede_gestionar=puede_gestionar,
            puede_llevar_factura=modulo == "cartera" and puede_gestionar and request.membresia.tiene_permiso("ventas.ver")))


class CrearERP(AccesoERP):
    def dispatch(self, request, *args, **kwargs):
        respuesta = super().dispatch(request, *args, **kwargs)
        return respuesta

    def mostrar(self, request, modulo, form):
        return render(request, "core/erp/form.html", dict(form=form, config=self.config, modulo=modulo))

    def construir(self, request):
        if not self.puede_gestionar():
            raise PermissionDenied
        if self.kwargs["modulo"] == "tesoreria":
            clase = MovimientoForm
        else:
            clase = formulario(self.config["model"], self.config["campos"])
        return clase(request.POST if request.method == "POST" else None, empresa=request.empresa)

    def get(self, request, modulo):
        return self.mostrar(request, modulo, self.construir(request))

    def post(self, request, modulo):
        form = self.construir(request)
        if form.is_valid():
            try:
                with transaction.atomic():
                    if modulo == "tesoreria":
                        obj = s.registrar_tesoreria(empresa=request.empresa, usuario=request.user, **form.cleaned_data)
                    else:
                        obj = form.save(commit=False)
                        if modulo == "contabilidad":
                            obj.usuario = request.user
                        if modulo == "agenda":
                            obj = s.reservar_cita(obj)
                        else:
                            obj = s.guardar(obj)
                messages.success(request, "Registro guardado.")
                return redirect("erp_detalle", modulo=modulo, pk=obj.pk)
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            except IntegrityError:
                form.add_error(None, "Ya existe un registro con esos datos. Revisa el listado antes de reintentar.")
        return self.mostrar(request, modulo, form)


class DetalleERP(AccesoERP):
    def objeto(self, request, pk):
        return get_object_or_404(self.config["model"].objects.filter(empresa=request.empresa), pk=pk)

    def mostrar(self, request, modulo, obj, form=None):
        config = self.config
        cerrado = bool(getattr(obj, config.get("cerrado", ""), False))
        lineas, cabeceras = [], []
        if "linea" in config:
            campos = config["campos_linea"]
            qs = config["linea"].objects.filter(empresa=request.empresa, **{config["relacion"]: obj})
            lineas = [dict(pk=l.pk, valores=[valor(l, c) for c in campos]) for l in qs]
            cabeceras = [etiqueta(config["linea"], c) for c in campos]
            if form is None and not cerrado and self.puede_gestionar():
                form = formulario(config["linea"], campos)(empresa=request.empresa)
        campos_detalle = list(dict.fromkeys(config["campos"] + config["columnas"]))
        cartera_rel = None
        if modulo in ("nomina", "agenda"):
            cartera_rel = getattr(obj, "cartera", None)
        elif modulo == "compras":
            cartera_rel = getattr(obj, "cuentacartera", None)
        abonos = (
            list(obj.abonos.select_related("cuenta", "usuario").order_by("-fecha", "-creado_en"))
            if modulo == "cartera"
            else []
        )
        return render(request, "core/erp/detalle.html", dict(config=config, modulo=modulo, obj=obj,
            datos=[(etiqueta(config["model"], c), valor(obj, c)) for c in campos_detalle],
            lineas=lineas, cabeceras=cabeceras, form=form, cerrado=cerrado, puede_gestionar=self.puede_gestionar(),
            cartera=cartera_rel, abonos=abonos))

    def get(self, request, modulo, pk):
        return self.mostrar(request, modulo, self.objeto(request, pk))

    def post(self, request, modulo, pk):
        obj = self.objeto(request, pk)
        accion = request.POST.get("accion")
        form = None
        try:
            with transaction.atomic():
                obj = s.bloquear(self.config["model"], request.empresa, pk)
                if accion in ("agregar", "quitar") and "linea" in self.config:
                    if getattr(obj, self.config["cerrado"]):
                        raise ValidationError("El documento ya está confirmado y no se puede modificar.")
                    if accion == "agregar":
                        form = formulario(self.config["linea"], self.config["campos_linea"])(request.POST, empresa=request.empresa)
                        if form.is_valid():
                            linea = form.save(commit=False)
                            setattr(linea, self.config["relacion"], obj)
                            s.guardar(linea)
                        else:
                            return self.mostrar(request, modulo, obj, form)
                    else:
                        linea = get_object_or_404(self.config["linea"], empresa=request.empresa,
                                     pk=request.POST.get("linea"), **{self.config["relacion"]: obj})
                        linea.delete()
                elif modulo == "compras" and accion == "recibir":
                    s.recibir_compra(empresa=request.empresa, pk=pk, usuario=request.user)
                elif modulo == "contabilidad" and accion == "confirmar":
                    s.confirmar_asiento(empresa=request.empresa, pk=pk)
                elif modulo == "nomina" and accion == "aprobar":
                    s.aprobar_nomina(empresa=request.empresa, pk=pk)
                elif modulo == "produccion" and accion == "producir":
                    s.completar_produccion(empresa=request.empresa, pk=pk, usuario=request.user)
                elif modulo == "agenda" and accion in ("atendida", "cancelada"):
                    s.cambiar_cita(empresa=request.empresa, pk=pk, estado=accion)
                elif modulo == "tesoreria" and accion == "conciliar":
                    obj.conciliado = True
                    s.guardar(obj)
                elif accion == "eliminar_borrador" and "cerrado" in self.config:
                    if getattr(obj, self.config["cerrado"]):
                        raise ValidationError("El documento ya está confirmado y no se puede eliminar.")
                    if "linea" in self.config:
                        self.config["linea"].objects.filter(
                            empresa=request.empresa, **{self.config["relacion"]: obj}
                        ).delete()
                    obj.delete()
                    messages.success(request, "Borrador eliminado.")
                    return redirect("erp_lista", modulo=modulo)
                else:
                    raise ValidationError("Acción no válida para este documento.")
            messages.success(request, "Operación realizada.")
        except (ValidationError, StockInsuficiente, ValueError) as error:
            messages.error(request, " ".join(error.messages) if isinstance(error, ValidationError) else str(error))
        except IntegrityError:
            messages.error(request, "La operación entra en conflicto con un registro existente.")
        return redirect("erp_detalle", modulo=modulo, pk=pk)


class CarteraFacturaERP(AccesoERP):
    def get(self, request):
        if not request.membresia.tiene_permiso("cartera.gestionar") or not request.membresia.tiene_permiso("ventas.ver"):
            raise PermissionDenied
        return self.mostrar(request, CarteraFacturaForm(empresa=request.empresa))

    def mostrar(self, request, form):
        return render(request, "core/erp/form.html", dict(form=form, config={"titulo": "Llevar factura a cartera"}, modulo="cartera"))

    def post(self, request):
        if not request.membresia.tiene_permiso("cartera.gestionar") or not request.membresia.tiene_permiso("ventas.ver"):
            raise PermissionDenied
        form = CarteraFacturaForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            try:
                obj = s.llevar_factura_a_cartera(empresa=request.empresa, pk=form.cleaned_data["factura"].pk,
                                               vencimiento=form.cleaned_data["vencimiento"])
                return redirect("erp_detalle", modulo="cartera", pk=obj.pk)
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
        return self.mostrar(request, form)


class ReportesERP(AccesoERP):
    def get(self, request):
        if not request.membresia.tiene_permiso("reportes.ver"):
            raise PermissionDenied
        # Cada sección exige además permiso sobre sus datos.
        datos = {"titulo": "Reportes operativos"}
        if request.membresia.tiene_permiso("cartera.ver"):
            cartera = m.CuentaCartera.objects.filter(empresa=request.empresa)
            datos["cartera"] = [dict(tipo=titulo, total=cartera.filter(tipo=tipo).aggregate(v=Sum(F("total") - F("abonado")))["v"] or 0)
                                for tipo, titulo in [("cobrar", "Por cobrar"), ("pagar", "Por pagar")]]
        if request.membresia.tiene_permiso("tesoreria.ver"):
            movimientos = m.MovimientoTesoreria.objects.filter(empresa=request.empresa)
            agrupados = movimientos.values("cuenta_id", "tipo").annotate(total=Sum("monto"))
            saldos = {}
            for fila in agrupados:
                saldos[fila["cuenta_id"]] = saldos.get(fila["cuenta_id"], 0) + (fila["total"] if fila["tipo"] == "ingreso" else -fila["total"])
            datos["cuentas"] = [dict(nombre=c.nombre, saldo=saldos.get(c.pk, 0)) for c in m.CuentaTesoreria.objects.filter(empresa=request.empresa)]
        if request.membresia.tiene_permiso("contabilidad.ver"):
            lineas = m.LineaAsiento.objects.filter(empresa=request.empresa, asiento__confirmado=True)
            datos["balance"] = list(lineas.values("cuenta__codigo", "cuenta__nombre").annotate(debito=Sum("debito"), credito=Sum("credito")).order_by("cuenta__codigo"))
        return render(request, "core/erp/reportes.html", datos)
