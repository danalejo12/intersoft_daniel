"""Vista web del panel para consultar y cambiar la suscripción SaaS de la empresa activa."""
import math

import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.mixins import TenantMixin
from core.pagos import consultar_transaccion, evento_es_valido

from . import cobros
from .models import CobroSuscripcion, Plan, Suscripcion
from .services import (
    DowngradeNoPermitido,
    cambiar_plan,
    crear_suscripcion_inicial,
    uso_actual,
)

ETIQUETAS_FEATURES = {
    "marketplace": "Publicación en Marketplace",
    "marketplace_destacado": "Productos destacados en Marketplace",
    "pos": "Punto de venta (POS) sin comisión",
    "inventario": "Control de inventario y kardex",
    "alertas_inventario": "Alertas automáticas de stock mínimo",
    "roles": "Roles y permisos personalizados",
    "reportes_basicos": "Reportes básicos de ventas",
    "reportes_avanzados": "Reportes financieros y ERP avanzados",
    "multisede": "Gestión multisede",
    "exportacion": "Exportación contable y de datos",
    "prioridad_busqueda": "Prioridad en resultados de búsqueda",
    "asistente_ia": "Asistente inteligente con IA",
}


class SuscripcionPanelView(TenantMixin, View):
    """Muestra en `/panel/suscripcion/` el plan actual, consumo frente a límites, catálogo de planes e historial."""

    template_name = "core/negocio/suscripcion.html"

    def _puede_cambiar(self, request) -> bool:
        membresia = getattr(request, "membresia", None)
        if membresia is None:
            return False
        return bool(membresia.rol.es_admin or membresia.tiene_permiso("negocio.editar"))

    def get(self, request):
        empresa = request.empresa
        suscripcion = crear_suscripcion_inicial(empresa)
        suscripcion = (
            Suscripcion.objects.select_related("plan", "empresa")
            .get(pk=suscripcion.pk)
        )
        consumo = uso_actual(empresa)
        limites = suscripcion.plan.limites or {}

        dias_restantes = None
        if suscripcion.vence_en is not None:
            segundos = (suscripcion.vence_en - timezone.now()).total_seconds()
            dias_restantes = max(0, math.ceil(segundos / 86400)) if segundos > 0 else 0

        planes_raw = Plan.objects.filter(activo=True).order_by("orden", "precio_mensual")
        planes_ui = []
        for p in planes_raw:
            lim_p = p.limites or {}
            features_legibles = [
                ETIQUETAS_FEATURES.get(cod, cod.replace("_", " ").capitalize())
                for cod in (p.features or [])
            ]
            planes_ui.append(
                {
                    "obj": p,
                    "limites": lim_p,
                    "features_legibles": features_legibles,
                    "es_actual": p.pk == suscripcion.plan_id,
                    "es_pago": cobros.es_plan_pago(p),
                    # Lo que se cobraría hoy en cada ciclo (con descuento de fundador si aplica)
                    "cobro_mensual": cobros.cotizar(suscripcion, p, Suscripcion.Ciclo.MENSUAL)[2],
                    "cobro_anual": cobros.cotizar(suscripcion, p, Suscripcion.Ciclo.ANUAL)[2],
                }
            )

        def _porcentaje(usado, tope):
            if tope is None or int(tope) <= 0:
                return 18  # barra decorativa suave para planes ilimitados
            return min(100, round((int(usado) / int(tope)) * 100))

        contexto = {
            "suscripcion": suscripcion,
            "dias_restantes": dias_restantes,
            "uso": consumo,
            "limites": limites,
            "pct_productos": _porcentaje(consumo.get("productos", 0), limites.get("productos")),
            "pct_usuarios": _porcentaje(consumo.get("usuarios", 0), limites.get("usuarios")),
            "planes_ui": planes_ui,
            "historial": suscripcion.historial.select_related("plan_anterior", "plan_nuevo")[:10],
            "cobros": CobroSuscripcion.objects.filter(empresa=empresa).select_related("plan")[:5],
            "puede_cambiar": self._puede_cambiar(request),
        }
        return render(request, self.template_name, contexto)

    def post(self, request):
        if not self._puede_cambiar(request):
            raise PermissionDenied("Solo el administrador del negocio puede cambiar el plan de suscripción.")

        codigo_plan = (request.POST.get("plan") or "").strip()
        ciclo = (request.POST.get("ciclo") or Suscripcion.Ciclo.MENSUAL).strip().upper()

        plan = Plan.objects.filter(codigo=codigo_plan, activo=True).first()
        if plan is not None and cobros.es_plan_pago(plan):
            # Un plan pago solo se activa cuando Wompi confirma el pago
            try:
                cobro = cobros.iniciar_cobro(empresa=request.empresa, plan=plan, ciclo=ciclo, usuario=request.user)
            except cobros.CobroNoDisponible as exc:
                messages.warning(request, str(exc))
                return redirect("suscripcion_panel")
            except (DowngradeNoPermitido, ValidationError) as exc:
                messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
                return redirect("suscripcion_panel")
            volver = request.build_absolute_uri(reverse("suscripcion_cobro", args=[cobro.pk]))
            return redirect(cobros.url_pago(cobro, redirect_url=volver))

        try:
            nueva = cambiar_plan(
                empresa=request.empresa,
                plan=codigo_plan,
                ciclo=ciclo,
                motivo="Cambio de plan desde el panel web",
            )
        except (DowngradeNoPermitido, ValidationError) as exc:
            mensaje = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
            messages.error(request, mensaje)
        else:
            messages.success(
                request,
                f"¡Listo! Tu empresa ahora está en el plan {nueva.plan.nombre} ({nueva.get_ciclo_display()}).",
            )
        return redirect("suscripcion_panel")


