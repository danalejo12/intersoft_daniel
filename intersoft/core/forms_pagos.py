"""Formulario de la pasarela propia de cada negocio. Los secretos nunca se vuelven a mostrar:
un campo vacío al editar significa «dejar el que ya está»."""
from django.utils.translation import gettext, gettext_lazy
from django import forms
from django.views.decorators.debug import sensitive_variables

from .models import ConfiguracionPagos
from .pasarela_negocio import EJEMPLOS, modo_de_llave

SECRETOS = ("llave_privada", "secreto_integridad", "secreto_eventos")


def _campo_secreto(etiqueta: str, ayuda: str) -> forms.CharField:
    return forms.CharField(
        label=etiqueta, required=False, strip=True, max_length=120, help_text=ayuda,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false"}),
    )


class ConfiguracionPagosForm(forms.ModelForm):
    llave_privada = _campo_secreto(
        gettext_lazy("Llave privada"), gettext_lazy("Opcional. Permite confirmar pagos consultando a Wompi si un aviso se pierde."),
    )
    secreto_integridad = _campo_secreto(gettext_lazy("Secreto de integridad"), gettext_lazy("Firma cada cobro para que nadie altere el monto."))
    secreto_eventos = _campo_secreto(gettext_lazy("Secreto de eventos"), gettext_lazy("Comprueba que los avisos de pago vienen de Wompi."))

    class Meta:
        model = ConfiguracionPagos
        fields = ["llave_publica", "cobrar_tarifa_al_comprador", "tarifa_porcentaje", "tarifa_fija"]
        labels = {"llave_publica": gettext_lazy("Llave pública")}
        help_texts = {"llave_publica": gettext_lazy("La encuentras en Wompi › Desarrolladores › Llaves del API.")}
        widgets = {"llave_publica": forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"})}

    field_order = ["llave_publica", "llave_privada", "secreto_integridad", "secreto_eventos",
                   "cobrar_tarifa_al_comprador", "tarifa_porcentaje", "tarifa_fija"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.existente = not self.instance._state.adding
        for nombre in SECRETOS:
            final = getattr(self.instance, f"{nombre}_final", "") if self.existente else ""
            campo = self.fields[nombre]
            campo.widget.attrs["placeholder"] = gettext("Guardado ····{final} — escribe solo para cambiarlo").format(final=final) if final else EJEMPLOS[nombre]
        self.fields["llave_publica"].widget.attrs["placeholder"] = EJEMPLOS["llave_publica"]

    def clean_llave_publica(self):
        valor = self.cleaned_data["llave_publica"].strip()
        if modo_de_llave("llave_publica", valor) is None:
            raise forms.ValidationError(gettext("No parece una llave pública de Wompi ({llave_publica}).").format(llave_publica=EJEMPLOS['llave_publica']))
        return valor

    @sensitive_variables()
    def _validar_secreto(self, nombre: str) -> str:
        valor = self.cleaned_data.get(nombre, "")
        if valor and modo_de_llave(nombre, valor) is None:
            raise forms.ValidationError(gettext("Formato inválido. Debe empezar por {nombre}").format(nombre=EJEMPLOS[nombre]))
        return valor

    def clean_llave_privada(self):
        return self._validar_secreto("llave_privada")

    def clean_secreto_integridad(self):
        return self._validar_secreto("secreto_integridad")

    def clean_secreto_eventos(self):
        return self._validar_secreto("secreto_eventos")

    @sensitive_variables()
    def clean(self):
        datos = super().clean()
        publica = datos.get("llave_publica")
        if not publica:
            return datos
        modo = modo_de_llave("llave_publica", publica)
        cambio_de_modo = self.existente and modo != self.instance.modo
        for nombre in ("secreto_integridad", "secreto_eventos"):
            if nombre in self.errors:
                continue
            if not datos.get(nombre) and (not self.existente or cambio_de_modo):
                motivo = gettext("Cambiaste de modo: escribe también este secreto.") if cambio_de_modo else gettext("Este secreto es obligatorio.")
                self.add_error(nombre, motivo)
        if cambio_de_modo and not datos.get("llave_privada") and self.instance.llave_privada_final:
            self.add_error("llave_privada", gettext("Cambiaste de modo: escribe también la llave privada de ese modo."))
        for nombre in SECRETOS:
            valor = datos.get(nombre)
            if valor and nombre not in self.errors and modo_de_llave(nombre, valor) != modo:
                self.add_error(nombre, gettext("Es de otro modo que la llave pública: no mezcles llaves de pruebas y de producción."))
        datos["modo"] = modo
        return datos

    @property
    def cambio_llaves(self) -> bool:
        return "llave_publica" in self.changed_data or any(self.cleaned_data.get(n) for n in SECRETOS)

    @sensitive_variables()
    def save(self, commit=True):
        config = super().save(commit=False)
        config.modo = self.cleaned_data["modo"]
        for nombre in SECRETOS:
            valor = self.cleaned_data.get(nombre)
            if valor:
                config.poner_secreto(nombre, valor)
        if self.cambio_llaves:
            # Llaves nuevas: hay que volver a verificarlas antes de cobrar con ellas
            config.verificada_en = None
            config.comercio_verificado = ""
            config.activa = False
        if commit:
            config.save()
        return config
