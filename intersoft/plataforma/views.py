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
from suscripciones.models import (
    CobroSuscripcion,
    ConfiguracionSuscripciones,
    CuponPlan,
    Plan,
    Suscripcion,
)
from suscripciones.services import cambiar_plan, cupos_fundador_actuales, otorgar_cortesia

from . import auditoria
from .forms import (
    AnuncioGlobalForm,
    ConfiguracionCobroPlataformaForm,
    CortesiaPlataformaForm,
    CuposFundadorForm,
    CuponPlanForm,
    FeatureFlagForm,
    PlanPlataformaForm,
)
from .metricas import calcular_metricas_saas
from .mixins import PlataformaMixin
from .models import (
    AnuncioGlobal,
    AuditoriaPlataforma,
    ConfiguracionCobroPlataforma,
    FeatureFlag,
    RolPlataforma,
)
from .totp import generar_secreto_totp, qr_data_uri, uri_otpauth, verificar_codigo_totp


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
        cupones = CuponPlan.objects.all()[:30]
        feature_flags = FeatureFlag.objects.select_related("empresa").all()[:40]

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
            "cupones": cupones,
            "cupon_form": CuponPlanForm(),
            "feature_flags": feature_flags,
            "feature_flag_form": FeatureFlagForm(),
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
        if accion == "crear_cupon":
            return self._crear_cupon(request, config)
        if accion == "toggle_cupon":
            return self._toggle_cupon(request)
        if accion == "guardar_feature_flag":
            return self._guardar_feature_flag(request, config)

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

    def _crear_cupon(self, request, config):
        cupon_form = CuponPlanForm(request.POST)
        if cupon_form.is_valid():
            cupon = cupon_form.save()
            auditoria.registrar(
                actor=request.user,
                accion="crear_cupon_plan",
                objeto_tipo="CuponPlan",
                objeto_id=str(cupon.pk),
                detalle={"codigo": cupon.codigo, "tipo": cupon.tipo, "valor": str(cupon.valor)},
                request=request,
            )
            messages.success(request, f"Cupón {cupon.codigo} creado correctamente.")
            return redirect("plataforma_planes_cobros")
        ctx = self._contexto(request, config, ConfiguracionCobroPlataformaForm(instance=config))
        ctx["cupon_form"] = cupon_form
        return render(request, self.template_name, ctx)

    def _toggle_cupon(self, request):
        cupon = get_object_or_404(CuponPlan, pk=request.POST.get("cupon_id"))
        cupon.activo = not cupon.activo
        cupon.save(update_fields=["activo", "actualizado_en"])
        auditoria.registrar(
            actor=request.user,
            accion="toggle_cupon_plan",
            objeto_tipo="CuponPlan",
            objeto_id=str(cupon.pk),
            detalle={"codigo": cupon.codigo, "activo": cupon.activo},
            request=request,
        )
        messages.success(request, f"Cupón {cupon.codigo} {'activado' if cupon.activo else 'desactivado'}.")
        return redirect("plataforma_planes_cobros")

    def _guardar_feature_flag(self, request, config):
        ff_form = FeatureFlagForm(request.POST)
        if ff_form.is_valid():
            flag, _ = FeatureFlag.objects.update_or_create(
                empresa=ff_form.cleaned_data["empresa"],
                codigo=ff_form.cleaned_data["codigo"],
                defaults={"habilitado": ff_form.cleaned_data["habilitado"]},
            )
            auditoria.registrar(
                actor=request.user,
                accion="actualizar_feature_flag",
                objeto_tipo="FeatureFlag",
                objeto_id=str(flag.pk),
                detalle={
                    "empresa_id": str(flag.empresa_id),
                    "codigo": flag.codigo,
                    "habilitado": flag.habilitado,
                },
                request=request,
            )
            messages.success(request, f"Feature flag '{flag.codigo}' actualizado para {flag.empresa.nombre}.")
            return redirect("plataforma_planes_cobros")
        ctx = self._contexto(request, config, ConfiguracionCobroPlataformaForm(instance=config))
        ctx["feature_flag_form"] = ff_form
        return render(request, self.template_name, ctx)


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


