"""Vistas de PQRS para compradores (/pqrs/), negocios (/panel/pqrs/) e Intersoft (/plataforma/pqrs/)."""
from django.utils.translation import gettext
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from core.mixins import PermisoRequeridoMixin
from core.models import Pedido
from plataforma import auditoria
from plataforma.mixins import PlataformaMixin

from .forms import (
    EncuestaSatisfaccionForm,
    GestionPQRSPlataformaForm,
    MensajePQRSForm,
    RadicarPQRSCompradorForm,
    RadicarPQRSNegocioForm,
)
from .models import PQRS
from .services import (
    agregar_mensaje_pqrs,
    cambiar_estado_pqrs,
    radicar_pqrs,
    registrar_encuesta_satisfaccion,
)


class MisPQRSListView(LoginRequiredMixin, View):
    """Lista las PQRS radicadas por el comprador autenticado."""

    template_name = "pqrs/comprador_lista.html"

    def get(self, request):
        pqrs_lista = (
            PQRS.objects.filter(autor=request.user)
            .select_related("empresa", "pedido")
            .order_by("-creado_en")
        )
        return render(request, self.template_name, {"pqrs_lista": pqrs_lista})


class RadicarPQRSCompradorView(LoginRequiredMixin, View):
    """Permite a un comprador radicar una PQRS (flujo B) desde /pqrs/ o desde su pedido."""

    template_name = "pqrs/comprador_nueva.html"

    def _initial(self, request):
        initial = {}
        pedido_id = (request.GET.get("pedido") or "").strip()
        if pedido_id:
            pedido = Pedido.objects.filter(pk=pedido_id, comprador=request.user).select_related("empresa").first()
            if pedido is not None:
                initial["pedido"] = pedido
                initial["empresa"] = pedido.empresa
        return initial

    def get(self, request):
        form = RadicarPQRSCompradorForm(usuario=request.user, initial=self._initial(request))
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = RadicarPQRSCompradorForm(request.POST, request.FILES, usuario=request.user)
        if form.is_valid():
            try:
                pqrs = radicar_pqrs(
                    autor=request.user,
                    tipo=form.cleaned_data["tipo"],
                    flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
                    asunto=form.cleaned_data["asunto"],
                    descripcion=form.cleaned_data["descripcion"],
                    empresa=form.cleaned_data["empresa"],
                    pedido=form.cleaned_data["pedido"],
                    adjunto=form.cleaned_data.get("adjunto"),
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages[0] if exc.messages else str(exc))
            else:
                messages.success(request, gettext("PQRS radicada con éxito: {radicado}.").format(radicado=pqrs.radicado))
                return redirect("pqrs_detalle", pk=pqrs.pk)
        return render(request, self.template_name, {"form": form})


