"""Formularios del ERP con relaciones limitadas a la empresa activa."""
import uuid

from django import forms
from django.db.models import F

from . import models


class FormularioERP(forms.ModelForm):
    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.empresa = empresa
        for nombre, campo in self.fields.items():
            if isinstance(campo, forms.ModelChoiceField):
                campo.queryset = campo.queryset.filter(empresa=empresa)
                if hasattr(campo.queryset.model, "activo"):
                    campo.queryset = campo.queryset.filter(activo=True)
            if isinstance(campo, forms.DateTimeField):
                campo.widget = forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})
            elif isinstance(campo, forms.DateField):
                campo.widget = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
            elif isinstance(campo.widget, forms.Textarea):
                campo.widget.attrs["rows"] = 3


def formulario(modelo, campos):
    return forms.modelform_factory(modelo, form=FormularioERP, fields=campos)


class MovimientoForm(forms.Form):
    cuenta = forms.ModelChoiceField(queryset=models.CuentaTesoreria.objects.none())
    tipo = forms.ChoiceField(choices=[("ingreso", "Ingreso"), ("egreso", "Egreso")])
    fecha = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    concepto = forms.CharField(max_length=200)
    monto = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    cartera = forms.ModelChoiceField(queryset=models.CuentaCartera.objects.none(), required=False,
                                    label="Aplicar a cuenta por cobrar / pagar")
    referencia = forms.CharField(max_length=100, required=False)
    operacion = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = models.CuentaTesoreria.objects.filter(empresa=empresa, activa=True)
        self.fields["cartera"].queryset = models.CuentaCartera.objects.filter(empresa=empresa, abonado__lt=F("total"))


class CarteraFacturaForm(forms.Form):
    factura = forms.ModelChoiceField(queryset=models.Factura.objects.none())
    vencimiento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["factura"].queryset = models.Factura.objects.filter(empresa=empresa, estado="emitida", cuentacartera__isnull=True)
