"""Formularios públicos del marketplace: registro de compradores y negocios, datos de envío y opiniones."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator

from .models import Cliente, Comentario, Empresa
from .validadores import (
    validar_ciudad,
    validar_correo_registro,
    validar_direccion,
    validar_documento_por_tipo,
    validar_nit_negocio,
    validar_nombre_negocio,
    validar_nombre_persona,
    validar_texto_util,
)

Usuario = get_user_model()

DEPARTAMENTOS = [
    "Amazonas", "Antioquia", "Arauca", "Atlántico", "Bogotá D.C.", "Bolívar", "Boyacá", "Caldas",
    "Caquetá", "Casanare", "Cauca", "Cesar", "Chocó", "Córdoba", "Cundinamarca", "Guainía",
    "Guaviare", "Huila", "La Guajira", "Magdalena", "Meta", "Nariño", "Norte de Santander",
    "Putumayo", "Quindío", "Risaralda", "San Andrés y Providencia", "Santander", "Sucre",
    "Tolima", "Valle del Cauca", "Vaupés", "Vichada",
]


class RegistroCompradorForm(UserCreationForm):
    """Formulario de usuario. Campos: first_name, last_name, email, password1, password2."""
    first_name = forms.CharField(label="Nombres", max_length=150)
    last_name = forms.CharField(label="Apellidos", max_length=150)
    # 150 y no 254: el correo también se guarda como username, que admite 150
    email = forms.EmailField(label="Correo electrónico", max_length=150)
    # Ley 1581 art. 9: autorización previa, expresa e informada. Nunca viene marcada por defecto.
    acepta_datos = forms.BooleanField(
        label="Autorizo el tratamiento de mis datos personales según la Política de tratamiento de datos.",
        error_messages={"required": "Para crear la cuenta debes autorizar el tratamiento de tus datos."},
    )
    mayor_edad = forms.BooleanField(
        label="Declaro que soy mayor de 18 años.",
        error_messages={"required": "Solo personas mayores de edad pueden crear una cuenta."},
    )

    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ["first_name", "last_name", "email"]

    def clean_first_name(self):
        """Valida que los nombres solo contengan caracteres reales de persona."""
        return validar_nombre_persona(self.cleaned_data["first_name"])

    def clean_last_name(self):
        """Valida que los apellidos solo contengan caracteres reales de persona."""
        return validar_nombre_persona(self.cleaned_data["last_name"])

    def clean_email(self):
        correo = validar_correo_registro(self.cleaned_data["email"])
        # Se revisa también username porque una cuenta creada con otro método puede tener este valor
        if Usuario.objects.filter(email__iexact=correo).exists() or Usuario.objects.filter(username__iexact=correo).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return correo

    def save(self, commit=True):
        self.instance.username = self.cleaned_data["email"]
        return super().save(commit=commit)


class RegistroNegocioForm(forms.ModelForm):
    """Formulario de empresa. Campos: nombre, nit, email, telefono, direccion."""
    class Meta:
        model = Empresa
        # slug, plan y activa los decide el servidor
        fields = ["nombre", "nit", "email", "telefono", "direccion"]
        labels = {
            "nombre": "Nombre del negocio",
            "nit": "NIT",
            "email": "Correo del negocio",
            "telefono": "Teléfono",
            "direccion": "Dirección de notificaciones",
        }
        error_messages = {"nit": {"unique": "Ya existe un negocio registrado con este NIT."}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hacer_obligatorios_datos_legales(self)

    def clean_nombre(self):
        """Valida que el nombre del negocio use solo letras, números y signos comerciales permitidos."""
        return validar_nombre_negocio(self.cleaned_data["nombre"])

    def clean_nit(self):
        """Valida el formato numérico del NIT y lo normaliza sin puntos ni espacios."""
        return validar_nit_negocio(self.cleaned_data["nit"])

    def clean_direccion(self):
        """Valida la dirección legal de notificaciones del negocio."""
        return validar_direccion(self.cleaned_data["direccion"])


def hacer_obligatorios_datos_legales(form):
    """Ley 1480, art. 53: el comprador debe poder identificar y contactar al vendedor."""
    form.fields["direccion"].required = True
    form.fields["direccion"].help_text = "Donde el negocio recibe notificaciones. La verán tus compradores."
    form.fields["telefono"].required = True
    form.fields["telefono"].validators.append(
        RegexValidator(r"^\+?[0-9\s-]{7,20}$", "Escribe un teléfono válido, por ejemplo 601 234 5678.")
    )


class DatosEnvioForm(forms.Form):
    """Formulario. Campos: nombre, tipo_documento, numero_documento, email, telefono, departamento, ciudad,
    direccion….
    """
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

    def clean_nombre(self):
        """Valida el nombre del comprador en el checkout."""
        return validar_nombre_persona(self.cleaned_data["nombre"])

    def clean_ciudad(self):
        """Valida el nombre de la ciudad o municipio de entrega."""
        return validar_ciudad(self.cleaned_data["ciudad"])

    def clean_direccion(self):
        """Valida la dirección de entrega con nomenclatura real."""
        return validar_direccion(self.cleaned_data["direccion"])

    def clean_numero_documento(self):
        return self.cleaned_data["numero_documento"].replace(".", "").replace(" ", "")

    def clean(self):
        """Valida el número de documento según el tipo elegido (CC, CE, NIT o PP)."""
        datos = super().clean()
        tipo = datos.get("tipo_documento")
        numero = datos.get("numero_documento")
        if tipo and numero:
            try:
                datos["numero_documento"] = validar_documento_por_tipo(tipo, numero)
            except forms.ValidationError as exc:
                self.add_error("numero_documento", exc)
        return datos


class ComentarioForm(forms.ModelForm):
    """Formulario de comentario. Campos: calificacion, texto."""
    class Meta:
        model = Comentario
        fields = ["calificacion", "texto"]
        error_messages = {
            "calificacion": {"required": "Elige de 1 a 5 estrellas.", "invalid": "Elige de 1 a 5 estrellas."},
            "texto": {"required": "Cuéntanos un poco más en tu comentario."},
        }

    def clean_texto(self):
        """Rechaza reseñas vacías o de relleno repetitivo."""
        return validar_texto_util(self.cleaned_data["texto"], min_caracteres=3)