class PlataformaNegociosView(PlataformaMixin, View):
    """Directorio de negocios con «Entrar como» (modo soporte) y gestión de anuncios globales."""

    permiso = "negocios"
    template_name = "plataforma/negocios.html"

    def _contexto(self, request, anuncio_form=None):
        q = (request.GET.get("q") or "").strip()
        empresas = Empresa.objects.select_related("suscripcion__plan").order_by("nombre")
        if q:
            empresas = empresas.filter(
                Q(nombre__icontains=q) | Q(nit__icontains=q) | Q(slug__icontains=q)
            )
        anuncios = AnuncioGlobal.objects.select_related("creado_por").all()[:20]
        return {
            "empresas": empresas[:100],
            "q": q,
            "anuncios": anuncios,
            "anuncio_form": anuncio_form or AnuncioGlobalForm(),
        }

    def get(self, request):
        return render(request, self.template_name, self._contexto(request))

    def post(self, request):
        accion = (request.POST.get("accion") or "").strip()

        if accion == "entrar_como":
            if request.rol_plataforma.rol not in (RolPlataforma.Rol.DUENO, RolPlataforma.Rol.SOPORTE):
                raise PermissionDenied("Solo Dueño o Soporte pueden entrar como un negocio.")
            empresa = get_object_or_404(Empresa, pk=request.POST.get("empresa_id"))
            modo = (request.POST.get("modo") or "lectura").strip().lower()
            solo_lectura = modo != "escritura"
            request.session["plataforma_soporte"] = {
                "empresa_id": str(empresa.pk),
                "solo_lectura": solo_lectura,
                "actor_id": str(request.user.pk),
            }
            auditoria.registrar(
                actor=request.user,
                accion="entrar_modo_soporte",
                objeto_tipo="Empresa",
                objeto_id=str(empresa.pk),
                detalle={
                    "empresa": empresa.nombre,
                    "modo": "lectura" if solo_lectura else "escritura",
                },
                request=request,
            )
            return redirect("dashboard")

        if accion == "toggle_anuncio":
            anuncio = get_object_or_404(AnuncioGlobal, pk=request.POST.get("anuncio_id"))
            anuncio.activo = not anuncio.activo
            anuncio.save(update_fields=["activo", "actualizado_en"])
            auditoria.registrar(
                actor=request.user,
                accion="toggle_anuncio_global",
                objeto_tipo="AnuncioGlobal",
                objeto_id=str(anuncio.pk),
                detalle={"titulo": anuncio.titulo, "activo": anuncio.activo},
                request=request,
            )
            messages.success(request, f"Anuncio «{anuncio.titulo}» actualizado.")
            return redirect("plataforma_negocios")

        anuncio_form = AnuncioGlobalForm(request.POST)
        if anuncio_form.is_valid():
            anuncio = anuncio_form.save(commit=False)
            anuncio.creado_por = request.user
            anuncio.save()
            auditoria.registrar(
                actor=request.user,
                accion="crear_anuncio_global",
                objeto_tipo="AnuncioGlobal",
                objeto_id=str(anuncio.pk),
                detalle={"titulo": anuncio.titulo, "tipo": anuncio.tipo, "activo": anuncio.activo},
                request=request,
            )
            messages.success(request, f"Anuncio «{anuncio.titulo}» publicado.")
            return redirect("plataforma_negocios")

        return render(request, self.template_name, self._contexto(request, anuncio_form=anuncio_form))


class SalirModoSoporteView(PlataformaMixin, View):
    """Sale del modo soporte («Entrar como») y deja constancia en AuditoriaPlataforma."""

    permiso = "negocios"

    def post(self, request):
        soporte_ctx = request.session.pop("plataforma_soporte", None)
        if soporte_ctx:
            empresa_id = str(soporte_ctx.get("empresa_id") or "")
            empresa = Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None
            modo_str = "lectura" if soporte_ctx.get("solo_lectura", True) else "escritura"
            auditoria.registrar(
                actor=request.user,
                accion="salir_modo_soporte",
                objeto_tipo="Empresa",
                objeto_id=empresa_id,
                detalle={
                    "empresa": empresa.nombre if empresa else "",
                    "modo": modo_str,
                },
                request=request,
            )
            messages.info(request, "Saliste del modo soporte.")
        return redirect("plataforma_negocios")

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


class PlataformaNegociosView(PlataformaMixin, View):
    """Directorio de negocios con «Entrar como» (modo soporte) y gestión de anuncios globales."""

    permiso = "negocios"
    template_name = "plataforma/negocios.html"

    def _contexto(self, request, anuncio_form=None):
        q = (request.GET.get("q") or "").strip()
        empresas = Empresa.objects.select_related("suscripcion__plan").order_by("nombre")
        if q:
            empresas = empresas.filter(
                Q(nombre__icontains=q) | Q(nit__icontains=q) | Q(slug__icontains=q)
            )
        anuncios = AnuncioGlobal.objects.select_related("creado_por").all()[:20]
        return {
            "empresas": empresas[:100],
            "q": q,
            "anuncios": anuncios,
            "anuncio_form": anuncio_form or AnuncioGlobalForm(),
        }

    def get(self, request):
        return render(request, self.template_name, self._contexto(request))

    def post(self, request):
        accion = (request.POST.get("accion") or "").strip()

        if accion == "entrar_como":
            if request.rol_plataforma.rol not in (RolPlataforma.Rol.DUENO, RolPlataforma.Rol.SOPORTE):
                raise PermissionDenied("Solo Dueño o Soporte pueden entrar como un negocio.")
            empresa = get_object_or_404(Empresa, pk=request.POST.get("empresa_id"))
            modo = (request.POST.get("modo") or "lectura").strip().lower()
            solo_lectura = modo != "escritura"
            request.session["plataforma_soporte"] = {
                "empresa_id": str(empresa.pk),
                "solo_lectura": solo_lectura,
                "actor_id": str(request.user.pk),
            }
            auditoria.registrar(
                actor=request.user,
                accion="entrar_modo_soporte",
                objeto_tipo="Empresa",
                objeto_id=str(empresa.pk),
                detalle={
                    "empresa": empresa.nombre,
                    "modo": "lectura" if solo_lectura else "escritura",
                },
                request=request,
            )
            return redirect("dashboard")

        if accion == "toggle_anuncio":
            anuncio = get_object_or_404(AnuncioGlobal, pk=request.POST.get("anuncio_id"))
            anuncio.activo = not anuncio.activo
            anuncio.save(update_fields=["activo", "actualizado_en"])
            auditoria.registrar(
                actor=request.user,
                accion="toggle_anuncio_global",
                objeto_tipo="AnuncioGlobal",
                objeto_id=str(anuncio.pk),
                detalle={"titulo": anuncio.titulo, "activo": anuncio.activo},
                request=request,
            )
            messages.success(request, f"Anuncio «{anuncio.titulo}» actualizado.")
            return redirect("plataforma_negocios")

        anuncio_form = AnuncioGlobalForm(request.POST)
        if anuncio_form.is_valid():
            anuncio = anuncio_form.save(commit=False)
            anuncio.creado_por = request.user
            anuncio.save()
            auditoria.registrar(
                actor=request.user,
                accion="crear_anuncio_global",
                objeto_tipo="AnuncioGlobal",
                objeto_id=str(anuncio.pk),
                detalle={"titulo": anuncio.titulo, "tipo": anuncio.tipo, "activo": anuncio.activo},
                request=request,
            )
            messages.success(request, f"Anuncio «{anuncio.titulo}» publicado.")
            return redirect("plataforma_negocios")

        return render(request, self.template_name, self._contexto(request, anuncio_form=anuncio_form))


