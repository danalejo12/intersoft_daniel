"""Panel operativo ERP: catálogos, documentos, transiciones y reportes."""
import csv
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction, IntegrityError
from django.db.models import DecimalField, F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.formats import date_format
from django.views import View

from . import models as m, erp_services as s
from .caja import pesos
from .contabilidad_automatica import (
    calcular_aportes_nomina_colombia,
    contabilizar_compra,
    contabilizar_movimiento_tesoreria,
    contabilizar_nomina,
)
from .erp_forms import formulario, MovimientoForm, CarteraFacturaForm
from .mixins import TenantMixin
from .services import StockInsuficiente


MODULOS = {
    "proveedores": {"model": m.Proveedor, "titulo": "Proveedores", "permiso": "compras", "categoria": "Abastecimiento", "color": "azul", "icono": "truck", "descripcion": "Directorio de proveedores, NIT y datos de contacto.", "campos": ["nombre", "documento", "email", "telefono", "direccion", "activo"], "columnas": ["nombre", "documento", "telefono", "activo"], "buscar": ["nombre", "documento"]},
    "compras": {"model": m.Compra, "titulo": "Compras", "permiso": "compras", "categoria": "Abastecimiento", "color": "azul", "icono": "bag", "descripcion": "Órdenes de compra, recepción en Kardex y cuentas por pagar.", "campos": ["proveedor", "referencia", "bodega", "fecha", "vencimiento", "observaciones"], "columnas": ["referencia", "proveedor", "fecha", "total", "recibida"], "buscar": ["referencia", "proveedor__nombre"], "linea": m.LineaCompra, "relacion": "compra", "campos_linea": ["producto", "cantidad", "costo", "iva_porcentaje"], "accion": "recibir", "etiqueta": "Recibir mercancía", "cerrado": "recibida"},
    "cartera": {"model": m.CuentaCartera, "titulo": "Cuentas por cobrar y pagar", "permiso": "cartera", "categoria": "Finanzas", "color": "ambar", "icono": "wallet", "descripcion": "Control de vencimientos, saldos pendientes y abonos.", "campos": ["tipo", "tercero", "concepto", "fecha", "vencimiento", "total"], "columnas": ["tipo", "tercero", "concepto", "vencimiento", "total", "saldo", "estado"], "buscar": ["tercero", "concepto"]},
    "cuentas": {"model": m.CuentaTesoreria, "titulo": "Cajas y bancos", "permiso": "tesoreria", "categoria": "Finanzas", "color": "verde", "icono": "bank", "descripcion": "Cuentas bancarias y cajas disponibles para recaudos y pagos.", "campos": ["nombre", "tipo", "activa"], "columnas": ["nombre", "tipo", "activa"], "buscar": ["nombre"]},
    "tesoreria": {"model": m.MovimientoTesoreria, "titulo": "Ingresos y egresos", "permiso": "tesoreria", "categoria": "Finanzas", "color": "verde", "icono": "arrows", "descripcion": "Movimientos de caja/banco, abonos a cartera y conciliación.", "campos": [], "columnas": ["fecha", "cuenta", "tipo", "concepto", "monto", "conciliado"], "buscar": ["concepto", "referencia"], "accion": "conciliar", "etiqueta": "Marcar conciliado", "cerrado": "conciliado"},
    "plan-contable": {"model": m.CuentaContable, "titulo": "Plan de cuentas", "permiso": "contabilidad", "categoria": "Contabilidad", "color": "violeta", "icono": "book", "descripcion": "Catálogo PUC de cuentas de débito y crédito por empresa.", "campos": ["codigo", "nombre", "naturaleza"], "columnas": ["codigo", "nombre", "naturaleza"], "buscar": ["codigo", "nombre"]},
    "contabilidad": {"model": m.AsientoContable, "titulo": "Comprobantes contables", "permiso": "contabilidad", "categoria": "Contabilidad", "color": "violeta", "icono": "scale", "descripcion": "Asientos de diario con validación de partida doble.", "campos": ["fecha", "concepto", "referencia"], "columnas": ["fecha", "concepto", "referencia", "confirmado"], "buscar": ["concepto", "referencia"], "linea": m.LineaAsiento, "relacion": "asiento", "campos_linea": ["cuenta", "debito", "credito"], "accion": "confirmar", "etiqueta": "Confirmar comprobante", "cerrado": "confirmado"},
    "empleados": {"model": m.Empleado, "titulo": "Empleados y profesionales", "permiso": "nomina", "categoria": "Talento Humano", "color": "azul", "icono": "users", "descripcion": "Personal activo, cargos, salarios base y agenda.", "campos": ["nombre", "documento", "cargo", "salario_base", "fecha_ingreso", "activo"], "columnas": ["nombre", "documento", "cargo", "salario_base", "activo"], "buscar": ["nombre", "documento"]},
    "nomina": {"model": m.LiquidacionNomina, "titulo": "Liquidaciones de nómina", "permiso": "nomina", "categoria": "Talento Humano", "color": "ambar", "icono": "receipt", "descripcion": "Liquidaciones por período con generación de cuenta por pagar.", "campos": ["empleado", "desde", "hasta", "base", "adicionales", "auxilio_transporte", "deducciones", "observaciones"], "columnas": ["empleado", "desde", "hasta", "neto", "aprobada"], "buscar": ["empleado__nombre"], "accion": "aprobar", "etiqueta": "Aprobar y generar cuenta por pagar", "cerrado": "aprobada", "ayuda": "Registra los valores revisados de cada período. Los adicionales salariales (horas extra, comisiones) aportan a salud y pensión; el auxilio de transporte se paga pero no aporta. Usa «Aplicar deducciones de ley» para calcular salud y pensión del empleado."},
    "produccion": {"model": m.OrdenProduccion, "titulo": "Órdenes de producción", "permiso": "produccion", "categoria": "Operación", "color": "violeta", "icono": "factory", "descripcion": "Transformación de insumos en producto terminado en Kardex.", "campos": ["producto", "cantidad", "fecha", "observaciones"], "columnas": ["producto", "cantidad", "fecha", "completada"], "buscar": ["producto__nombre"], "linea": m.InsumoProduccion, "relacion": "orden", "campos_linea": ["producto", "cantidad"], "accion": "producir", "etiqueta": "Consumir insumos y recibir producto", "cerrado": "completada", "ayuda": "Indica las cantidades totales de insumos para esta orden, en unidades enteras."},
    "servicios": {"model": m.Servicio, "titulo": "Catálogo de servicios", "permiso": "agenda", "categoria": "Operación", "color": "verde", "icono": "sparkles", "descripcion": "Servicios ofertados, tarifas, IVA y duración estimada.", "campos": ["nombre", "precio", "iva_porcentaje", "duracion_minutos", "activo"], "columnas": ["nombre", "precio", "iva_porcentaje", "duracion_minutos", "activo"], "buscar": ["nombre"]},
    "agenda": {"model": m.Cita, "titulo": "Agenda de servicios", "permiso": "agenda", "categoria": "Operación", "color": "azul", "icono": "calendar", "descripcion": "Programación de citas sin cruces y facturación en cartera.", "campos": ["cliente", "empleado", "servicio", "inicio", "observaciones"], "columnas": ["inicio", "fin", "cliente", "empleado", "servicio", "total", "estado"], "buscar": ["cliente__nombre", "empleado__nombre", "servicio__nombre"], "ayuda": "Al atender una cita se genera una cuenta por cobrar. Registra su cobro desde Ingresos y egresos."},
}

