"""Formularios para la consola interna de plataforma."""
from decimal import Decimal

from django import forms
from django.views.decorators.debug import sensitive_variables

from core.models import Empresa
from core.pasarela_negocio import EJEMPLOS, modo_de_llave
from suscripciones.models import CuponPlan, Plan

from .models import AnuncioGlobal, ConfiguracionCobroPlataforma, FeatureFlag


class IdsPropiosMixin:
    """Varios formularios comparten la página de Planes y cobros (y la de Negocios) y algunos campos se
    llaman igual (empresa, codigo, activo…). Cada formulario usa su propio prefijo en los id del HTML para
    que no se repitan ni una etiqueta active el campo de otro formulario. Los nombres enviados no cambian."""

    prefijo_ids = ""

    def __init__(self, *args, **kwargs):
        if self.prefijo_ids:
            kwargs.setdefault("auto_id", f"{self.prefijo_ids}_%s")
        super().__init__(*args, **kwargs)

FEATURES_DISPONIBLES = [
    ("marketplace", "Marketplace"),
    ("marketplace_destacado", "Marketplace destacado"),
    ("pos", "POS (Punto de venta)"),
    ("inventario", "Inventario"),
    ("alertas_inventario", "Alertas de inventario"),
    ("roles", "Roles de equipo"),
    ("reportes_basicos", "Reportes básicos"),
    ("reportes_avanzados", "Reportes avanzados"),
    ("multisede", "Multisede"),
    ("exportacion", "Exportación de datos"),
    ("prioridad_busqueda", "Prioridad en búsqueda"),
    ("asistente_ia", "Asistente IA"),
]


class ConfiguracionCobroPlataformaForm(IdsPropiosMixin, forms.ModelForm):
    """Formulario de configuración de cobro de plataforma. Campos: modo, llave_publica, activa, llave_privada,
    secreto_integridad, secreto_eventos.
    """
    prefijo_ids = "llaves"
    """Formulario seguro para las llaves de Wompi de Intersoft: nunca expone secretos existentes."""

    llave_privada = forms.CharField(
        label="Llave privada",
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Déjala vacía para conservar la actual", "autocomplete": "new-password"},
        ),
    )
    secreto_integridad = forms.CharField(
        label="Secreto de integridad",
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Déjalo vacío para conservar el actual", "autocomplete": "new-password"},
        ),
    )
    secreto_eventos = forms.CharField(
        label="Secreto de eventos (webhook)",
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Déjalo vacío para conservar el actual", "autocomplete": "new-password"},
        ),
    )

    class Meta:
        model = ConfiguracionCobroPlataforma
        fields = ["modo", "llave_publica", "activa"]
        labels = {
            "modo": "Entorno de Wompi",
            "llave_publica": "Llave pública",
            "activa": "Activar cobro de planes con estas llaves",
        }
        widgets = {
            "llave_publica": forms.TextInput(attrs={"placeholder": "pub_test_... o pub_prod_..."}),
        }

    def clean(self):
        datos = super().clean()
        modo = datos.get("modo")
        publica = (datos.get("llave_publica") or "").strip()
        datos["llave_publica"] = publica

        if publica:
            modo_pub = modo_de_llave("llave_publica", publica)
            if modo_pub is None:
                self.add_error("llave_publica", f"Formato inválido. Ejemplo: {EJEMPLOS['llave_publica']}")
            elif modo and modo_pub != modo:
                self.add_error("llave_publica", f"La llave pública no corresponde al modo {modo}.")

        for campo in ("llave_privada", "secreto_integridad", "secreto_eventos"):
            valor = (datos.get(campo) or "").strip()
            datos[campo] = valor
            if valor:
                modo_val = modo_de_llave(campo, valor)
                if modo_val is None:
                    self.add_error(campo, f"Formato inválido. Ejemplo: {EJEMPLOS[campo]}")
                elif modo and modo_val != modo:
                    self.add_error(campo, f"Este secreto no corresponde al modo {modo}.")

        if datos.get("activa"):
            if not publica:
                self.add_error("llave_publica", "Ingresa la llave pública para activar los cobros.")
            tiene_integridad = bool(datos.get("secreto_integridad") or self.instance.secreto_integridad_cifrado)
            if not tiene_integridad:
                self.add_error("secreto_integridad", "El secreto de integridad es obligatorio para activar cobros.")

        return datos

    @sensitive_variables()
    def guardar(self, usuario) -> tuple[ConfiguracionCobroPlataforma, list[str]]:
        """Guarda la configuración, cifra los secretos nuevos e invalida la verificación si cambiaron las llaves.
        Devuelve (configuración, campos cambiados sin valores).
        """
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


