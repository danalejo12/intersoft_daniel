"""Vistas de la consola interna de plataforma (/plataforma/)."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from core.models import EjecucionTarea, Empresa
from core.pasarela_negocio import verificar_llaves
from suscripciones import cobros as cobros_suscripcion
from suscripciones.models import CobroSuscripcion, ConfiguracionSuscripciones, Plan, Suscripcion
from suscripciones.services import cambiar_plan, cupos_fundador_actuales, otorgar_cortesia

from . import auditoria
from .forms import (
    ConfiguracionCobroPlataformaForm,
    CortesiaPlataformaForm,
    CuposFundadorForm,
    PlanPlataformaForm,
)
from .metricas import calcular_metricas_saas
from .mixins import PlataformaMixin
from .models import AuditoriaPlataforma, ConfiguracionCobroPlataforma, RolPlataforma


class InicioPlataformaView(PlataformaMixin, View):
    """Inicio de /plataforma/: métricas globales SaaS y estado de tareas periódicas."""

    permiso = "inicio"
    template_name = "plataforma/inicio.html"

    def get(self, request):
        negocios_activos = Empresa.objects.filter(activa=True).count()
        negocios_prueba = Suscripcion.objects.filter(
            empresa__activa=True,
            estado=Suscripcion.Estado.TRIAL,
        ).count()
        negocios_plan_pago = (
            Suscripcion.objects.filter(
                empresa__activa=True,
                estado=Suscripcion.Estado.ACTIVA,
            )
            .exclude(plan__codigo="gratis")
            .count()
        )
        cobros_pendientes = CobroSuscripcion.objects.filter(
            estado=CobroSuscripcion.Estado.PENDIENTE
        ).count()
        cobros_revision = CobroSuscripcion.objects.filter(
            estado=CobroSuscripcion.Estado.REQUIERE_REVISION
        ).count()

        tareas = EjecucionTarea.objects.all().order_by("nombre")
        auditorias_recientes = AuditoriaPlataforma.objects.select_related("actor")[:8]
        metricas = calcular_metricas_saas()

        return render(
            request,
            self.template_name,
            {
                "negocios_activos": negocios_activos,
                "negocios_prueba": negocios_prueba,
                "negocios_plan_pago": negocios_plan_pago,
                "cobros_pendientes": cobros_pendientes,
                "cobros_revision": cobros_revision,
                "tareas": tareas,
                "auditorias_recientes": auditorias_recientes,
                "metricas": metricas,
            },
        )


class PlanesCobrosPlataformaView(PlataformaMixin, View):
    """Gestión de planes, cobros, cortesías, fundadores y llaves de Wompi de Intersoft."""

    permiso = "finanzas"
    template_name = "plataforma/planes_cobros.html"

    def _puede_editar_llaves(self, request) -> bool:
        return (
            request.rol_plataforma.rol == RolPlataforma.Rol.DUENO
            and request.rol_plataforma.tiene_permiso("llaves_wompi")
        )

    def _cobros_filtrados(self, request):
        estado = (request.GET.get("estado") or "").strip()
        plan_codigo = (request.GET.get("plan") or "").strip()
        negocio = (request.GET.get("negocio") or "").strip()

        qs = CobroSuscripcion.objects.select_related("empresa", "plan").all()
        if estado:
            qs = qs.filter(estado=estado)
        if plan_codigo:
            qs = qs.filter(plan__codigo=plan_codigo)
        if negocio:
            qs = qs.filter(
                Q(empresa__nombre__icontains=negocio)
                | Q(empresa__slug__icontains=negocio)
                | Q(referencia__icontains=negocio)
            )
        return qs[:50], {"estado": estado, "plan": plan_codigo, "negocio": negocio}

    def _contexto(
        self,
        request,
        config,
        form,
        *,
        cortesia_form=None,
        cupos_form=None,
    ):
        planes = Plan.objects.all().order_by("orden", "precio_mensual")
        cobros_filtrados, filtros = self._cobros_filtrados(request)
        cobros_revision = CobroSuscripcion.objects.select_related("empresa", "plan").filter(
            estado=CobroSuscripcion.Estado.REQUIERE_REVISION
        )
        fundadores_ocupados = Suscripcion.objects.filter(es_fundador=True).count()
        cupos_fundador = cupos_fundador_actuales()

        return {
            "config": config,
            "form": form,
            "puede_editar_llaves": self._puede_editar_llaves(request),
            "planes": planes,
            "cobros_recientes": cobros_filtrados,
            "cobros_revision": cobros_revision,
            "filtros": filtros,
            "estados_cobro": CobroSuscripcion.Estado.choices,
            "fundadores_ocupados": fundadores_ocupados,
            "cupos_fundador": cupos_fundador,
            "cupos_disponibles": max(cupos_fundador - fundadores_ocupados, 0),
            "cupos_form": cupos_form or CuposFundadorForm(initial={"cupos_fundador": cupos_fundador}),
            "cortesia_form": cortesia_form or CortesiaPlataformaForm(),
        }

    def get(self, request):
        config = ConfiguracionCobroPlataforma.obtener()
        form = ConfiguracionCobroPlataformaForm(instance=config)
        return render(request, self.template_name, self._contexto(request, config, form))

    def post(self, request):
        config = ConfiguracionCobroPlataforma.obtener()
        accion = (request.POST.get("accion") or "guardar").strip()

        if accion == "actualizar_cupos_fundador":
            return self._actualizar_cupos_fundador(request, config)
        if accion == "otorgar_cortesia":
            return self._otorgar_cortesia(request, config)
        if accion == "reconsultar_cobro":
            return self._reconsultar_cobro(request)
        if accion == "aplicar_cobro_manual":
            return self._aplicar_cobro_manual(request)

        if not self._puede_editar_llaves(request):
            raise PermissionDenied("Solo el rol Dueño puede editar o verificar las llaves de Wompi.")

        if accion == "verificar":
            return self._verificar_llaves(request, config)

        form = ConfiguracionCobroPlataformaForm(request.POST, instance=config)
        if form.is_valid():
            config, campos_cambiados = form.guardar(request.user)
            auditoria.registrar(
                actor=request.user,
                accion="actualizar_llaves_wompi",
                objeto_tipo="ConfiguracionCobroPlataforma",
                objeto_id=str(config.pk),
                detalle={
                    "modo": config.modo,
                    "activa": config.activa,
                    "campos_actualizados": campos_cambiados,
                },
                request=request,
            )
            messages.success(request, "Configuración de cobro de Intersoft guardada correctamente.")
            return redirect("plataforma_planes_cobros")

        return render(request, self.template_name, self._contexto(request, config, form))

    def _verificar_llaves(self, request, config):
        if not config.llave_publica:
            messages.error(request, "Guarda primero una llave pública antes de verificar.")
            return redirect("plataforma_planes_cobros")

        resultado = verificar_llaves(config)
        config.ultimo_intento_verificacion = timezone.now()
        if resultado.ok:
            config.verificada_en = config.ultimo_intento_verificacion
            config.comercio_verificado = resultado.comercio
            config.save(
                update_fields=[
                    "verificada_en",
                    "comercio_verificado",
                    "ultimo_intento_verificacion",
                    "actualizado_en",
                ]
            )
            messages.success(
                request,
                f"Llaves verificadas correctamente en Wompi ({resultado.comercio or config.get_modo_display()}).",
            )
        else:
            config.verificada_en = None
            config.save(
                update_fields=["verificada_en", "ultimo_intento_verificacion", "actualizado_en"]
            )
            messages.error(request, " ".join(resultado.errores))

        auditoria.registrar(
            actor=request.user,
            accion="verificar_llaves_wompi",
            objeto_tipo="ConfiguracionCobroPlataforma",
            objeto_id=str(config.pk),
            detalle={
                "modo": config.modo,
                "verificacion_ok": resultado.ok,
                "comercio": resultado.comercio,
            },
            request=request,
        )
        return redirect("plataforma_planes_cobros")

    def _actualizar_cupos_fundador(self, request, config):
        cupos_form = CuposFundadorForm(request.POST)
        if cupos_form.is_valid():
            nuevo_cupo = cupos_form.cleaned_data["cupos_fundador"]
            cfg_sus = ConfiguracionSuscripciones.obtener()
            anterior = cfg_sus.cupos_fundador
            cfg_sus.cupos_fundador = nuevo_cupo
            cfg_sus.save(update_fields=["cupos_fundador", "actualizado_en"])
            auditoria.registrar(
                actor=request.user,
                accion="actualizar_cupos_fundador",
                objeto_tipo="ConfiguracionSuscripciones",
                objeto_id=str(cfg_sus.pk),
                detalle={"antes": anterior, "despues": nuevo_cupo},
                request=request,
            )
            messages.success(request, f"Cupos de fundador actualizados a {nuevo_cupo}.")
            return redirect("plataforma_planes_cobros")

        form = ConfiguracionCobroPlataformaForm(instance=config)
        return render(
            request,
            self.template_name,
            self._contexto(request, config, form, cupos_form=cupos_form),
        )

    def _otorgar_cortesia(self, request, config):
        cortesia_form = CortesiaPlataformaForm(request.POST)
        if cortesia_form.is_valid():
            empresa = cortesia_form.cleaned_data["empresa"]
            plan = cortesia_form.cleaned_data["plan"]
            dias = cortesia_form.cleaned_data["dias"]
            motivo = cortesia_form.cleaned_data["motivo"]
            try:
                suscripcion = otorgar_cortesia(empresa, motivo=motivo, dias=dias, plan=plan)
            except ValidationError as exc:
                cortesia_form.add_error(None, exc.messages[0] if exc.messages else str(exc))
            else:
                auditoria.registrar(
                    actor=request.user,
                    accion="otorgar_cortesia",
                    objeto_tipo="Suscripcion",
                    objeto_id=str(suscripcion.pk),
                    detalle={
                        "empresa_id": str(empresa.pk),
                        "empresa": empresa.nombre,
                        "plan": suscripcion.plan.codigo,
                        "dias": dias,
                        "motivo": motivo,
                    },
                    request=request,
                )
                messages.success(
                    request,
                    f"Cortesía aplicada a {empresa.nombre} (plan {suscripcion.plan.nombre}).",
                )
                return redirect("plataforma_planes_cobros")

        form = ConfiguracionCobroPlataformaForm(instance=config)
        return render(
            request,
            self.template_name,
            self._contexto(request, config, form, cortesia_form=cortesia_form),
        )

    def _reconsultar_cobro(self, request):
        cobro = get_object_or_404(CobroSuscripcion, pk=request.POST.get("cobro_id"))
        estado_anterior = cobro.estado
        cobro_actualizado = cobros_suscripcion.sincronizar_cobro(cobro, forzar=True)
        auditoria.registrar(
            actor=request.user,
            accion="reconsultar_cobro_wompi",
            objeto_tipo="CobroSuscripcion",
            objeto_id=str(cobro.pk),
            detalle={
                "referencia": cobro.referencia,
                "estado_anterior": estado_anterior,
                "estado_nuevo": cobro_actualizado.estado,
            },
            request=request,
        )
        messages.info(
            request,
            f"Cobro {cobro.referencia} consultado en Wompi. Estado actual: {cobro_actualizado.get_estado_display()}.",
        )
        return redirect("plataforma_planes_cobros")

    def _aplicar_cobro_manual(self, request):
        cobro = get_object_or_404(
            CobroSuscripcion.objects.select_related("empresa", "plan"),
            pk=request.POST.get("cobro_id"),
        )
        motivo = (request.POST.get("motivo") or "").strip()
        if not motivo:
            messages.error(request, "Debes indicar un motivo para aplicar manualmente el cobro.")
            return redirect("plataforma_planes_cobros")
        if cobro.estado == CobroSuscripcion.Estado.APROBADO:
            messages.warning(request, f"El cobro {cobro.referencia} ya estaba aprobado.")
            return redirect("plataforma_planes_cobros")

        actor_nombre = request.user.get_full_name() or request.user.email
        try:
            with transaction.atomic():
                cambiar_plan(
                    cobro.empresa,
                    cobro.plan,
                    cobro.ciclo,
                    motivo=f"Aplicación manual cobro {cobro.referencia}: {motivo}"[:255],
                    forzar_fundador=cobro.descuento_porcentaje > 0,
                )
                cobro.estado = CobroSuscripcion.Estado.APROBADO
                cobro.resuelto_en = timezone.now()
                cobro.detalle = f"Aplicado manualmente por {actor_nombre}"[:255]
                cobro.save(update_fields=["estado", "resuelto_en", "detalle", "actualizado_en"])
        except ValidationError as exc:
            messages.error(
                request,
                f"No se pudo activar el plan: {exc.messages[0] if exc.messages else exc}",
            )
            return redirect("plataforma_planes_cobros")

        auditoria.registrar(
            actor=request.user,
            accion="aplicar_cobro_manual",
            objeto_tipo="CobroSuscripcion",
            objeto_id=str(cobro.pk),
            detalle={
                "referencia": cobro.referencia,
                "empresa_id": str(cobro.empresa_id),
                "plan": cobro.plan.codigo,
                "motivo": motivo,
            },
            request=request,
        )
        messages.success(
            request,
            f"Cobro {cobro.referencia} aplicado manualmente y plan {cobro.plan.nombre} activado.",
        )
        return redirect("plataforma_planes_cobros")


class EditarPlanPlataformaView(PlataformaMixin, View):
    """Editor de precios, límites, funcionalidades y comisión de un plan."""

    permiso = "finanzas"
    template_name = "plataforma/editar_plan.html"

    def get(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanPlataformaForm(instance=plan)
        return render(request, self.template_name, {"plan": plan, "form": form})

    def post(self, request, pk):
        plan = get_object_or_404(Plan, pk=pk)
        form = PlanPlataformaForm(request.POST, instance=plan)
        if form.is_valid():
            plan_actualizado, cambios = form.guardar()
            auditoria.registrar(
                actor=request.user,
                accion="editar_plan",
                objeto_tipo="Plan",
                objeto_id=str(plan_actualizado.pk),
                detalle={"codigo": plan_actualizado.codigo, "cambios": cambios},
                request=request,
            )
            messages.success(request, f"Plan {plan_actualizado.nombre} actualizado correctamente.")
            return redirect("plataforma_planes_cobros")
        return render(request, self.template_name, {"plan": plan, "form": form})


class SeccionProximamenteView(PlataformaMixin, View):
    """Vista marcador para secciones de la consola aún en construcción."""

    titulo_seccion = ""
    descripcion_seccion = ""
    template_name = "plataforma/proximamente.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "titulo_seccion": self.titulo_seccion,
                "descripcion_seccion": self.descripcion_seccion,
            },
        )
