"""Formularios para la consola interna de plataforma."""
from django.utils.translation import gettext, gettext_lazy
from decimal import Decimal

from django import forms
from django.views.decorators.debug import sensitive_variables

from core.models import Empresa
from core.pasarela_negocio import EJEMPLOS, modo_de_llave
from suscripciones.models import CuponPlan, Plan

from .models import AnuncioGlobal, ConfiguracionCobroPlataforma, FeatureFlag

FEATURES_DISPONIBLES = [
    ("marketplace", gettext_lazy("Marketplace")),
    ("marketplace_destacado", gettext_lazy("Marketplace destacado")),
    ("pos", gettext_lazy("POS (Punto de venta)")),
    ("inventario", gettext_lazy("Inventario")),
    ("alertas_inventario", gettext_lazy("Alertas de inventario")),
    ("roles", gettext_lazy("Roles de equipo")),
    ("reportes_basicos", gettext_lazy("Reportes básicos")),
    ("reportes_avanzados", gettext_lazy("Reportes avanzados")),
    ("multisede", gettext_lazy("Multisede")),
    ("exportacion", gettext_lazy("Exportación de datos")),
    ("prioridad_busqueda", gettext_lazy("Prioridad en búsqueda")),
    ("asistente_ia", gettext_lazy("Asistente IA")),
]


class ConfiguracionCobroPlataformaForm(forms.ModelForm):
    """Formulario seguro para las llaves de Wompi de Intersoft: nunca expone secretos existentes."""

    llave_privada = forms.CharField(
        label=gettext_lazy("Llave privada"),
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": gettext_lazy("Déjala vacía para conservar la actual"), "autocomplete": "new-password"},
        ),
    )
    secreto_integridad = forms.CharField(
        label=gettext_lazy("Secreto de integridad"),
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": gettext_lazy("Déjalo vacío para conservar el actual"), "autocomplete": "new-password"},
        ),
    )
    secreto_eventos = forms.CharField(
        label=gettext_lazy("Secreto de eventos (webhook)"),
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": gettext_lazy("Déjalo vacío para conservar el actual"), "autocomplete": "new-password"},
        ),
    )

    class Meta:
        model = ConfiguracionCobroPlataforma
        fields = ["modo", "llave_publica", "activa"]
        labels = {
            "modo": gettext_lazy("Entorno de Wompi"),
            "llave_publica": gettext_lazy("Llave pública"),
            "activa": gettext_lazy("Activar cobro de planes con estas llaves"),
        }
        widgets = {
            "llave_publica": forms.TextInput(attrs={"placeholder": gettext_lazy("pub_test_... o pub_prod_...")}),
        }

    def clean(self):
        datos = super().clean()
        modo = datos.get("modo")
        publica = (datos.get("llave_publica") or "").strip()
        datos["llave_publica"] = publica

        if publica:
            modo_pub = modo_de_llave("llave_publica", publica)
            if modo_pub is None:
                self.add_error("llave_publica", gettext("Formato inválido. Ejemplo: {llave_publica}").format(llave_publica=EJEMPLOS['llave_publica']))
            elif modo and modo_pub != modo:
                self.add_error("llave_publica", gettext("La llave pública no corresponde al modo {modo}.").format(modo=modo))

        for campo in ("llave_privada", "secreto_integridad", "secreto_eventos"):
            valor = (datos.get(campo) or "").strip()
            datos[campo] = valor
            if valor:
                modo_val = modo_de_llave(campo, valor)
                if modo_val is None:
                    self.add_error(campo, gettext("Formato inválido. Ejemplo: {campo}").format(campo=EJEMPLOS[campo]))
                elif modo and modo_val != modo:
                    self.add_error(campo, gettext("Este secreto no corresponde al modo {modo}.").format(modo=modo))

        if datos.get("activa"):
            if not publica:
                self.add_error("llave_publica", gettext("Ingresa la llave pública para activar los cobros."))
            tiene_integridad = bool(datos.get("secreto_integridad") or self.instance.secreto_integridad_cifrado)
            if not tiene_integridad:
                self.add_error("secreto_integridad", gettext("El secreto de integridad es obligatorio para activar cobros."))

        return datos

    @sensitive_variables()
    def guardar(self, usuario) -> tuple[ConfiguracionCobroPlataforma, list[str]]:
        config = super().save(commit=False)
        campos_cambiados = list(self.changed_data)
        secreto_cambiado = False

        for campo in ("llave_privada", "secreto_integridad", "secreto_eventos"):
            nuevo = self.cleaned_data.get(campo)
            if nuevo:
                config.poner_secreto(campo, nuevo)
                secreto_cambiado = True
                if campo not in campos_cambiados:
                    campos_cambiados.append(campo)

        if "llave_publica" in self.changed_data or "modo" in self.changed_data or secreto_cambiado:
            config.verificada_en = None
            config.comercio_verificado = ""

        config.actualizada_por = usuario
        config.save()
        return config, campos_cambiados