DINERO = {"total", "subtotal", "iva", "abonado", "saldo", "monto", "precio", "salario_base", "base", "adicionales", "auxilio_transporte", "deducciones", "neto", "costo", "debito", "credito"}
ETIQUETAS = {"saldo": "Saldo", "estado": "Estado", "iva_porcentaje": "IVA (%)"}


def etiqueta(modelo, campo):
    """Etiqueta legible de un campo del ERP."""
    if campo in ETIQUETAS:
        return ETIQUETAS[campo]
    return str(modelo._meta.get_field(campo).verbose_name).capitalize()


def valor(objeto, campo):
    """Valor de un campo listo para mostrar: pesos, Sí/No, opciones y fechas en formato local."""
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
    """Base de las vistas del ERP: carga la configuración del módulo y exige `<módulo>.ver` o `<módulo>.gestionar`."""
    def dispatch(self, request, *args, **kwargs):
        self.config = MODULOS.get(kwargs.get("modulo"))
        if kwargs.get("modulo") and self.config is None:
            raise Http404
        if request.user.is_authenticated and request.membresia and self.config:
            es_contabilizar = (
                request.method == "POST"
                and request.POST.get("accion") == "contabilizar"
                and request.membresia.tiene_permiso("contabilidad.gestionar")
                and request.membresia.tiene_permiso(f"{self.config['permiso']}.ver")
            )
            accion = "ver" if request.method == "GET" else "gestionar"
            if not es_contabilizar and not request.membresia.tiene_permiso(f"{self.config['permiso']}.{accion}"):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def puede_gestionar(self):
        return self.request.membresia.tiene_permiso(f"{self.config['permiso']}.gestionar")


