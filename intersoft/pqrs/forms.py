"""Formularios de PQRS para compradores, negocios (/panel/) e Intersoft (/plataforma/)."""
from django.utils.translation import gettext, gettext_lazy
from django import forms

from core.models import Empresa, Pedido, Usuario

from .models import PQRS, MensajePQRS


class RadicarPQRSCompradorForm(forms.Form):
    """Formulario para que un comprador radique una PQRS (flujo B) en /pqrs/."""

    tipo = forms.ChoiceField(label=gettext_lazy("Tipo de solicitud"), choices=PQRS.Tipo.choices)
    pedido = forms.ModelChoiceField(
        label=gettext_lazy("Pedido relacionado (opcional)"),
        queryset=Pedido.objects.none(),
        required=False,
        empty_label=gettext_lazy("Sin pedido específico"),
    )
    empresa = forms.ModelChoiceField(
        label=gettext_lazy("Negocio"),
        queryset=Empresa.objects.filter(activa=True).order_by("nombre"),
        required=False,
        empty_label=gettext_lazy("Selecciona un negocio (si no elegiste pedido)"),
    )
    asunto = forms.CharField(label=gettext_lazy("Asunto"), max_length=160)
    descripcion = forms.CharField(label=gettext_lazy("Descripción"), widget=forms.Textarea(attrs={"rows": 4}))
    adjunto = forms.FileField(
        label=gettext_lazy("Adjunto (imagen o PDF, máx. 5 MB)"),
        required=False,
    )

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        if usuario is not None:
            self.fields["pedido"].queryset = (
                Pedido.objects.filter(comprador=usuario)
                .select_related("empresa")
                .order_by("-creado_en")
            )

    def clean(self):
        datos = super().clean()
        pedido = datos.get("pedido")
        empresa = datos.get("empresa")
        if pedido is not None:
            datos["empresa"] = pedido.empresa
        elif empresa is None:
            self.add_error("empresa", gettext("Selecciona un negocio o un pedido."))
        return datos


class RadicarPQRSNegocioForm(forms.Form):
    """Formulario para que un negocio radique una PQRS hacia Intersoft (flujo A) en /panel/pqrs/."""

    tipo = forms.ChoiceField(label=gettext_lazy("Tipo de solicitud"), choices=PQRS.Tipo.choices)
    prioridad = forms.ChoiceField(
        label=gettext_lazy("Prioridad"),
        choices=PQRS.Prioridad.choices,
        initial=PQRS.Prioridad.MEDIA,
    )
    asunto = forms.CharField(label=gettext_lazy("Asunto"), max_length=160)
    descripcion = forms.CharField(label=gettext_lazy("Descripción"), widget=forms.Textarea(attrs={"rows": 4}))
    adjunto = forms.FileField(
        label=gettext_lazy("Adjunto (imagen o PDF, máx. 5 MB)"),
        required=False,
    )


class MensajePQRSForm(forms.ModelForm):
    """Formulario para responder en el hilo de una PQRS."""

    class Meta:
        model = MensajePQRS
        fields = ["texto", "adjunto", "interno"]
        widgets = {
            "texto": forms.Textarea(attrs={"rows": 3, "placeholder": gettext_lazy("Escribe tu mensaje o respuesta...")}),
        }

    def __init__(self, *args, permitir_interno: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        if not permitir_interno:
            self.fields.pop("interno", None)


class EncuestaSatisfaccionForm(forms.Form):
    """Encuesta de satisfacción al cerrar una PQRS (1 a 5)."""

    calificacion = forms.TypedChoiceField(
        label=gettext_lazy("Califica la atención recibida"),
        choices=[(i, f"{i} / 5") for i in range(1, 6)],
        coerce=int,
    )
    comentario_satisfaccion = forms.CharField(
        label=gettext_lazy("Comentario opcional"),
        max_length=255,
        required=False,
    )


class GestionPQRSPlataformaForm(forms.Form):
    """Formulario para actualizar estado, prioridad y asignación desde /plataforma/pqrs/."""

    estado = forms.ChoiceField(label=gettext_lazy("Estado"), choices=PQRS.Estado.choices)
    prioridad = forms.ChoiceField(label=gettext_lazy("Prioridad"), choices=PQRS.Prioridad.choices)
    asignado_a = forms.ModelChoiceField(
        label=gettext_lazy("Asignado a"),
        queryset=Usuario.objects.filter(is_staff=True, is_active=True).order_by("email"),
        required=False,
        empty_label=gettext_lazy("Sin asignar"),
    )