class DetallePQRSCompradorView(LoginRequiredMixin, View):
    """Detalle de una PQRS para su autor (sin notas internas) y encuesta de cierre."""

    template_name = "pqrs/comprador_detalle.html"

    def _contexto(self, pqrs, msg_form=None, encuesta_form=None):
        return {
            "pqrs": pqrs,
            "mensajes": pqrs.mensajes.filter(interno=False).select_related("autor"),
            "msg_form": msg_form or MensajePQRSForm(permitir_interno=False),
            "encuesta_form": encuesta_form or EncuestaSatisfaccionForm(),
        }

    def get(self, request, pk):
        pqrs = get_object_or_404(PQRS.objects.select_related("empresa", "pedido"), pk=pk, autor=request.user)
        return render(request, self.template_name, self._contexto(pqrs))

    def post(self, request, pk):
        pqrs = get_object_or_404(PQRS.objects.select_related("empresa", "pedido"), pk=pk, autor=request.user)
        accion = (request.POST.get("accion") or "mensaje").strip()

        if accion == "encuesta":
            encuesta_form = EncuestaSatisfaccionForm(request.POST)
            if encuesta_form.is_valid():
                registrar_encuesta_satisfaccion(
                    pqrs,
                    calificacion=encuesta_form.cleaned_data["calificacion"],
                    comentario=encuesta_form.cleaned_data.get("comentario_satisfaccion", ""),
                )
                messages.success(request, gettext("Gracias por calificar la atención. Tu PQRS quedó cerrada."))
                return redirect("pqrs_detalle", pk=pqrs.pk)
            return render(request, self.template_name, self._contexto(pqrs, encuesta_form=encuesta_form))

        if pqrs.estado == PQRS.Estado.CERRADA:
            messages.error(request, gettext("Esta PQRS ya está cerrada y no admite nuevos mensajes."))
            return redirect("pqrs_detalle", pk=pqrs.pk)

        msg_form = MensajePQRSForm(request.POST, request.FILES, permitir_interno=False)
        if msg_form.is_valid():
            agregar_mensaje_pqrs(
                pqrs,
                autor=request.user,
                texto=msg_form.cleaned_data["texto"],
                adjunto=msg_form.cleaned_data.get("adjunto"),
                interno=False,
            )
            messages.success(request, gettext("Mensaje enviado."))
            return redirect("pqrs_detalle", pk=pqrs.pk)
        return render(request, self.template_name, self._contexto(pqrs, msg_form=msg_form))


class PanelPQRSListView(PermisoRequeridoMixin, View):
    """Bandeja de PQRS de un negocio en /panel/pqrs/ (recibidas de compradores y enviadas a Intersoft)."""

    permiso_requerido = "pqrs.gestionar"
    template_name = "pqrs/panel_lista.html"

    def get(self, request):
        pqrs_lista = (
            PQRS.objects.filter(empresa=request.empresa)
            .select_related("autor", "pedido")
            .order_by("-creado_en")
        )
        return render(request, self.template_name, {"pqrs_lista": pqrs_lista})


class PanelPQRSNuevaView(PermisoRequeridoMixin, View):
    """Permite al negocio radicar una PQRS hacia Intersoft (flujo A) desde /panel/pqrs/."""

    permiso_requerido = "pqrs.gestionar"
    template_name = "pqrs/panel_nueva.html"

    def get(self, request):
        return render(request, self.template_name, {"form": RadicarPQRSNegocioForm()})

    def post(self, request):
        form = RadicarPQRSNegocioForm(request.POST, request.FILES)
        if form.is_valid():
            pqrs = radicar_pqrs(
                autor=request.user,
                tipo=form.cleaned_data["tipo"],
                flujo=PQRS.Flujo.NEGOCIO_INTERSOFT,
                asunto=form.cleaned_data["asunto"],
                descripcion=form.cleaned_data["descripcion"],
                empresa=request.empresa,
                adjunto=form.cleaned_data.get("adjunto"),
                prioridad=form.cleaned_data["prioridad"],
            )
            messages.success(request, gettext("PQRS enviada a Intersoft con radicado {radicado}.").format(radicado=pqrs.radicado))
            return redirect("panel_pqrs_detalle", pk=pqrs.pk)
        return render(request, self.template_name, {"form": form})