class CobroSuscripcionView(TenantMixin, View):
    """A donde vuelve el administrador desde Wompi: consulta el pago y muestra el resultado."""

    def get(self, request, pk):
        if not SuscripcionPanelView._puede_cambiar(self, request):
            raise PermissionDenied("Solo el administrador del negocio puede ver los cobros del plan.")
        cobro = get_object_or_404(CobroSuscripcion.objects.select_related("plan"), pk=pk, empresa=request.empresa)
        cobro = cobros.sincronizar_cobro(cobro, transaccion_id=request.GET.get("id", ""))
        return render(request, "core/negocio/cobro_suscripcion.html", {"cobro": cobro})


@method_decorator(csrf_exempt, name="dispatch")
class WompiWebhookSuscripcionesView(View):
    """Eventos de la cuenta de Wompi de Intersoft. Firma verificada y transacción consultada en la API."""

    http_method_names = ["post"]

    def post(self, request):
        try:
            evento = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest("JSON no válido.")
        datos = evento.get("data") if isinstance(evento, dict) else None
        transaccion = datos.get("transaction") if isinstance(datos, dict) else None
        if not isinstance(transaccion, dict) or not isinstance(transaccion.get("reference"), str):
            return HttpResponseBadRequest("Transacción no válida.")
        cobro = CobroSuscripcion.objects.filter(referencia=transaccion["reference"]).first()
        if cobro is None:
            return HttpResponseBadRequest("Cobro no válido.")
        try:
            llaves = cobros.credenciales_intersoft()
        except cobros.CobroNoDisponible:
            return HttpResponse(status=503)
        if not evento_es_valido(evento, llaves.eventos):
            return HttpResponseBadRequest("Firma no válida.")
        if evento.get("event") == "transaction.updated":
            # Referencia y moneda no siempre van firmadas: se toman de la API de Wompi
            real = consultar_transaccion(transaccion.get("id"), llaves=llaves)
            if real is None:
                return HttpResponse(status=503)
            if real.get("reference") != cobro.referencia or real.get("id") != transaccion.get("id"):
                return HttpResponseBadRequest("Transacción no válida.")
            cobros.aplicar_transaccion(real)
        return HttpResponse(status=200)
