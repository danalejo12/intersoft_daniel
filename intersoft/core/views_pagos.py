"""Panel › Pagos: cada negocio conecta su propia cuenta de Wompi."""
from django.utils.translation import gettext
import uuid
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.debug import sensitive_post_parameters

from .cifrado import SecretoIlegible
from .forms_pagos import ConfiguracionPagosForm
from .mixins import PermisoRequeridoMixin
from .models import AuditoriaPagos, ConfiguracionPagos, Empresa
from .pasarela_negocio import SEGUNDOS_ENTRE_VERIFICACIONES, verificar_llaves

PERMISO = "pagos.configurar"


def configuracion_de(empresa) -> ConfiguracionPagos | None:
    return ConfiguracionPagos.objects.de_empresa(empresa).first()


def auditar(request, accion, campos=()):
    AuditoriaPagos.objects.create(empresa=request.empresa, usuario=request.user,
                                  accion=accion, campos=list(campos))


def bloquear_negocio(request):
    Empresa.objects.select_for_update().get(pk=request.empresa.pk)


class PagosBaseView(PermisoRequeridoMixin, View):
    permiso_requerido = PERMISO

    def config_o_aviso(self) -> ConfiguracionPagos | None:
        config = configuracion_de(self.request.empresa)
        if config is None:
            messages.error(self.request, gettext("Primero guarda las llaves de Wompi."))
        return config


@method_decorator(  # los reportes de error nunca incluyen las llaves
    sensitive_post_parameters("llave_privada", "secreto_integridad", "secreto_eventos"), name="dispatch",
)
class PagosNegocioView(PagosBaseView):
    template_name = "core/negocio/pagos.html"

    def get(self, request, *args, **kwargs):
        config = configuracion_de(request.empresa)
        return self.mostrar(config, ConfiguracionPagosForm(instance=config))

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        bloquear_negocio(request)
        config = configuracion_de(request.empresa) or ConfiguracionPagos(empresa=request.empresa)
        form = ConfiguracionPagosForm(request.POST, instance=config)
        if not form.is_valid():
            return self.mostrar(config if config.pk else None, form, status=400)
        cambio_llaves = form.cambio_llaves
        config = form.save(commit=False)
        if cambio_llaves:
            config.revision = uuid.uuid4()
        config.actualizada_por = request.user
        config.save()
        auditar(request, "guardar", form.changed_data)
        if cambio_llaves:
            messages.success(request, gettext("Guardamos tus llaves cifradas. Ahora verifícalas con Wompi para empezar a cobrar."))
        else:
            messages.success(request, gettext("Guardamos la configuración de tarifas."))
        return redirect("negocio_pagos")

    def mostrar(self, config, form, status=200):
        from django.urls import reverse
        contexto = {"config": config, "form": form, "webhook_url": self.request.build_absolute_uri(
            reverse("wompi_webhook_negocio", args=[self.request.empresa.pk]))}
        return render(self.request, self.template_name, contexto, status=status)


class VerificarPagosView(PagosBaseView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        config = self.config_o_aviso()
        if config is None:
            return redirect("negocio_pagos")
        ahora = timezone.now()
        limite = ahora - timedelta(seconds=SEGUNDOS_ENTRE_VERIFICACIONES)
        # UPDATE condicional: dos clics seguidos no disparan dos consultas a Wompi
        turno = ConfiguracionPagos.objects.filter(pk=config.pk).exclude(
            ultimo_intento_verificacion__gt=limite
        ).update(ultimo_intento_verificacion=ahora)
        if not turno:
            messages.warning(request, gettext("Espera {segundos_entre_verificaciones} segundos antes de verificar otra vez.").format(segundos_entre_verificaciones=SEGUNDOS_ENTRE_VERIFICACIONES))
            return redirect("negocio_pagos")
        try:
            resultado = verificar_llaves(config)
        except SecretoIlegible:
            messages.error(request, gettext("No pudimos leer tus llaves. Revisa la clave de cifrado o vuelve a guardarlas."))
            return redirect("negocio_pagos")
        with transaction.atomic():
            bloquear_negocio(request)
            actual = ConfiguracionPagos.objects.filter(pk=config.pk, revision=config.revision,
                                                       ultimo_intento_verificacion=ahora)
            if not actual.exists():
                messages.warning(request, gettext("La configuración cambió o hay una verificación más reciente. Verifica el estado actual."))
                return redirect("negocio_pagos")
            if resultado.ok:
                actual.update(verificada_en=ahora, comercio_verificado=resultado.comercio)
            else:
                actual.update(verificada_en=None, activa=False)
            auditar(request, "verificar_ok" if resultado.ok else "verificar_error")
        if resultado.ok:
            nombre = f" «{resultado.comercio}»" if resultado.comercio else ""
            messages.success(request, gettext("¡Conectado! Wompi reconoce tus llaves del comercio{nombre}.").format(nombre=nombre))
        else:
            for error in resultado.errores:
                messages.error(request, error)
        return redirect("negocio_pagos")


class ActivarPagosView(PagosBaseView):
    http_method_names = ["post"]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        bloquear_negocio(request)
        config = self.config_o_aviso()
        if config is None:
            return redirect("negocio_pagos")
        activar = request.POST.get("activa") == "1"
        if activar and config.verificada_en is None:
            messages.error(request, gettext("Verifica tus llaves con Wompi antes de activar los cobros."))
            return redirect("negocio_pagos")
        ConfiguracionPagos.objects.filter(pk=config.pk).update(activa=activar, actualizada_por=request.user)
        auditar(request, "activar" if activar else "pausar")
        if activar:
            messages.success(request, gettext("Cobros en línea activados con tu cuenta de Wompi."))
        else:
            messages.info(request, gettext("Pausaste los cobros en línea de tu cuenta de Wompi."))
        return redirect("negocio_pagos")


class EliminarPagosView(PagosBaseView):
    http_method_names = ["post"]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        bloquear_negocio(request)
        borrados, _ = ConfiguracionPagos.objects.de_empresa(request.empresa).delete()
        if borrados:
            auditar(request, "eliminar")
            messages.info(request, gettext("Borramos tus llaves de Wompi de Intersoft."))
        return redirect("negocio_pagos")