class InicioERP(AccesoERP):
    """Tablero de módulos del ERP visibles para el rol. Ruta: `/panel/erp/` («erp_inicio»)."""
    def get(self, request):
        tarjetas = []
        categorias = []
        for slug, config in MODULOS.items():
            if request.membresia.tiene_permiso(f"{config['permiso']}.ver"):
                categoria = config.get("categoria", "General")
                if categoria not in categorias:
                    categorias.append(categoria)
                tarjetas.append(
                    {
                        "slug": slug,
                        "titulo": config["titulo"],
                        "cantidad": config["model"].objects.filter(empresa=request.empresa).count(),
                        "categoria": categoria,
                        "color": config.get("color", "azul"),
                        "icono": config.get("icono", "grid"),
                        "descripcion": config.get("descripcion", ""),
                    }
                )
        puede_ver_reportes = request.membresia.tiene_permiso("reportes.ver")
        if not tarjetas and not puede_ver_reportes:
            raise PermissionDenied
        return render(
            request,
            "core/erp/inicio.html",
            {
                "tarjetas": tarjetas,
                "categorias": categorias,
                "puede_ver_reportes": puede_ver_reportes,
            },
        )


class ListaERP(AccesoERP):
    """Lista paginada y con búsqueda de un módulo del ERP; exporta a CSV con ?exportar=csv. Ruta:
    `/panel/erp/<slug:modulo>/` («erp_lista»).
    """
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
        return render(request, "core/erp/lista.html", {"config": config, "modulo": modulo, "cabeceras": cabeceras,
            "filas": [{"pk": o.pk, "valores": [valor(o, c) for c in columnas]} for o in pagina], "pagina": pagina,
            "total_registros": pagina.paginator.count, "q": q, "estado": estado, "puede_gestionar": puede_gestionar,
            "puede_llevar_factura": modulo == "cartera" and puede_gestionar and request.membresia.tiene_permiso("ventas.ver")})


class CrearERP(AccesoERP):
    """Crea un documento de un módulo del ERP (compras, nómina, agenda…). Ruta: `/panel/erp/<slug:modulo>/nuevo/`
    («erp_crear»).
    """
    def mostrar(self, request, modulo, form):
        return render(request, "core/erp/form.html", {"form": form, "config": self.config, "modulo": modulo})

    def construir(self, request):
        """Formulario del módulo con los datos enviados (o vacío); exige poder gestionar."""
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
                        obj = s.reservar_cita(obj) if modulo == "agenda" else s.guardar(obj)
                messages.success(request, "Registro guardado.")
                return redirect("erp_detalle", modulo=modulo, pk=obj.pk)
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            except IntegrityError:
                form.add_error(None, "Ya existe un registro con esos datos. Revisa el listado antes de reintentar.")
        return self.mostrar(request, modulo, form)


