from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Empresa

Usuario = get_user_model()


class RegistroCompradorForm(UserCreationForm):
    first_name = forms.CharField(label="Nombres", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150)
    # 150 y no 254: el correo también se guarda como username, que admite 150
    email = forms.EmailField(label="Correo electrónico", max_length=150)

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ["first_name", "last_name", "email"]

    def clean_email(self):
        correo = self.cleaned_data["email"].lower()
        # Se revisa también username porque una cuenta creada con otro método puede tener este valor
        if Usuario.objects.filter(email__iexact=correo).exists() or Usuario.objects.filter(username__iexact=correo).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return correo

    def save(self, commit=True):
        self.instance.username = self.cleaned_data["email"]
        return super().save(commit=commit)


class RegistroNegocioForm(forms.ModelForm):
    class Meta:
        model = Empresa
        # slug, plan y activa los decide el servidor
        fields = ["nombre", "nit", "email", "telefono", "direccion"]
        labels = {
            "nombre": "Nombre del negocio",
            "nit": "NIT",
            "email": "Correo del negocio",
            "telefono": "Teléfono",
            "direccion": "Dirección",
        }
        error_messages = {"nit": {"unique": "Ya existe un negocio registrado con este NIT."}}

    def clean_nit(self):
        return self.cleaned_data["nit"].replace(".", "").replace(" ", "")
