"""Bodegas o sedes: listado, creación/edición, desactivación y traslados entre bodegas."""
from django.utils.translation import gettext
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import bodegas
from .forms import BodegaForm, TrasladoForm
from .importaciones import importar_productos_excel
from .mixins import PermisoRequeridoMixin
from .models import Bodega, Producto, TrasladoBodega
from .services import StockInsuficiente


class BodegaListView(PermisoRequeridoMixin, View):
    permiso_requerido = "inventario.ver"

    def get(self, request):
        lista = (
            Bodega.objects.de_empresa(request.empresa)
            .annotate(
                unidades=Sum("existencias__cantidad"),
                productos=Count("existencias", filter=Q(existencias__cantidad__gt=0)),
            )
            .order_by("-activa", "-es_principal", "nombre")
        )
        bodegas.bodega_principal(request.empresa)  # un negocio antiguo sin bodegas recibe la suya
        return render(request, "core/bodegas/lista.html", {
            "bodegas": lista,
            "puede_editar": request.membresia.tiene_permiso("inventario.editar"),
            "permite_varias": bodegas.permite_varias_bodegas(request.empresa),
        })


class BodegaFormView(PermisoRequeridoMixin, View):
    permiso_requerido = "inventario.editar"

    def objeto(self, pk):
        return get_object_or_404(Bodega.objects.de_empresa(self.request.empresa), pk=pk) if pk else None

    def get(self, request, pk=None):
        bodega = self.objeto(pk)
        inicial = {}
        if bodega:
            inicial = {"nombre": bodega.nombre, "direccion": bodega.direccion,
                       "es_principal": bodega.es_principal, "vende_en_linea": bodega.vende_en_linea}
        return render(request, "core/bodegas/form.html", {"form": BodegaForm(initial=inicial), "bodega": bodega})

    def post(self, request, pk=None):
        bodega = self.objeto(pk)
        form = BodegaForm(request.POST)
        if form.is_valid():
            try:
                bodega = bodegas.guardar_bodega(empresa=request.empresa, bodega=bodega, **form.cleaned_data)
            except bodegas.OperacionBodega as error:
                form.add_error(None, str(error))
            else:
                messages.success(request, gettext("Bodega «{nombre}» guardada.").format(nombre=bodega.nombre))
                return redirect("bodegas_lista")
        return render(request, "core/bodegas/form.html", {"form": form, "bodega": bodega})


class BodegaDesactivarView(PermisoRequeridoMixin, View):
    permiso_requerido = "inventario.editar"
    http_method_names = ["post"]

    def post(self, request, pk):
        bodega = get_object_or_404(Bodega.objects.de_empresa(request.empresa), pk=pk, activa=True)
        try:
            bodegas.desactivar_bodega(empresa=request.empresa, bodega=bodega)
            messages.success(request, gettext("Desactivamos la bodega «{nombre}».").format(nombre=bodega.nombre))
        except bodegas.OperacionBodega as error:
            messages.error(request, str(error))
        return redirect("bodegas_lista")


class TrasladoView(PermisoRequeridoMixin, View):
    """Pasar unidades de un producto entre bodegas."""

    permiso_requerido = "inventario.movimientos"

    def producto(self, pk):
        return get_object_or_404(Producto, pk=pk, empresa=self.request.empresa, activo=True)

    def mostrar(self, producto, form):
        activas = Bodega.objects.de_empresa(self.request.empresa).filter(activa=True)
        return render(self.request, "core/bodegas/traslado.html", {
            "producto": producto, "form": form,
            "existencias": [(b, bodegas.existencia(producto, b)) for b in activas],
        })

    def get(self, request, pk):
        producto = self.producto(pk)
        return self.mostrar(producto, TrasladoForm(empresa=request.empresa))

    def post(self, request, pk):
        producto = self.producto(pk)
        form = TrasladoForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            en_transito = bool(request.POST.get("en_transito"))
            try:
                if en_transito:
                    bodegas.enviar_traslado(
                        empresa=request.empresa, producto=producto, usuario=request.user, **form.cleaned_data
                    )
                else:
                    bodegas.trasladar(
                        empresa=request.empresa, producto=producto, usuario=request.user, **form.cleaned_data
                    )
            except (StockInsuficiente, ValueError) as error:
                form.add_error("cantidad", str(error))
            else:
                if en_transito:
                    messages.success(
                        request,
                        gettext("Envío en tránsito registrado ({cantidad} de «{nombre}»).").format(cantidad=form.cleaned_data['cantidad'], nombre=producto.nombre),
                    )
                    return redirect("bodegas_traslados")
                messages.success(request, gettext("Trasladamos {cantidad} de «{nombre}».").format(cantidad=form.cleaned_data['cantidad'], nombre=producto.nombre))
                return redirect("productos_kardex", pk=producto.pk)
        return self.mostrar(producto, form)