class DetalleERP(AccesoERP):
    """Detalle de un documento del ERP y sus acciones (líneas, confirmar, aprobar, contabilizar, eliminar
    borrador). Ruta: `/panel/erp/<slug:modulo>/<uuid:pk>/` («erp_detalle»).
    """
    def objeto(self, request, pk):
        return get_object_or_404(self.config["model"].objects.filter(empresa=request.empresa), pk=pk)

    def mostrar(self, request, modulo, obj, form=None):
        """Renderiza el detalle del documento con sus líneas, acciones y formulario de líneas."""
        config = self.config
        cerrado = bool(getattr(obj, config.get("cerrado", ""), False))
        lineas, cabeceras = [], []
        if "linea" in config:
            campos = config["campos_linea"]
            qs = config["linea"].objects.filter(empresa=request.empresa, **{config["relacion"]: obj})
            lineas = [{"pk": linea.pk, "valores": [valor(linea, c) for c in campos]} for linea in qs]
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
        prefijos_ref = {
            "compras": f"COMP-{obj.pk}",
            "tesoreria": f"TES-{getattr(obj, 'operacion', obj.pk)}",
            "nomina": f"NOM-{obj.pk}",
        }
        asiento_contable = (
            m.AsientoContable.objects.filter(empresa=request.empresa, referencia=prefijos_ref[modulo]).first()
            if modulo in prefijos_ref
            else None
        )
        puede_contabilizar = (
            modulo in prefijos_ref
            and (cerrado or modulo == "tesoreria")
            and request.membresia.tiene_permiso("contabilidad.gestionar")
        )
        puede_tesoreria = request.membresia.tiene_permiso("tesoreria.gestionar")
        aportes_ley = (
            calcular_aportes_nomina_colombia(salario_base=obj.base, adicionales_salariales=obj.adicionales,
                                             auxilio_transporte=obj.auxilio_transporte)
            if modulo == "nomina"
            else None
        )
        return render(request, "core/erp/detalle.html", {"config": config, "modulo": modulo, "obj": obj,
            "datos": [(etiqueta(config["model"], c), valor(obj, c)) for c in campos_detalle],
            "lineas": lineas, "cabeceras": cabeceras, "form": form, "cerrado": cerrado, "puede_gestionar": self.puede_gestionar(),
            "cartera": cartera_rel, "abonos": abonos, "asiento_contable": asiento_contable,
            "puede_contabilizar": puede_contabilizar, "puede_tesoreria": puede_tesoreria, "aportes_ley": aportes_ley})

    def get(self, request, modulo, pk):
        return self.mostrar(request, modulo, self.objeto(request, pk))

    # Acciones propias de un módulo: (módulo, acción) → método. Las de líneas, contabilizar y eliminar
    # borrador aplican a varios módulos y se resuelven en _ejecutar (QA-05: antes era un solo if/elif de 34 caminos).
    ACCIONES_MODULO = {
        ("compras", "recibir"): "_recibir_compra",
        ("contabilidad", "confirmar"): "_confirmar_asiento",
        ("nomina", "aprobar"): "_aprobar_nomina",
        ("nomina", "calcular_aportes"): "_calcular_aportes",
        ("produccion", "producir"): "_completar_produccion",
        ("agenda", "atendida"): "_cambiar_cita",
        ("agenda", "cancelada"): "_cambiar_cita",
        ("tesoreria", "conciliar"): "_conciliar",
    }
    CONTABILIZABLES = {
        "compras": lambda obj, usuario: contabilizar_compra(compra=obj, usuario=usuario),
        "tesoreria": lambda obj, usuario: contabilizar_movimiento_tesoreria(movimiento=obj, usuario=usuario),
        "nomina": lambda obj, usuario: contabilizar_nomina(nomina=obj, usuario=usuario),
    }

    def post(self, request, modulo, pk):
        self.objeto(request, pk)  # 404 si el documento no es de esta empresa
        accion = request.POST.get("accion")
        try:
            with transaction.atomic():
                obj = s.bloquear(self.config["model"], request.empresa, pk)
                respuesta = self._ejecutar(request, modulo, accion, obj)
                if respuesta is not None:
                    return respuesta
            messages.success(request, "Operación realizada.")
        except (ValidationError, StockInsuficiente, ValueError) as error:
            messages.error(request, " ".join(error.messages) if isinstance(error, ValidationError) else str(error))
        except IntegrityError:
            messages.error(request, "La operación entra en conflicto con un registro existente.")
        return redirect("erp_detalle", modulo=modulo, pk=pk)

    def _ejecutar(self, request, modulo, accion, obj):
        """Ejecuta la acción pedida. Devuelve una respuesta solo cuando no se vuelve al detalle."""
        if accion in ("agregar", "quitar") and "linea" in self.config:
            return self._accion_linea(request, modulo, accion, obj)
        metodo = self.ACCIONES_MODULO.get((modulo, accion))
        if metodo:
            return getattr(self, metodo)(request, obj, accion)
        if accion == "contabilizar" and modulo in self.CONTABILIZABLES:
            if not request.membresia.tiene_permiso("contabilidad.gestionar"):
                raise PermissionDenied
            self.CONTABILIZABLES[modulo](obj, request.user)
            return None
        if accion == "eliminar_borrador" and "cerrado" in self.config:
            return self._eliminar_borrador(request, modulo, obj)
        raise ValidationError("Acción no válida para este documento.")

    # ---------- Acciones ----------
    def _accion_linea(self, request, modulo, accion, obj):
        """Agrega o quita una línea del documento mientras siga en borrador."""
        if getattr(obj, self.config["cerrado"]):
            raise ValidationError("El documento ya está confirmado y no se puede modificar.")
        if accion == "quitar":
            from .http_utils import obtener_por_uuid_o_404

            linea = obtener_por_uuid_o_404(
                self.config["linea"],
                request.POST.get("linea"),
                empresa=request.empresa,
                **{self.config["relacion"]: obj},
            )
            linea.delete()
            return None
        form = formulario(self.config["linea"], self.config["campos_linea"])(request.POST, empresa=request.empresa)
        if not form.is_valid():
            return self.mostrar(request, modulo, obj, form)
        linea = form.save(commit=False)
        setattr(linea, self.config["relacion"], obj)
        s.guardar(linea)
        return None

    def _recibir_compra(self, request, obj, accion):
        s.recibir_compra(empresa=request.empresa, pk=obj.pk, usuario=request.user)

    def _confirmar_asiento(self, request, obj, accion):
        s.confirmar_asiento(empresa=request.empresa, pk=obj.pk)

    def _aprobar_nomina(self, request, obj, accion):
        s.aprobar_nomina(empresa=request.empresa, pk=obj.pk)

    def _completar_produccion(self, request, obj, accion):
        s.completar_produccion(empresa=request.empresa, pk=obj.pk, usuario=request.user)

    def _cambiar_cita(self, request, obj, accion):
        s.cambiar_cita(empresa=request.empresa, pk=obj.pk, estado=accion)

    def _conciliar(self, request, obj, accion):
        """Marca el movimiento de tesorería como conciliado."""
        obj.conciliado = True
        s.guardar(obj)

    def _calcular_aportes(self, request, obj, accion):
        """Salud y pensión del empleado: los adicionales salariales aportan; el auxilio de transporte no."""
        if obj.aprobada:
            raise ValidationError("La nómina ya fue aprobada.")
        aportes = calcular_aportes_nomina_colombia(
            salario_base=obj.base, adicionales_salariales=obj.adicionales,
            auxilio_transporte=obj.auxilio_transporte,
        )
        obj.deducciones = aportes["deducciones_empleado"]
        obj.neto = obj.base + obj.adicionales + obj.auxilio_transporte - obj.deducciones
        s.guardar(obj)

    def _eliminar_borrador(self, request, modulo, obj):
        """Elimina un documento en borrador y sus líneas."""
        if getattr(obj, self.config["cerrado"]):
            raise ValidationError("El documento ya está confirmado y no se puede eliminar.")
        if "linea" in self.config:
            self.config["linea"].objects.filter(empresa=request.empresa, **{self.config["relacion"]: obj}).delete()
        obj.delete()
        messages.success(request, "Borrador eliminado.")
        return redirect("erp_lista", modulo=modulo)


