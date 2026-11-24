"""Formularios de protección de datos: autorización y solicitudes del titular."""
from django import forms

from .models import SolicitudDatos


class AutorizacionForm(forms.Form):
    """Aceptación expresa de la política vigente. Las casillas nunca vienen marcadas."""

    acepta_datos = forms.BooleanField(
        label="Autorizo el tratamiento de mis datos personales para las finalidades descritas.",
        error_messages={"required": "Debes marcar la autorización para seguir usando tu cuenta."},
    )
    mayor_edad = forms.BooleanField(
        label="Declaro que soy mayor de 18 años.",
        error_messages={"required": "Solo personas mayores de edad pueden usar una cuenta."},
    )


class SolicitudDatosForm(forms.ModelForm):
    """Radicación de una consulta o reclamo sobre los datos personales del titular."""

    class Meta:
        model = SolicitudDatos
        fields = ["tipo", "detalle"]
        labels = {"tipo": "¿Qué necesitas?", "detalle": "Cuéntanos los detalles (opcional)"}
        widgets = {"detalle": forms.Textarea(attrs={"rows": 3, "maxlength": 2000})}


class RespuestaSolicitudForm(forms.Form):
    """Respuesta del equipo al titular desde la consola de plataforma."""

    respuesta = forms.CharField(label="Respuesta para el titular", widget=forms.Textarea(attrs={"rows": 5}),
                                max_length=4000)
