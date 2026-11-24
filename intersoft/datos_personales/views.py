"""Vistas de protección de datos: política, autorización, «Mis datos» y bandeja de la consola."""
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import FormView, TemplateView

from core.redirecciones import destino_seguro
from plataforma import auditoria
from plataforma.mixins import PlataformaMixin

from . import politica, services
from .forms import AutorizacionForm, RespuestaSolicitudForm, SolicitudDatosForm
from .models import SolicitudDatos


def contexto_politica() -> dict:
    """Datos que la política y el aviso de privacidad muestran (Decreto 1377 art. 13)."""
    return {
        "responsable": politica.responsable(),
        "finalidades": politica.FINALIDADES,
        "encargados": politica.ENCARGADOS,
        "version_politica": politica.VERSION_POLITICA,
        "plazo_consulta": politica.PLAZO_CONSULTA_DIAS,
        "plazo_reclamo": politica.PLAZO_RECLAMO_DIAS,
    }


class PoliticaPrivacidadView(TemplateView):
    """Política de tratamiento de datos personales, pública. Ruta: `/privacidad/` («legal_privacidad»)."""

    template_name = "core/tienda/legal/privacidad.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **contexto_politica()}


class AutorizarDatosView(LoginRequiredMixin, FormView):
    """Pide la autorización de la política vigente. Ruta: `/privacidad/autorizar/` («datos_autorizar»)."""

    template_name = "datos_personales/autorizar.html"
    form_class = AutorizacionForm

    def get(self, request, *args, **kwargs):
        if services.autorizacion_vigente(request.user):
            return HttpResponseRedirect(destino_seguro(request) or reverse("marketplace"))
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        services.registrar_autorizacion(self.request.user, medio="aceptacion_en_linea", request=self.request,
                                        mayor_de_edad=form.cleaned_data["mayor_edad"])
        messages.success(self.request, "Gracias. Guardamos tu autorización.")
        return HttpResponseRedirect(destino_seguro(self.request) or reverse("marketplace"))

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **contexto_politica(), "next": destino_seguro(self.request)}


class MisDatosView(LoginRequiredMixin, View):
    """Derechos del titular en un solo lugar. Ruta: `/mis-datos/` («mis_datos»).

    Muestra las autorizaciones dadas y las solicitudes, permite descargar los datos y radicar una solicitud."""

    template_name = "datos_personales/mis_datos.html"

    def _contexto(self, request, form=None):
        """Contexto común de la página; `form` trae los errores cuando la solicitud no es válida."""
        usuario = request.user
        return {
            **contexto_politica(),
            "form": form or SolicitudDatosForm(),
            "autorizaciones": usuario.autorizaciones_datos.all(),
            "solicitudes": usuario.solicitudes_datos.all(),
            "autorizacion_vigente": services.autorizacion_vigente(usuario),
        }

    def get(self, request):
        return render(request, self.template_name, self._contexto(request))

    def post(self, request):
        form = SolicitudDatosForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._contexto(request, form))
        solicitud = services.radicar_solicitud(titular=request.user, tipo=form.cleaned_data["tipo"],
                                               detalle=form.cleaned_data["detalle"])
        plazo = timezone.localtime(solicitud.fecha_limite).strftime("%d/%m/%Y")
        messages.success(request, f"Radicamos tu solicitud {solicitud.radicado}. Te responderemos por correo "
                                  f"a más tardar el {plazo}.")
        return redirect("mis_datos")


class DescargarMisDatosView(LoginRequiredMixin, View):
    """Descarga en JSON de todos los datos del titular. Ruta: `/mis-datos/descargar/` («mis_datos_descargar»)."""

    def get(self, request):
        contenido = json.dumps(services.exportar_datos(request.user), ensure_ascii=False, indent=2)
        respuesta = HttpResponse(contenido, content_type="application/json; charset=utf-8")
        respuesta["Content-Disposition"] = 'attachment; filename="mis-datos-intersoft.json"'
        respuesta["Cache-Control"] = "no-store"
        return respuesta


