"""Gestión de cupones de descuento de cada negocio para su tienda en el marketplace."""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from .http_utils import obtener_por_uuid_o_404
from .mixins import PermisoRequeridoMixin
from .models import CuponTienda
from .validadores import validar_codigo_comercial


class CuponTiendaForm(forms.ModelForm):
    """Formulario para crear cupones de descuento propios del negocio."""

    class Meta:
        model = CuponTienda
        fields = ["codigo", "tipo", "valor", "monto_minimo", "usos_maximos", "vence_en", "activo"]
        widgets = {
            "codigo": forms.TextInput(attrs={"placeholder": "Ej.: BIENVENIDO10", "autocomplete": "off"}),
            "valor": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "placeholder": "10"}),
            "monto_minimo": forms.NumberInput(attrs={"step": "100", "min": "0", "placeholder": "0"}),
            "usos_maximos": forms.NumberInput(attrs={"min": "1", "placeholder": "Sin límite"}),
            "vence_en": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["monto_minimo"].required = False
        self.fields["usos_maximos"].required = False
        self.fields["vence_en"].required = False

    def clean_codigo(self):
        codigo = validar_codigo_comercial(self.cleaned_data.get("codigo"), ejemplo="PROMO15")
        if not codigo:
            raise forms.ValidationError("Escribe un código sin espacios (ej.: PROMO15).")
        return codigo

    def clean_monto_minimo(self):
        return self.cleaned_data.get("monto_minimo") or Decimal("0.00")

    def clean(self):
        datos = super().clean()
        tipo = datos.get("tipo")
        valor = datos.get("valor")
        if tipo == CuponTienda.Tipo.PORCENTAJE and valor is not None and valor > Decimal("100"):
            self.add_error("valor", "Un descuento en porcentaje no puede superar el 100%.")
        vence = datos.get("vence_en")
        if vence and vence <= timezone.now():
            self.add_error("vence_en", "La fecha de vencimiento debe estar en el futuro.")
        return datos


class CuponesPanelView(PermisoRequeridoMixin, View):
    """Lista y administración de cupones de tienda del negocio (/panel/cupones/)."""

    permiso_requerido = "ventas.crear"
    template_name = "core/cupones_panel.html"

    def _contexto(self, request, form=None):
        """Construye el contexto del panel de cupones con métricas y formulario."""
        cupones = list(CuponTienda.objects.de_empresa(request.empresa).order_by("-creado_en"))
        activos = sum(1 for c in cupones if c.esta_vigente)
        usos_totales = sum(c.usos_actuales for c in cupones)
        return {
            "cupones": cupones,
            "activos": activos,
            "usos_totales": usos_totales,
            "form": form or CuponTiendaForm(),
        }

    def get(self, request):
        return render(request, self.template_name, self._contexto(request))

    def post(self, request):
        accion = request.POST.get("accion", "crear")

        if accion == "toggle":
            cupon = obtener_por_uuid_o_404(
                CuponTienda.objects.de_empresa(request.empresa),
                request.POST.get("cupon_id"),
            )
            cupon.activo = not cupon.activo
            cupon.save(update_fields=["activo", "actualizado_en"])
            estado = "activado" if cupon.activo else "desactivado"
            messages.success(request, f"Cupón «{cupon.codigo}» {estado}.")
            return redirect("cupones_panel")

        if accion == "eliminar":
            cupon = obtener_por_uuid_o_404(
                CuponTienda.objects.de_empresa(request.empresa),
                request.POST.get("cupon_id"),
            )
            if cupon.usos_actuales > 0:
                messages.warning(request, f"El cupón «{cupon.codigo}» ya fue usado; desactívalo en lugar de eliminarlo.")
            else:
                codigo = cupon.codigo
                cupon.delete()
                messages.success(request, f"Cupón «{codigo}» eliminado.")
            return redirect("cupones_panel")

        form = CuponTiendaForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(request, form=form), status=400)

        cupon = form.save(commit=False)
        cupon.empresa = request.empresa
        try:
            with transaction.atomic():
                cupon.save()
        except IntegrityError:
            form.add_error("codigo", "Ya existe un cupón con este código en tu negocio.")
            return render(request, self.template_name, self._contexto(request, form=form), status=400)

        messages.success(request, f"Cupón «{cupon.codigo}» creado correctamente.")
        return redirect("cupones_panel")