class PanelPQRSDetalleView(PermisoRequeridoMixin, View):
    """Gestión de una PQRS dentro del panel del negocio (aislamiento estricto por tenant)."""

    permiso_requerido = "pqrs.gestionar"
    template_name = "pqrs/panel_detalle.html"

    def _contexto(self, pqrs, msg_form=None, encuesta_form=None):
        es_flujo_b = pqrs.flujo == PQRS.Flujo.COMPRADOR_NEGOCIO
        mensajes_qs = pqrs.mensajes.select_related("autor")
        if not es_flujo_b:
            mensajes_qs = mensajes_qs.filter(interno=False)
        return {
            "pqrs": pqrs,
            "es_flujo_b": es_flujo_b,
            "mensajes": mensajes_qs,
            "msg_form": msg_form or MensajePQRSForm(permitir_interno=es_flujo_b),
            "encuesta_form": encuesta_form or EncuestaSatisfaccionForm(),
        }

    def get(self, request, pk):
        pqrs = get_object_or_404(
            PQRS.objects.select_related("autor", "pedido", "empresa"),
            pk=pk,
            empresa=request.empresa,
        )
        return render(request, self.template_name, self._contexto(pqrs))

    def post(self, request, pk):
        pqrs = get_object_or_404(
            PQRS.objects.select_related("autor", "pedido", "empresa"),
            pk=pk,
            empresa=request.empresa,
        )
        es_flujo_b = pqrs.flujo == PQRS.Flujo.COMPRADOR_NEGOCIO
        accion = (request.POST.get("accion") or "mensaje").strip()

        if accion == "encuesta" and not es_flujo_b:
            encuesta_form = EncuestaSatisfaccionForm(request.POST)
            if encuesta_form.is_valid():
                registrar_encuesta_satisfaccion(
                    pqrs,
                    calificacion=encuesta_form.cleaned_data["calificacion"],
                    comentario=encuesta_form.cleaned_data.get("comentario_satisfaccion", ""),
                )
                messages.success(request, gettext("Encuesta registrada y PQRS cerrada."))
                return redirect("panel_pqrs_detalle", pk=pqrs.pk)
            return render(request, self.template_name, self._contexto(pqrs, encuesta_form=encuesta_form))

        if accion == "cambiar_estado" and es_flujo_b:
            nuevo_estado = (request.POST.get("estado") or "").strip()
            if nuevo_estado in (PQRS.Estado.EN_TRAMITE, PQRS.Estado.RESPONDIDA, PQRS.Estado.CERRADA):
                cambiar_estado_pqrs(pqrs, nuevo_estado=nuevo_estado)
                messages.success(request, gettext("Estado actualizado a {get_estado_display}.").format(get_estado_display=pqrs.get_estado_display()))
            return redirect("panel_pqrs_detalle", pk=pqrs.pk)

        msg_form = MensajePQRSForm(request.POST, request.FILES, permitir_interno=es_flujo_b)
        if msg_form.is_valid():
            interno = bool(msg_form.cleaned_data.get("interno")) if es_flujo_b else False
            nuevo_estado = None
            if es_flujo_b and not interno and pqrs.estado in (PQRS.Estado.RADICADA, PQRS.Estado.EN_TRAMITE):
                nuevo_estado = PQRS.Estado.RESPONDIDA
            agregar_mensaje_pqrs(
                pqrs,
                autor=request.user,
                texto=msg_form.cleaned_data["texto"],
                adjunto=msg_form.cleaned_data.get("adjunto"),
                interno=interno,
                nuevo_estado=nuevo_estado,
            )
            messages.success(request, gettext("Mensaje registrado correctamente."))
            return redirect("panel_pqrs_detalle", pk=pqrs.pk)

        return render(request, self.template_name, self._contexto(pqrs, msg_form=msg_form))


class PlataformaPQRSListView(PlataformaMixin, View):
    """Bandeja global de Intersoft en /plataforma/pqrs/: muestra todas, escaladas primero."""

    permiso = "pqrs"
    template_name = "pqrs/plataforma_lista.html"

    def get(self, request):
        estado = (request.GET.get("estado") or "").strip()
        flujo = (request.GET.get("flujo") or "").strip()

        qs = (
            PQRS.objects.select_related("empresa", "autor", "asignado_a", "pedido")
            .annotate(
                prioridad_escalada=Case(
                    When(estado=PQRS.Estado.ESCALADA, then=0),
                    default=1,
                    output_field=IntegerField(),
                )
            )
            .order_by("prioridad_escalada", "fecha_limite", "-creado_en")
        )
        if estado:
            qs = qs.filter(estado=estado)
        if flujo:
            qs = qs.filter(flujo=flujo)

        return render(
            request,
            self.template_name,
            {
                "pqrs_lista": qs,
                "filtros": {"estado": estado, "flujo": flujo},
                "estados": PQRS.Estado.choices,
                "flujos": PQRS.Flujo.choices,
            },
        )