class TrasladosTransitoListView(PermisoRequeridoMixin, View):
    """Lista los traslados entre bodegas (en tránsito y recibidos)."""

    permiso_requerido = "inventario.ver"

    def get(self, request):
        traslados = TrasladoBodega.objects.filter(empresa=request.empresa).select_related(
            "producto", "origen", "destino", "enviado_por", "recibido_por"
        )[:100]
        return render(
            request,
            "core/bodegas/traslados.html",
            {
                "traslados": traslados,
                "puede_confirmar": request.membresia.tiene_permiso("inventario.movimientos"),
            },
        )


class ConfirmarTrasladoView(PermisoRequeridoMixin, View):
    """Confirma la recepción de un traslado en tránsito en la bodega destino."""

    permiso_requerido = "inventario.movimientos"
    http_method_names = ["post"]

    def post(self, request, pk):
        try:
            traslado = bodegas.confirmar_traslado(empresa=request.empresa, pk=pk, usuario=request.user)
            messages.success(
                request,
                gettext("Recepción confirmada: {cantidad} de «{nombre}» en {nombre2}.").format(cantidad=traslado.cantidad, nombre=traslado.producto.nombre, nombre2=traslado.destino.nombre),
            )
        except bodegas.OperacionBodega as error:
            messages.error(request, str(error))
        return redirect("bodegas_traslados")


class ConteoFisicoView(PermisoRequeridoMixin, View):
    """Hoja imprimible de conteo físico por bodega y ajuste masivo en MovimientoInventario."""

    permiso_requerido = "inventario.movimientos"
    template_name = "core/bodegas/conteo.html"

    def _contexto(self, request, bodega):
        productos = list(Producto.objects.filter(empresa=request.empresa, activo=True).order_by("nombre"))
        existencias = bodegas.existencias_por_producto(bodega, productos)
        filas = [{"producto": p, "stock_sistema": existencias.get(p.pk, 0)} for p in productos]
        return {"bodega": bodega, "filas": filas}

    def get(self, request, pk):
        bodega = get_object_or_404(Bodega.objects.de_empresa(request.empresa), pk=pk, activa=True)
        return render(request, self.template_name, self._contexto(request, bodega))

    def post(self, request, pk):
        bodega = get_object_or_404(Bodega.objects.de_empresa(request.empresa), pk=pk, activa=True)
        conteos = {}
        for clave, valor in request.POST.items():
            if not clave.startswith("conteo_") or valor in (None, ""):
                continue
            prod_id = clave.replace("conteo_", "", 1)
            try:
                conteos[prod_id] = int(valor)
            except ValueError:
                messages.error(request, gettext("Todos los valores de conteo deben ser números enteros."))
                return render(request, self.template_name, self._contexto(request, bodega))

        if not conteos:
            messages.warning(request, gettext("No ingresaste cantidades contadas."))
            return redirect("bodegas_conteo", pk=bodega.pk)

        try:
            bodegas.aplicar_conteo_fisico(
                empresa=request.empresa,
                bodega=bodega,
                conteos=conteos,
                usuario=request.user,
                observaciones=request.POST.get("observaciones", ""),
            )
        except ValueError as error:
            messages.error(request, str(error))
            return render(request, self.template_name, self._contexto(request, bodega))

        messages.success(request, gettext("Conteo físico aplicado en «{nombre}».").format(nombre=bodega.nombre))
        return redirect("bodegas_lista")


class ImportarProductosExcelView(PermisoRequeridoMixin, View):
    """Importación masiva de productos y stock inicial desde Excel (.xlsx)."""

    permiso_requerido = "inventario.crear"
    template_name = "core/productos/importar.html"

    def get(self, request):
        bodegas_activas = Bodega.objects.de_empresa(request.empresa).filter(activa=True)
        return render(request, self.template_name, {"bodegas": bodegas_activas, "errores": []})

    def post(self, request):
        bodegas_activas = Bodega.objects.de_empresa(request.empresa).filter(activa=True)
        archivo = request.FILES.get("archivo")
        if not archivo:
            return render(
                request,
                self.template_name,
                {
                    "bodegas": bodegas_activas,
                    "errores": [{"fila": 1, "error": gettext("Selecciona un archivo .xlsx.")}],
                },
            )
        bodega_id = request.POST.get("bodega")
        bodega = (
            Bodega.objects.de_empresa(request.empresa).filter(pk=bodega_id, activa=True).first()
            if bodega_id
            else None
        )
        resultado = importar_productos_excel(
            empresa=request.empresa, archivo=archivo, usuario=request.user, bodega=bodega
        )
        if resultado["errores"]:
            return render(
                request,
                self.template_name,
                {"bodegas": bodegas_activas, "errores": resultado["errores"]},
            )
        messages.success(request, gettext("Se importaron {creados} producto(s) correctamente.").format(creados=resultado['creados']))
        return redirect("productos_lista")
