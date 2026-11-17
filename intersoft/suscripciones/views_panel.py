"""Vista web del panel para consultar y cambiar la suscripción SaaS de la empresa activa."""
import math

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from core.mixins import TenantMixin

from .models import Plan, Suscripcion
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
            "puede_cambiar": self._puede_cambiar(request),
        }
        return render(request, self.template_name, contexto)

    def post(self, request):
        if not self._puede_cambiar(request):
            raise PermissionDenied("Solo el administrador del negocio puede cambiar el plan de suscripción.")

        codigo_plan = (request.POST.get("plan") or "").strip()
        ciclo = (request.POST.get("ciclo") or Suscripcion.Ciclo.MENSUAL).strip().upper()

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