class SalirModoSoporteView(PlataformaMixin, View):
    """Sale del modo soporte («Entrar como») y deja constancia en AuditoriaPlataforma."""

    permiso = "negocios"

    def post(self, request):
        soporte_ctx = request.session.pop("plataforma_soporte", None)
        if soporte_ctx:
            empresa_id = str(soporte_ctx.get("empresa_id") or "")
            empresa = Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None
            modo_str = "lectura" if soporte_ctx.get("solo_lectura", True) else "escritura"
            auditoria.registrar(
                actor=request.user,
                accion="salir_modo_soporte",
                objeto_tipo="Empresa",
                objeto_id=empresa_id,
                detalle={
                    "empresa": empresa.nombre if empresa else "",
                    "modo": modo_str,
                },
                request=request,
            )
            messages.info(request, "Saliste del modo soporte.")
        return redirect("plataforma_negocios")


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


class PlataformaTOTPView(PlataformaMixin, View):
    """Enrolamiento y verificación obligatoria 2FA/TOTP para personal de /plataforma/."""

    permiso = ""
    requiere_totp = False
    template_name = "plataforma/totp.html"

    def get(self, request):
        rol = request.rol_plataforma
        if not rol.totp_activo:
            secreto = request.session.get("plataforma_totp_setup") or generar_secreto_totp()
            request.session["plataforma_totp_setup"] = secreto
            uri = uri_otpauth(secreto, request.user.email)
            return render(
                request,
                self.template_name,
                {
                    "configurando": True,
                    "secreto_nuevo": secreto,
                    "uri_totp": uri,
                    "qr_totp": qr_data_uri(uri),
                },
            )
        return render(request, self.template_name, {"configurando": False})

    def post(self, request):
        rol = request.rol_plataforma
        codigo = (request.POST.get("codigo") or "").strip()

        if not rol.totp_activo:
            secreto = request.session.get("plataforma_totp_setup") or ""
            if not verificar_codigo_totp(secreto, codigo):
                messages.error(request, "Código TOTP inválido. Verifica la hora de tu dispositivo e inténtalo de nuevo.")
                uri = uri_otpauth(secreto, request.user.email)
                return render(
                    request,
                    self.template_name,
                    {
                        "configurando": True,
                        "secreto_nuevo": secreto,
                        "uri_totp": uri,
                        "qr_totp": qr_data_uri(uri),
                    },
                )
            rol.establecer_totp_secreto(secreto)
            rol.totp_activo = True
            rol.save(update_fields=["totp_secreto_cifrado", "totp_activo", "actualizado_en"])
            request.session.pop("plataforma_totp_setup", None)
            request.session["plataforma_totp_verificado"] = str(request.user.pk)
            auditoria.registrar(
                actor=request.user,
                accion="activar_totp",
                objeto_tipo="RolPlataforma",
                objeto_id=str(rol.pk),
                detalle={"rol": rol.rol},
                request=request,
            )
            messages.success(request, "Autenticación en dos pasos (2FA) activada correctamente.")
            return redirect("plataforma_inicio")

        if not verificar_codigo_totp(rol.totp_secreto, codigo):
            messages.error(request, "Código TOTP incorrecto.")
            return render(request, self.template_name, {"configurando": False})

        request.session["plataforma_totp_verificado"] = str(request.user.pk)
        auditoria.registrar(
            actor=request.user,
            accion="verificar_totp",
            objeto_tipo="RolPlataforma",
            objeto_id=str(rol.pk),
            detalle={"rol": rol.rol},
            request=request,
        )
        return redirect("plataforma_inicio")
