"""Vistas de la consola interna de plataforma (/plataforma/)."""
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views import View

from core.models import EjecucionTarea, Empresa
from core.tareas import TAREAS, ejecutar_pendientes
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
from . import operacion
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
        atencion = self.requiere_atencion(request.rol_plataforma.permisos, cobros_revision)

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
                "atencion": atencion,
            },
        )

    @staticmethod
    def requiere_atencion(permisos, cobros_revision):
        """Lo urgente para el rol de quien entra, cada cosa con su enlace."""
        from pqrs.models import PQRS
        from soporte.models import ErrorRegistrado

        items = []
        if "finanzas" in permisos and cobros_revision:
            items.append({"tipo": "peligro", "texto": f"{cobros_revision} cobro(s) de plan requieren revisión",
                          "detalle": "Pagos recibidos que no se pudieron activar o con monto distinto.",
                          "url": reverse("plataforma_planes_cobros")})
        if "pqrs" in permisos:
            abiertas = PQRS.objects.exclude(estado__in=[PQRS.Estado.CERRADA, PQRS.Estado.RESPONDIDA])
            escaladas = abiertas.filter(estado=PQRS.Estado.ESCALADA).count()
            vencidas = abiertas.filter(fecha_limite__lt=timezone.now()).count()
            if escaladas or vencidas:
                items.append({"tipo": "alerta", "texto": f"{escaladas} PQRS escalada(s) · {vencidas} vencida(s)",
                              "detalle": "Clientes esperando respuesta.", "url": reverse("plataforma_pqrs")})
        if "errores" in permisos:
            nuevos = ErrorRegistrado.objects.filter(estado=ErrorRegistrado.Estado.NUEVO).count()
            if nuevos:
                items.append({"tipo": "peligro", "texto": f"{nuevos} error(es) nuevo(s) sin revisar",
                              "detalle": "Fallos reales que vieron los usuarios.", "url": reverse("plataforma_errores")})
        if "operacion" in permisos:
            tareas = operacion.estado_tareas()
            con_fallos = [t.nombre for t in tareas if t.fallos_seguidos]
            atrasadas = [t.nombre for t in tareas if t.atrasada and not t.fallos_seguidos]
            if con_fallos:
                items.append({"tipo": "peligro", "texto": f"{len(con_fallos)} tarea(s) periódica(s) fallando",
                              "detalle": ", ".join(con_fallos), "url": reverse("plataforma_operacion")})
            elif atrasadas:
                items.append({"tipo": "alerta", "texto": f"{len(atrasadas)} tarea(s) periódica(s) atrasada(s)",
                              "detalle": "¿Está corriendo el programador de tareas?", "url": reverse("plataforma_operacion")})
        return items


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
        """Cobros filtrados por estado, plan y negocio o referencia, y los filtros aplicados."""
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
        """Contexto de la página Planes y cobros: planes, cobros, fundadores, cupones e interruptores."""
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
        """Verifica en Wompi las llaves de Intersoft y deja el resultado en la auditoría."""
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
        """Actualiza el cupo de fundadores y lo registra en la auditoría."""
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
        """Otorga días gratis o un plan de cortesía a un negocio y lo registra en la auditoría."""
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
        """Vuelve a consultar en Wompi un cobro de plan y registra el cambio de estado."""
        from core.http_utils import obtener_por_uuid_o_404

        cobro = obtener_por_uuid_o_404(CobroSuscripcion, request.POST.get("cobro_id"))
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
        """Activa manualmente el plan de un cobro (con motivo obligatorio) y lo registra en la auditoría."""
        from core.http_utils import obtener_por_uuid_o_404

        cobro = obtener_por_uuid_o_404(
            CobroSuscripcion.objects.select_related("empresa", "plan"),
            request.POST.get("cobro_id"),
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
        """Crea un cupón de descuento para planes."""
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
        """Activa o desactiva un cupón."""
        from core.http_utils import obtener_por_uuid_o_404

        cupon = obtener_por_uuid_o_404(CuponPlan, request.POST.get("cupon_id"))
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
        """Crea o actualiza un interruptor de función para un negocio."""
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
        """Contexto de la página Negocios: búsqueda, directorio y anuncios globales."""
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
            from core.http_utils import obtener_por_uuid_o_404

            empresa = obtener_por_uuid_o_404(Empresa, request.POST.get("empresa_id"))
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
            from core.http_utils import obtener_por_uuid_o_404

            anuncio = obtener_por_uuid_o_404(AnuncioGlobal, request.POST.get("anuncio_id"))
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


class PlataformaTOTPView(PlataformaMixin, View):
    """Enrolamiento, verificación 2FA/TOTP, códigos de recuperación y límite de intentos para /plataforma/."""

    permiso = ""
    requiere_totp = False
    template_name = "plataforma/totp.html"
    max_intentos = 5
    ventana_bloqueo_segundos = 15 * 60

    @staticmethod
    def _clave_intentos(user_id) -> str:
        """Clave de caché para contabilizar intentos fallidos de TOTP por usuario."""
        return f"plataforma:totp:intentos:{user_id}"

    def _esta_bloqueado(self, user_id) -> bool:
        """Devuelve True si el usuario excedió el límite de intentos fallidos de 2FA."""
        from django.core.cache import cache

        return (cache.get(self._clave_intentos(user_id)) or 0) >= self.max_intentos

    def _registrar_fallo(self, user_id) -> int:
        """Incrementa el contador de intentos fallidos de 2FA en caché."""
        from django.core.cache import cache

        clave = self._clave_intentos(user_id)
        intentos = (cache.get(clave) or 0) + 1
        cache.set(clave, intentos, self.ventana_bloqueo_segundos)
        return intentos

    def _limpiar_fallos(self, user_id) -> None:
        """Reinicia el contador de intentos fallidos tras una verificación exitosa."""
        from django.core.cache import cache

        cache.delete(self._clave_intentos(user_id))

    def get(self, request):
        rol = request.rol_plataforma
        codigos_nuevos = request.session.pop("plataforma_totp_codigos_nuevos", None)
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
        return render(
            request,
            self.template_name,
            {
                "configurando": False,
                "codigos_nuevos": codigos_nuevos,
                "codigos_restantes": len(rol.totp_codigos_recuperacion or []),
                "bloqueado": self._esta_bloqueado(request.user.pk),
            },
        )

    def post(self, request):
        import time

        rol = request.rol_plataforma
        if self._esta_bloqueado(request.user.pk):
            messages.error(
                request,
                "Demasiados intentos fallidos de 2FA. Espera 15 minutos antes de volver a intentarlo.",
            )
            return render(
                request,
                self.template_name,
                {
                    "configurando": not rol.totp_activo,
                    "codigos_restantes": len(rol.totp_codigos_recuperacion or []),
                    "bloqueado": True,
                },
                status=429,
            )

        codigo = (request.POST.get("codigo") or "").strip()

        if not rol.totp_activo:
            secreto = request.session.get("plataforma_totp_setup") or ""
            if not verificar_codigo_totp(secreto, codigo):
                self._registrar_fallo(request.user.pk)
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
            self._limpiar_fallos(request.user.pk)
            rol.establecer_totp_secreto(secreto)
            rol.totp_activo = True
            codigos_planos = rol.generar_codigos_recuperacion()
            rol.save(
                update_fields=[
                    "totp_secreto_cifrado",
                    "totp_activo",
                    "totp_codigos_recuperacion",
                    "actualizado_en",
                ]
            )
            request.session.pop("plataforma_totp_setup", None)
            request.session["plataforma_totp_verificado"] = str(request.user.pk)
            request.session["plataforma_totp_ultima_actividad"] = int(time.time())
            request.session["plataforma_totp_codigos_nuevos"] = codigos_planos
            auditoria.registrar(
                actor=request.user,
                accion="activar_totp",
                objeto_tipo="RolPlataforma",
                objeto_id=str(rol.pk),
                detalle={"rol": rol.rol, "codigos_recuperacion": len(codigos_planos)},
                request=request,
            )
            messages.success(
                request,
                "Autenticación en dos pasos (2FA) activada. Guarda tus códigos de recuperación en un lugar seguro.",
            )
            return redirect("plataforma_totp")

        uso_recuperacion = False
        if not verificar_codigo_totp(rol.totp_secreto, codigo):
            if rol.consumir_codigo_recuperacion(codigo):
                uso_recuperacion = True
            else:
                self._registrar_fallo(request.user.pk)
                messages.error(request, "Código TOTP o código de recuperación incorrecto.")
                return render(
                    request,
                    self.template_name,
                    {
                        "configurando": False,
                        "codigos_restantes": len(rol.totp_codigos_recuperacion or []),
                        "bloqueado": self._esta_bloqueado(request.user.pk),
                    },
                )

        self._limpiar_fallos(request.user.pk)
        request.session["plataforma_totp_verificado"] = str(request.user.pk)
        request.session["plataforma_totp_ultima_actividad"] = int(time.time())
        auditoria.registrar(
            actor=request.user,
            accion="usar_codigo_recuperacion_totp" if uso_recuperacion else "verificar_totp",
            objeto_tipo="RolPlataforma",
            objeto_id=str(rol.pk),
            detalle={
                "rol": rol.rol,
                "codigos_restantes": len(rol.totp_codigos_recuperacion or []),
            },
            request=request,
        )
        if uso_recuperacion:
            messages.warning(
                request,
                f"Ingresaste con un código de recuperación. Te quedan {len(rol.totp_codigos_recuperacion or [])}.",
            )
        return redirect("plataforma_inicio")


class OperacionPlataformaView(PlataformaMixin, View):
    """Operación: estado del sistema, tareas periódicas (con ejecución manual), revisión de despliegue y entorno."""

    permiso = "operacion"
    template_name = "plataforma/operacion.html"

    def get(self, request):
        datos = operacion.diagnostico()
        datos["despliegue"] = operacion.revision_despliegue()
        datos["entorno"] = operacion.entorno()
        datos["auditoria_tareas"] = (
            AuditoriaPlataforma.objects.filter(accion="ejecutar_tarea_manual").select_related("actor")[:5]
        )
        return render(request, self.template_name, datos)

    def post(self, request):
        nombre = (request.POST.get("tarea") or "").strip()
        if request.POST.get("accion") != "ejecutar_tarea" or nombre not in {t.nombre for t in TAREAS}:
            messages.error(request, "Tarea no válida.")
            return redirect("plataforma_operacion")
        resultado = ejecutar_pendientes(forzar=True, solo=[nombre]).get(nombre, "error")
        fila = EjecucionTarea.objects.filter(nombre=nombre).first()
        auditoria.registrar(
            actor=request.user,
            accion="ejecutar_tarea_manual",
            objeto_tipo="EjecucionTarea",
            objeto_id=nombre,
            detalle={"resultado": resultado},
            request=request,
        )
        if resultado == "ok":
            messages.success(request, f"«{nombre}» terminó: {(fila.ultimo_resultado if fila else '') or 'sin novedades'}")
        else:
            messages.error(request, f"«{nombre}» falló: {fila.ultimo_error if fila else 'sin detalle'}")
        return redirect("plataforma_operacion")


class AuditoriaPlataformaView(PlataformaMixin, View):
    """Bitácora completa de auditoría con filtros por texto, persona y fechas."""

    permiso = "operacion"
    template_name = "plataforma/auditoria.html"
    por_pagina = 50

    def get(self, request):
        registros = AuditoriaPlataforma.objects.select_related("actor")
        q = (request.GET.get("q") or "").strip()[:80]
        desde = parse_date(request.GET.get("desde") or "")
        hasta = parse_date(request.GET.get("hasta") or "")
        if q:
            registros = registros.filter(
                Q(accion__icontains=q) | Q(objeto_tipo__icontains=q) | Q(objeto_id__icontains=q)
                | Q(actor__email__icontains=q)
            )
        if desde:
            registros = registros.filter(fecha__date__gte=desde)
        if hasta:
            registros = registros.filter(fecha__date__lte=hasta)
        pagina = Paginator(registros.order_by("-fecha"), self.por_pagina).get_page(request.GET.get("pagina"))
        filtros = {"q": q, "desde": request.GET.get("desde") or "", "hasta": request.GET.get("hasta") or ""}
        return render(request, self.template_name, {
            "pagina": pagina,
            "filtros": filtros,
            "filtros_url": urlencode({k: v for k, v in filtros.items() if v}),
        })
