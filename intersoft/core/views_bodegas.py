"""Bodegas o sedes: listado, creación/edición, desactivación y traslados entre bodegas."""
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from . import bodegas
from .forms import BodegaForm, TrasladoForm
from .mixins import PermisoRequeridoMixin
from .models import Bodega, Producto
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
                messages.success(request, f"Bodega «{bodega.nombre}» guardada.")
                return redirect("bodegas_lista")
        return render(request, "core/bodegas/form.html", {"form": form, "bodega": bodega})


class BodegaDesactivarView(PermisoRequeridoMixin, View):
    permiso_requerido = "inventario.editar"
    http_method_names = ["post"]

    def post(self, request, pk):
        bodega = get_object_or_404(Bodega.objects.de_empresa(request.empresa), pk=pk, activa=True)
        try:
            bodegas.desactivar_bodega(empresa=request.empresa, bodega=bodega)
            messages.success(request, f"Desactivamos la bodega «{bodega.nombre}».")
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
            try:
                bodegas.trasladar(empresa=request.empresa, producto=producto, usuario=request.user, **form.cleaned_data)
            except (StockInsuficiente, ValueError) as error:
                form.add_error("cantidad", str(error))
            else:
                messages.success(request, f"Trasladamos {form.cleaned_data['cantidad']} de «{producto.nombre}».")
                return redirect("productos_kardex", pk=producto.pk)
        return self.mostrar(producto, form)
