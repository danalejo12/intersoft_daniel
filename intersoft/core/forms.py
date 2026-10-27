from django import forms

from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        # "empresa" NO está en la lista: la asigna el servidor (TenantMixin.form_valid)
        fields = ["tipo_documento", "numero_documento", "nombre", "email", "telefono", "direccion"]
        labels = {
            "tipo_documento": "Tipo de documento",
            "numero_documento": "Número de documento",
            "email": "Correo electrónico",
            "telefono": "Teléfono",
            "direccion": "Dirección",
        }

    def __init__(self, *args, empresa=None, **kwargs):
        # La vista nos pasa la empresa activa para poder validar duplicados
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        # Opción vacía en español
        self.fields["tipo_documento"].choices = [("", "Selecciona el tipo")] + list(
            Cliente.TipoDocumento.choices
        )

    def clean_numero_documento(self):
        # clean_<campo> valida UN campo. Normalizamos: "1.020.304 050" -> "1020304050"
        numero = self.cleaned_data["numero_documento"]
        return numero.replace(".", "").replace(" ", "")

    def clean(self):
        # clean() valida VARIOS campos juntos (tipo + número)
        datos = super().clean()
        tipo = datos.get("tipo_documento")
        numero = datos.get("numero_documento")

        if tipo and numero and self.empresa:
            existe = (
                Cliente.objects
                .filter(empresa=self.empresa, tipo_documento=tipo, numero_documento=numero)
                .exclude(pk=self.instance.pk)   # al editar, no compararse consigo mismo
                .exists()
            )
            if existe:
                self.add_error("numero_documento", "Ya existe un cliente con este documento en tu empresa.")
        return datos