class PlataformaPQRSDetalleView(PlataformaMixin, View):
    """Detalle y gestión de cualquier PQRS desde la consola /plataforma/pqrs/."""

    permiso = "pqrs"
    template_name = "pqrs/plataforma_detalle.html"

    def _contexto(self, pqrs, msg_form=None, gestion_form=None):
        return {
            "pqrs": pqrs,
            "mensajes": pqrs.mensajes.select_related("autor"),
            "msg_form": msg_form or MensajePQRSForm(permitir_interno=True),
            "gestion_form": gestion_form
            or GestionPQRSPlataformaForm(
                initial={
                    "estado": pqrs.estado,
                    "prioridad": pqrs.prioridad,
                    "asignado_a": pqrs.asignado_a,
                }
            ),
        }

    def get(self, request, pk):
        pqrs = get_object_or_404(PQRS.objects.select_related("empresa", "autor", "asignado_a", "pedido"), pk=pk)
        return render(request, self.template_name, self._contexto(pqrs))

    def post(self, request, pk):
        pqrs = get_object_or_404(PQRS.objects.select_related("empresa", "autor", "asignado_a", "pedido"), pk=pk)
        accion = (request.POST.get("accion") or "mensaje").strip()

        if accion == "gestionar":
            gestion_form = GestionPQRSPlataformaForm(request.POST)
            if gestion_form.is_valid():
                estado_anterior = pqrs.estado
                cambiar_estado_pqrs(
                    pqrs,
                    nuevo_estado=gestion_form.cleaned_data["estado"],
                    prioridad=gestion_form.cleaned_data["prioridad"],
                    asignado_a=gestion_form.cleaned_data["asignado_a"],
                )
                auditoria.registrar(
                    actor=request.user,
                    accion="gestionar_pqrs_plataforma",
                    objeto_tipo="PQRS",
                    objeto_id=str(pqrs.pk),
                    detalle={
                        "radicado": pqrs.radicado,
                        "estado_anterior": estado_anterior,
                        "estado_nuevo": pqrs.estado,
                        "prioridad": pqrs.prioridad,
                    },
                    request=request,
                )
                messages.success(request, gettext("PQRS {radicado} actualizada.").format(radicado=pqrs.radicado))
                return redirect("plataforma_pqrs_detalle", pk=pqrs.pk)
            return render(request, self.template_name, self._contexto(pqrs, gestion_form=gestion_form))

        msg_form = MensajePQRSForm(request.POST, request.FILES, permitir_interno=True)
        if msg_form.is_valid():
            interno = bool(msg_form.cleaned_data.get("interno"))
            nuevo_estado = None
            if not interno and pqrs.estado in (PQRS.Estado.RADICADA, PQRS.Estado.EN_TRAMITE, PQRS.Estado.ESCALADA):
                nuevo_estado = PQRS.Estado.RESPONDIDA
            agregar_mensaje_pqrs(
                pqrs,
                autor=request.user,
                texto=msg_form.cleaned_data["texto"],
                adjunto=msg_form.cleaned_data.get("adjunto"),
                interno=interno,
                nuevo_estado=nuevo_estado,
            )
            auditoria.registrar(
                actor=request.user,
                accion="responder_pqrs_plataforma",
                objeto_tipo="PQRS",
                objeto_id=str(pqrs.pk),
                detalle={"radicado": pqrs.radicado, "interno": interno},
                request=request,
            )
            messages.success(request, gettext("Mensaje registrado en la PQRS."))
            return redirect("plataforma_pqrs_detalle", pk=pqrs.pk)
        return render(request, self.template_name, self._contexto(pqrs, msg_form=msg_form))