class PlanPlataformaForm(forms.ModelForm):
    """Editor de precios, límites, funcionalidades, comisión y estado de un plan."""

    limite_productos = forms.IntegerField(
        label=gettext_lazy("Límite de productos"),
        required=False,
        min_value=0,
        help_text=gettext_lazy("Déjalo vacío para ilimitado."),
    )
    limite_usuarios = forms.IntegerField(
        label=gettext_lazy("Límite de usuarios"),
        required=False,
        min_value=0,
        help_text=gettext_lazy("Déjalo vacío para ilimitado."),
    )
    features = forms.MultipleChoiceField(
        label=gettext_lazy("Funcionalidades (features)"),
        required=False,
        choices=FEATURES_DISPONIBLES,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Plan
        fields = ["nombre", "precio_mensual", "precio_anual", "comision_porcentaje", "activo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plan = self.instance
        if plan and plan.pk:
            limites = plan.limites or {}
            self.fields["limite_productos"].initial = limites.get("productos")
            self.fields["limite_usuarios"].initial = limites.get("usuarios")
            actuales = list(plan.features or [])
            conocidas = {codigo for codigo, _ in FEATURES_DISPONIBLES}
            extra = [(f, f) for f in actuales if f not in conocidas]
            if extra:
                self.fields["features"].choices = list(FEATURES_DISPONIBLES) + extra
            self.fields["features"].initial = actuales

    def clean(self):
        datos = super().clean()
        if self.instance and self.instance.codigo == "gratis":
            precio_m = datos.get("precio_mensual")
            precio_a = datos.get("precio_anual")
            if precio_m is not None and precio_m != Decimal("0.00"):
                self.add_error("precio_mensual", gettext("El plan gratis debe mantener precio mensual 0."))
            if precio_a is not None and precio_a != Decimal("0.00"):
                self.add_error("precio_anual", gettext("El plan gratis debe mantener precio anual 0."))
            if datos.get("activo") is False:
                self.add_error("activo", gettext("El plan gratis no se puede desactivar."))
        return datos

    def guardar(self) -> tuple[Plan, dict]:
        plan_antes = Plan.objects.get(pk=self.instance.pk)
        plan = super().save(commit=False)

        limites = dict(plan_antes.limites or {})
        limites["productos"] = self.cleaned_data.get("limite_productos")
        limites["usuarios"] = self.cleaned_data.get("limite_usuarios")
        plan.limites = limites
        plan.features = list(self.cleaned_data.get("features") or [])
        plan.save()

        cambios = {}
        if plan_antes.nombre != plan.nombre:
            cambios["nombre"] = {"antes": plan_antes.nombre, "despues": plan.nombre}
        if plan_antes.precio_mensual != plan.precio_mensual:
            cambios["precio_mensual"] = {
                "antes": str(plan_antes.precio_mensual),
                "despues": str(plan.precio_mensual),
            }
        if plan_antes.precio_anual != plan.precio_anual:
            cambios["precio_anual"] = {
                "antes": str(plan_antes.precio_anual),
                "despues": str(plan.precio_anual),
            }
        if plan_antes.comision_porcentaje != plan.comision_porcentaje:
            cambios["comision_porcentaje"] = {
                "antes": str(plan_antes.comision_porcentaje),
                "despues": str(plan.comision_porcentaje),
            }
        if plan_antes.activo != plan.activo:
            cambios["activo"] = {"antes": plan_antes.activo, "despues": plan.activo}
        if (plan_antes.limites or {}) != (plan.limites or {}):
            cambios["limites"] = {"antes": plan_antes.limites, "despues": plan.limites}
        if (plan_antes.features or []) != (plan.features or []):
            cambios["features"] = {"antes": plan_antes.features, "despues": plan.features}

        return plan, cambios


class CortesiaPlataformaForm(forms.Form):
    """Formulario para otorgar días gratis o un plan de cortesía a un negocio."""

    empresa = forms.ModelChoiceField(
        label=gettext_lazy("Negocio"),
        queryset=Empresa.objects.filter(activa=True).order_by("nombre"),
    )
    plan = forms.ModelChoiceField(
        label=gettext_lazy("Plan de cortesía (opcional)"),
        queryset=Plan.objects.filter(activo=True).order_by("orden", "precio_mensual"),
        required=False,
        empty_label=gettext_lazy("Conservar plan actual"),
    )
    dias = forms.IntegerField(
        label=gettext_lazy("Días gratis (opcional)"),
        required=False,
        min_value=1,
        help_text=gettext_lazy("Si se omite al asignar un plan pago, se otorgan 30 días."),
    )
    motivo = forms.CharField(
        label=gettext_lazy("Motivo"),
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Ej. Compensación de soporte o alianza")}),
    )

    def clean(self):
        datos = super().clean()
        motivo = (datos.get("motivo") or "").strip()
        datos["motivo"] = motivo
        if not motivo:
            self.add_error("motivo", gettext("El motivo es obligatorio."))
        if not datos.get("dias") and not datos.get("plan"):
            raise forms.ValidationError(gettext("Debes indicar días gratis o seleccionar un plan de cortesía."))
        return datos


class CuposFundadorForm(forms.Form):
    """Formulario para ajustar el máximo de cupos de fundador en la base de datos."""

    cupos_fundador = forms.IntegerField(
        label=gettext_lazy("Cupos totales de fundador"),
        min_value=0,
    )


class AnuncioGlobalForm(forms.ModelForm):
    """Formulario para publicar anuncios globales visibles en /panel/."""

    class Meta:
        model = AnuncioGlobal
        fields = ["titulo", "mensaje", "tipo", "inicia_en", "vence_en", "activo"]
        widgets = {
            "mensaje": forms.Textarea(attrs={"rows": 3}),
            "inicia_en": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "vence_en": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicia_en"].required = False
        self.fields["vence_en"].required = False

    def clean_inicia_en(self):
        from django.utils import timezone

        return self.cleaned_data.get("inicia_en") or timezone.now()


class CuponPlanForm(forms.ModelForm):
    """Formulario para crear cupones de descuento de planes desde /plataforma/planes-cobros/."""

    class Meta:
        model = CuponPlan
        fields = ["codigo", "tipo", "valor", "inicia_en", "vence_en", "usos_maximos", "activo"]
        widgets = {
            "inicia_en": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "vence_en": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inicia_en"].required = False
        self.fields["vence_en"].required = False

    def clean_inicia_en(self):
        from django.utils import timezone

        return self.cleaned_data.get("inicia_en") or timezone.now()


class FeatureFlagForm(forms.ModelForm):
    """Formulario para activar/desactivar una función específica por negocio."""

    codigo = forms.ChoiceField(label=gettext_lazy("Funcionalidad"), choices=FEATURES_DISPONIBLES)

    class Meta:
        model = FeatureFlag
        fields = ["empresa", "codigo", "habilitado"]