class PlanPlataformaForm(IdsPropiosMixin, forms.ModelForm):
    """Formulario de plan. Campos: nombre, precio_mensual, precio_anual, comision_porcentaje, activo,
    limite_productos, limite_usuarios, features.
    """
    prefijo_ids = "plan"
    """Editor de precios, límites, funcionalidades, comisión y estado de un plan."""

    limite_productos = forms.IntegerField(
        label="Límite de productos",
        required=False,
        min_value=0,
        help_text="Déjalo vacío para ilimitado.",
    )
    limite_usuarios = forms.IntegerField(
        label="Límite de usuarios",
        required=False,
        min_value=0,
        help_text="Déjalo vacío para ilimitado.",
    )
    features = forms.MultipleChoiceField(
        label="Funcionalidades (features)",
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
                self.add_error("precio_mensual", "El plan gratis debe mantener precio mensual 0.")
            if precio_a is not None and precio_a != Decimal("0.00"):
                self.add_error("precio_anual", "El plan gratis debe mantener precio anual 0.")
            if datos.get("activo") is False:
                self.add_error("activo", "El plan gratis no se puede desactivar.")
        return datos

    def guardar(self) -> tuple[Plan, dict]:
        """Guarda precios, límites y funciones del plan. Devuelve (plan, cambios antes/después para la auditoría)."""
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


class CortesiaPlataformaForm(IdsPropiosMixin, forms.Form):
    """Formulario. Campos: empresa, plan, dias, motivo."""
    prefijo_ids = "cortesia"
    """Formulario para otorgar días gratis o un plan de cortesía a un negocio."""

    empresa = forms.ModelChoiceField(
        label="Negocio",
        queryset=Empresa.objects.filter(activa=True).order_by("nombre"),
        empty_label="Selecciona un negocio",
    )
    plan = forms.ModelChoiceField(
        label="Plan de cortesía (opcional)",
        queryset=Plan.objects.filter(activo=True).order_by("orden", "precio_mensual"),
        required=False,
        empty_label="Conservar plan actual",
    )
    dias = forms.IntegerField(
        label="Días gratis (opcional)",
        required=False,
        min_value=1,
        help_text="Si se omite al asignar un plan pago, se otorgan 30 días.",
    )
    motivo = forms.CharField(
        label="Motivo",
        max_length=255,
        widget=forms.TextInput(attrs={"placeholder": "Ej. Compensación o alianza"}),
    )

    def clean(self):
        datos = super().clean()
        motivo = (datos.get("motivo") or "").strip()
        datos["motivo"] = motivo
        if not motivo:
            self.add_error("motivo", "El motivo es obligatorio.")
        if not datos.get("dias") and not datos.get("plan"):
            raise forms.ValidationError("Debes indicar días gratis o seleccionar un plan de cortesía.")
        return datos


class CuposFundadorForm(IdsPropiosMixin, forms.Form):
    """Formulario. Campos: cupos_fundador."""
    prefijo_ids = "cupos"
    """Formulario para ajustar el máximo de cupos de fundador en la base de datos."""

    cupos_fundador = forms.IntegerField(
        label="Cupos totales de fundador",
        min_value=0,
    )


class AnuncioGlobalForm(IdsPropiosMixin, forms.ModelForm):
    """Formulario de anuncio global. Campos: titulo, mensaje, tipo, inicia_en, vence_en, activo."""
    prefijo_ids = "anuncio"
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


class CuponPlanForm(IdsPropiosMixin, forms.ModelForm):
    """Formulario de cupón de plan. Campos: codigo, tipo, valor, inicia_en, vence_en, usos_maximos, activo."""
    prefijo_ids = "cupon"
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


class FeatureFlagForm(IdsPropiosMixin, forms.ModelForm):
    """Formulario de interruptor de función. Campos: empresa, codigo, habilitado."""
    prefijo_ids = "flag"
    """Formulario para activar/desactivar una función específica por negocio."""

    codigo = forms.ChoiceField(label="Funcionalidad", choices=FEATURES_DISPONIBLES)

    class Meta:
        model = FeatureFlag
        fields = ["empresa", "codigo", "habilitado"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["empresa"].empty_label = "Selecciona un negocio"



