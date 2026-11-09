from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator

from .models import Cliente, Comentario, Empresa

Usuario = get_user_model()

DEPARTAMENTOS = [
    "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bogotá D.C.", "Bolívar", "Boyacá", "Caldas",
    "Caquetá", "Casanare", "Cauca", "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía",
    "Guaviare", "Huila", "La Guajira", "Magdalena", "Meta", "Nariño", "Norte de Santander",
    "Putumayo", "Quindío", "Risaralda", "San Andrés y Providencia", "Santander", "Sucre",
    "Tolima", "Valle del Cauca", "Vaupés", "Vichada",
]


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


class DatosEnvioForm(forms.Form):
    nombre = forms.CharField(
        label="Nombre completo", max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    tipo_documento = forms.ChoiceField(label="Tipo de documento", choices=Cliente.TipoDocumento.choices)
    numero_documento = forms.CharField(
        label="Número de documento", max_length=20,
        help_text="Lo necesitamos para tu factura.",
        validators=[RegexValidator(r"^[0-9A-Za-z.\s-]+$", "Escribe solo números y letras.")],
    )
    email = forms.EmailField(
        label="Correo electrónico", max_length=150,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    telefono = forms.CharField(
        label="Celular", max_length=20,
        help_text="Para avisarte cuando tu pedido vaya en camino.",
        validators=[RegexValidator(r"^\+?[0-9\s-]{7,20}$", "Escribe un número válido, por ejemplo 300 123 4567.")],
        widget=forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel"}),
    )
    departamento = forms.ChoiceField(
        label="Departamento",
        choices=[("", "Elige tu departamento")] + [(d, d) for d in DEPARTAMENTOS],
    )
    ciudad = forms.CharField(
        label="Ciudad o municipio", max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "address-level2"}),
    )
    direccion = forms.CharField(
        label="Dirección", max_length=200,
        widget=forms.TextInput(attrs={"autocomplete": "street-address", "placeholder": "Calle 10 # 20-30"}),
    )
    indicaciones = forms.CharField(
        label="Indicaciones de entrega (opcional)", max_length=200, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Apartamento, torre, barrio o una referencia"}),
    )

    def clean_numero_documento(self):
        return self.cleaned_data["numero_documento"].replace(".", "").replace(" ", "")


class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ["calificacion", "texto"]
        error_messages = {
            "calificacion": {"required": "Elige de 1 a 5 estrellas.", "invalid": "Elige de 1 a 5 estrellas."},
            "texto": {"required": "Cuéntanos un poco más en tu comentario."},
        }