class PlataformaSolicitudesDatosView(PlataformaMixin, View):
    """Bandeja de solicitudes de datos personales. Ruta: `/plataforma/datos-personales/`. Permiso: «pqrs»."""

    permiso = "pqrs"

    def get(self, request):
        estado = (request.GET.get("estado") or "").strip()
        solicitudes = SolicitudDatos.objects.select_related("titular").order_by("fecha_limite")
        if estado:
            solicitudes = solicitudes.filter(estado=estado)
        pendientes = SolicitudDatos.objects.filter(
            estado__in=(SolicitudDatos.Estado.RADICADA, SolicitudDatos.Estado.EN_TRAMITE))
        return render(request, "datos_personales/plataforma_lista.html", {
            "solicitudes": solicitudes, "estado": estado, "estados": SolicitudDatos.Estado.choices,
            "pendientes": pendientes.count(),
            "vencidas": pendientes.filter(fecha_limite__lt=timezone.now()).count(),
            "responsable": politica.responsable(),
        })


class PlataformaSolicitudDatosDetalleView(PlataformaMixin, View):
    """Atiende una solicitud: tomarla, responder, rechazar o ejecutar la supresión. Permiso: «pqrs»."""

    permiso = "pqrs"
    template_name = "datos_personales/plataforma_detalle.html"

    def _render(self, request, solicitud, form=None):
        """Pinta el detalle con el formulario de respuesta (con errores si los hay)."""
        return render(request, self.template_name, {
            "solicitud": solicitud, "form": form or RespuestaSolicitudForm(),
            "permite_supresion": solicitud.tipo in (SolicitudDatos.Tipo.SUPRIMIR, SolicitudDatos.Tipo.REVOCAR),
            "abierta": solicitud.estado in (SolicitudDatos.Estado.RADICADA, SolicitudDatos.Estado.EN_TRAMITE),
        })

    def get(self, request, pk):
        return self._render(request, get_object_or_404(SolicitudDatos.objects.select_related("titular"), pk=pk))

    def post(self, request, pk):
        solicitud = get_object_or_404(SolicitudDatos.objects.select_related("titular"), pk=pk)
        accion = request.POST.get("accion", "")
        if solicitud.estado in (SolicitudDatos.Estado.RESPONDIDA, SolicitudDatos.Estado.RECHAZADA):
            messages.error(request, "Esta solicitud ya fue cerrada.")
            return redirect("plataforma_datos_detalle", pk=solicitud.pk)
        if accion == "tomar":
            solicitud.estado = SolicitudDatos.Estado.EN_TRAMITE
            solicitud.atendida_por = request.user
            solicitud.save(update_fields=["estado", "atendida_por", "actualizado_en"])
            return self._auditar_y_volver(request, solicitud, accion, "La solicitud quedó en trámite.")
        form = RespuestaSolicitudForm(request.POST)
        if not form.is_valid():
            return self._render(request, solicitud, form)
        texto = form.cleaned_data["respuesta"]
        try:
            if accion == "suprimir":
                services.atender_supresion(solicitud, respuesta=texto, actor=request.user)
                aviso = "Datos suprimidos y respuesta enviada al titular."
            else:
                services.responder_solicitud(solicitud, respuesta=texto, actor=request.user,
                                             rechazar=accion == "rechazar")
                aviso = "Respuesta enviada al titular."
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return self._render(request, solicitud, form)
        return self._auditar_y_volver(request, solicitud, accion or "responder", aviso)

    @staticmethod
    def _auditar_y_volver(request, solicitud, accion, aviso):
        """Deja la acción en la bitácora de la consola y vuelve al detalle."""
        auditoria.registrar(actor=request.user, accion=f"datos_personales_{accion}", objeto_tipo="SolicitudDatos",
                            objeto_id=str(solicitud.pk), detalle={"radicado": solicitud.radicado}, request=request)
        messages.success(request, aviso)
        return redirect("plataforma_datos_detalle", pk=solicitud.pk)