class CarteraFacturaERP(AccesoERP):
    """Lleva una factura de venta a cartera (cuenta por cobrar) con su vencimiento. Ruta:
    `/panel/erp/cartera/factura/` («erp_cartera_factura»).
    """
    def get(self, request):
        if not request.membresia.tiene_permiso("cartera.gestionar") or not request.membresia.tiene_permiso("ventas.ver"):
            raise PermissionDenied
        return self.mostrar(request, CarteraFacturaForm(empresa=request.empresa))

    def mostrar(self, request, form):
        return render(request, "core/erp/form.html", {"form": form, "config": {"titulo": "Llevar factura a cartera"}, "modulo": "cartera"})

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


def _datos_reportes(request):
    """Datos de los reportes del ERP que el rol puede ver (cartera, tesorería y balance)."""
    datos = {"titulo": "Reportes operativos"}
    if request.membresia.tiene_permiso("cartera.ver"):
        cartera = m.CuentaCartera.objects.filter(empresa=request.empresa)
        datos["cartera"] = [
            {
                "tipo": titulo,
                "total": cartera.filter(tipo=tipo).aggregate(v=Sum(F("total") - F("abonado")))["v"] or 0,
            }
            for tipo, titulo in [("cobrar", "Por cobrar"), ("pagar", "Por pagar")]
        ]
    if request.membresia.tiene_permiso("tesoreria.ver"):
        movimientos = m.MovimientoTesoreria.objects.filter(empresa=request.empresa)
        agrupados = movimientos.values("cuenta_id", "tipo").annotate(total=Sum("monto"))
        saldos = {}
        for fila in agrupados:
            saldos[fila["cuenta_id"]] = saldos.get(fila["cuenta_id"], 0) + (
                fila["total"] if fila["tipo"] == "ingreso" else -fila["total"]
            )
        datos["cuentas"] = [
            {"nombre": c.nombre, "saldo": saldos.get(c.pk, 0)}
            for c in m.CuentaTesoreria.objects.filter(empresa=request.empresa)
        ]
    if request.membresia.tiene_permiso("contabilidad.ver"):
        lineas = m.LineaAsiento.objects.filter(empresa=request.empresa, asiento__confirmado=True)
        datos["balance"] = list(
            lineas.values("cuenta__codigo", "cuenta__nombre")
            .annotate(debito=Sum("debito"), credito=Sum("credito"))
            .order_by("cuenta__codigo")
        )

    from django.db.models import Avg, Count

    facturas_emitidas = m.Factura.objects.filter(
        empresa=request.empresa, estado=m.Factura.Estado.EMITIDA
    )
    datos["ventas_por_bodega"] = list(
        facturas_emitidas.values("bodega__nombre")
        .annotate(facturas=Count("id"), subtotal=Sum("subtotal"), total=Sum("total"))
        .order_by("-total")
    )
    datos["ventas_por_turno"] = list(
        facturas_emitidas.filter(turno__isnull=False)
        .values("turno_id", "turno__cajero__email", "turno__bodega__nombre", "turno__creado_en")
        .annotate(facturas=Count("id"), total=Sum("total"))
        .order_by("-turno__creado_en")[:20]
    )

    costos_promedio = {
        row["producto_id"]: row["costo_prom"] or Decimal("0")
        for row in m.LineaCompra.objects.filter(
            empresa=request.empresa, compra__recibida=True
        )
        .values("producto_id")
        .annotate(costo_prom=Avg("costo"))
    }
    existencias_map = {
        (row["bodega_id"], row["producto_id"]): row["cantidad"]
        for row in m.Existencia.objects.filter(empresa=request.empresa).values(
            "bodega_id", "producto_id", "cantidad"
        )
    }
    detalles_agg = (
        m.DetalleFactura.objects.filter(
            empresa=request.empresa, factura__estado=m.Factura.Estado.EMITIDA
        )
        .values("factura__bodega_id", "factura__bodega__nombre", "producto_id", "producto__codigo", "producto__nombre", "producto__stock")
        .annotate(
            unidades=Sum("cantidad"),
            ingresos=Sum(
                F("cantidad") * F("precio_unitario"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        )
        .order_by("-unidades")[:30]
    )
    rotacion_margenes = []
    for det in detalles_agg:
        unidades = int(det["unidades"] or 0)
        ingresos = det["ingresos"] or Decimal("0")
        costo_unit = costos_promedio.get(det["producto_id"], Decimal("0"))
        costo_est = costo_unit * unidades
        margen = ingresos - costo_est
        stock_bod = (
            existencias_map.get((det["factura__bodega_id"], det["producto_id"]), 0)
            if det["factura__bodega_id"]
            else int(det["producto__stock"] or 0)
        )
        rotacion = round(unidades / stock_bod, 2) if stock_bod > 0 else float(unidades)
        rotacion_margenes.append(
            {
                "codigo": det["producto__codigo"],
                "producto": det["producto__nombre"],
                "bodega": det["factura__bodega__nombre"] or "Sin bodega",
                "unidades": unidades,
                "ingresos": ingresos,
                "costo_estimado": costo_est,
                "margen": margen,
                "stock_actual": stock_bod,
                "rotacion": rotacion,
            }
        )
    datos["rotacion_margenes"] = rotacion_margenes
    return datos


class ReportesERP(AccesoERP):
    """Reportes del ERP: cartera pendiente, saldos de cajas y bancos y balance de comprobación. Ruta:
    `/panel/erp/reportes/` («erp_reportes»).
    """
    def get(self, request):
        if not request.membresia.tiene_permiso("reportes.ver"):
            raise PermissionDenied
        return render(request, "core/erp/reportes.html", _datos_reportes(request))


class ReportesExportarExcelView(AccesoERP):
    """Exporta los reportes financieros a Excel (.xlsx), sujeto a la feature 'exportacion' del plan."""

    def get(self, request):
        if not request.membresia.tiene_permiso("reportes.ver"):
            raise PermissionDenied
        from suscripciones.services import crear_suscripcion_inicial

        sub = crear_suscripcion_inicial(request.empresa)
        if not sub.puede("exportacion"):
            messages.error(
                request,
                f"La exportación a Excel está disponible en el plan Pro (tu plan actual es {sub.plan.nombre}).",
            )
            return redirect("suscripcion_panel")

        from .exportaciones import generar_reporte_erp_excel

        datos = _datos_reportes(request)
        contenido = generar_reporte_erp_excel(
            empresa=request.empresa,
            cartera=datos.get("cartera"),
            cuentas=datos.get("cuentas"),
            balance=datos.get("balance"),
        )
        respuesta = HttpResponse(
            contenido,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        respuesta["Content-Disposition"] = f'attachment; filename="reporte-{request.empresa.slug}.xlsx"'
        return respuesta
