"""Formularios para gestionar roles, permisos y miembros del equipo de una empresa."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Membresia, Permiso, Rol, Usuario
from .permisos import GRUPOS_PERMISOS, sincronizar_catalogo_permisos


class RolForm(forms.ModelForm):
    permisos = forms.ModelMultipleChoiceField(
        queryset=Permiso.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Permisos asignados",
    )

    class Meta:
        model = Rol
        fields = ["nombre", "descripcion", "es_admin", "permisos"]
        labels = {
            "nombre": "Nombre del rol",
            "descripcion": "Descripción",
            "es_admin": "Acceso total de administrador en este negocio",
        }

    def __init__(self, *args, empresa, **kwargs):
        sincronizar_catalogo_permisos()
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        self.fields["permisos"].queryset = Permiso.objects.all().order_by("codigo")

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if (
            Rol.objects.filter(empresa=self.empresa, nombre__iexact=nombre)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise ValidationError("Ya existe un rol con este nombre en tu empresa.")
        return nombre

    def clean(self):
        datos = super().clean()
        es_admin = datos.get("es_admin", False)
        if self.instance.pk and self.instance.es_admin and not es_admin:
            tiene_miembros_activos = self.instance.membresias.filter(activa=True).exists()
            otros_admins = (
                Membresia.objects.filter(empresa=self.empresa, activa=True, rol__es_admin=True)
                .exclude(rol=self.instance)
                .exists()
            )
            if tiene_miembros_activos and not otros_admins:
                raise ValidationError(
                    "No puedes quitar el acceso de administrador al único rol con administradores activos."
                )
        return datos

    def grupos_permisos(self):
        """Agrupa los permisos por módulo indicando cuáles están marcados actualmente."""
        por_codigo = {p.codigo: p for p in self.fields["permisos"].queryset}
        if self.is_bound:
            seleccionados = {str(v) for v in self["permisos"].value() or []}
        elif self.instance.pk:
            seleccionados = {str(pk) for pk in self.instance.permisos.values_list("pk", flat=True)}
        else:
            seleccionados = set()

        grupos = []
        for titulo, items in GRUPOS_PERMISOS:
            filas = []
            for codigo, _ in items:
                perm = por_codigo.get(codigo)
                if perm is not None:
                    filas.append({
                        "pk": str(perm.pk),
                        "codigo": perm.codigo,
                        "descripcion": perm.descripcion,
                        "marcado": str(perm.pk) in seleccionados,
                    })
            if filas:
                grupos.append({"titulo": titulo, "permisos": filas})
        return grupos


class MiembroCrearForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico")
    first_name = forms.CharField(max_length=150, required=False, label="Nombres")
    last_name = forms.CharField(max_length=150, required=False, label="Apellidos")
    rol = forms.ModelChoiceField(
        queryset=Rol.objects.none(),
        label="Rol en el negocio",
        empty_label="Selecciona un rol",
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="Contraseña inicial (solo si la cuenta es nueva)",
        help_text="Si el correo ya tiene cuenta en Intersoft, se vinculará sin cambiar su contraseña.",
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.usuario_existente = None
        self.fields["rol"].queryset = Rol.objects.de_empresa(empresa).order_by("-es_admin", "nombre")

    def clean_email(self):
        correo = self.cleaned_data["email"].strip().lower()
        if Membresia.objects.filter(empresa=self.empresa, usuario__email__iexact=correo).exists():
            raise ValidationError("Esta persona ya hace parte del equipo de tu negocio.")
        return correo

    def clean(self):
        datos = super().clean()
        correo = datos.get("email")
        rol = datos.get("rol")
        password = datos.get("password") or ""

        if rol and rol.empresa_id != self.empresa.pk:
            self.add_error("rol", "El rol seleccionado no pertenece a esta empresa.")

        if correo:
            self.usuario_existente = Usuario.objects.filter(email__iexact=correo).first()
            if self.usuario_existente is None:
                if not password:
                    self.add_error(
                        "password",
                        "Ingresa una contraseña inicial porque este correo aún no tiene cuenta.",
                    )
                else:
                    try:
                        validate_password(password)
                    except ValidationError as error:
                        self.add_error("password", error)
        return datos

    @transaction.atomic
    def guardar(self):
        correo = self.cleaned_data["email"]
        rol = self.cleaned_data["rol"]
        usuario = self.usuario_existente
        if usuario is None:
            usuario = Usuario.objects.create_user(
                username=correo,
                email=correo,
                password=self.cleaned_data["password"],
                first_name=self.cleaned_data.get("first_name", "").strip(),
                last_name=self.cleaned_data.get("last_name", "").strip(),
            )
        return Membresia.objects.create(
            usuario=usuario,
            empresa=self.empresa,
            rol=rol,
            activa=True,
        )


class MiembroEditarForm(forms.ModelForm):
    class Meta:
        model = Membresia
        fields = ["rol", "activa"]
        labels = {
            "rol": "Rol asignado",
            "activa": "Membresía activa (puede entrar al panel del negocio)",
        }

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields["rol"].queryset = Rol.objects.de_empresa(empresa).order_by("-es_admin", "nombre")

    def clean(self):
        datos = super().clean()
        rol = datos.get("rol")
        activa = datos.get("activa", False)

        if rol and rol.empresa_id != self.empresa.pk:
            self.add_error("rol", "El rol seleccionado no pertenece a esta empresa.")
            return datos

        era_admin_activo = bool(
            self.instance.pk and self.instance.activa and self.instance.rol.es_admin
        )
        seguira_siendo_admin_activo = bool(activa and rol and rol.es_admin)
        if era_admin_activo and not seguira_siendo_admin_activo:
            otros_admins = (
                Membresia.objects.filter(empresa=self.empresa, activa=True, rol__es_admin=True)
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if not otros_admins:
                raise ValidationError("El negocio debe conservar al menos un administrador activo.")
        return datos
