"""Formularios de soporte, feedback e ideas."""
from django.utils.translation import gettext_lazy
from django import forms

from .models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, Idea, ReporteProblema


class ReporteProblemaForm(forms.ModelForm):
    """Formulario corto para que el usuario reporte un problema desde el panel."""

    url = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = ReporteProblema
        fields = ["url", "descripcion", "captura"]
        labels = {
            "descripcion": gettext_lazy("¿Qué pasó?"),
            "captura": gettext_lazy("Captura de pantalla (opcional, máx. 5 MB)"),
        }
        widgets = {
            "descripcion": forms.Textarea(
                attrs={"rows": 4, "placeholder": gettext_lazy("Cuéntanos brevemente qué estabas haciendo y qué ocurrió...")}
            ),
        }


class ComentarioWidgetForm(forms.ModelForm):
    class Meta:
        model = ComentarioWidget
        fields = ["util", "comentario", "pantalla"]


class EncuestaNPSForm(forms.ModelForm):
    class Meta:
        model = EncuestaNPS
        fields = ["puntaje", "comentario", "pantalla"]


class IdeaForm(forms.ModelForm):
    class Meta:
        model = Idea
        fields = ["titulo", "descripcion"]
        labels = {
            "titulo": gettext_lazy("Título de la idea"),
            "descripcion": gettext_lazy("¿Qué problema resuelve y cómo debería funcionar?"),
        }
        widgets = {
            "descripcion": forms.Textarea(attrs={"rows": 3}),
        }


class ErrorEstadoForm(forms.ModelForm):
    class Meta:
        model = ErrorRegistrado
        fields = ["estado", "notas_internas"]
        widgets = {
            "notas_internas": forms.Textarea(attrs={"rows": 3}),
        }


class IdeaEstadoForm(forms.ModelForm):
    class Meta:
        model = Idea
        fields = ["estado"]
