"""Vistas de soporte, errores automáticos, reportes, comentarios, NPS e ideas."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from plataforma import auditoria
from plataforma.mixins import PlataformaMixin

from .context_processors import usuario_puede_responder_nps
from .forms import (
    ComentarioWidgetForm,
    EncuestaNPSForm,
    ErrorEstadoForm,
    IdeaEstadoForm,
    IdeaForm,
    ReporteProblemaForm,
)
from .models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, Idea, ReporteProblema, VotoIdea


def _redirigir_seguro(request, destino_crudo: str, fallback: str = "dashboard"):
    """Redirige al destino solo si es del propio sitio; si no, al destino por defecto."""
    if destino_crudo and url_has_allowed_host_and_scheme(
        destino_crudo, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(destino_crudo)
    return redirect(fallback)


class ReportarProblemaView(LoginRequiredMixin, View):
    """Formulario corto de reporte manual con captura automática de URL, navegador, hora y empresa."""

    template_name = "soporte/reportar.html"

    def get(self, request):
        url_origen = (request.GET.get("url") or request.META.get("HTTP_REFERER") or "")[:500]
        form = ReporteProblemaForm(initial={"url": url_origen})
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "url_origen": url_origen,
                "navegador": (request.META.get("HTTP_USER_AGENT") or "")[:300],
                "ahora": timezone.now(),
            },
        )

    def post(self, request):
        from core.rate_limit import respuesta_limite_excedido, verificar_limite

        if not verificar_limite(request, ambito="soporte_reportar", maximo=10, ventana_segundos=900, por_usuario=True):
            return respuesta_limite_excedido(
                "Has enviado varios reportes en pocos minutos. Espera un momento antes de enviar otro."
            )
        form = ReporteProblemaForm(request.POST, request.FILES)
        url_origen = (request.POST.get("url") or request.META.get("HTTP_REFERER") or "")[:500]
        navegador = (request.META.get("HTTP_USER_AGENT") or "")[:300]
        if form.is_valid():
            reporte = form.save(commit=False)
            reporte.empresa = getattr(request, "empresa", None)
            reporte.usuario = request.user
            reporte.url = (form.cleaned_data.get("url") or url_origen)[:500]
            reporte.navegador = navegador
            reporte.fecha_reporte = timezone.now()
            reporte.save()
            messages.success(request, "Gracias por reportar el problema. Nuestro equipo lo revisará.")
            return _redirigir_seguro(request, reporte.url, fallback="dashboard")

        return render(
            request,
            self.template_name,
            {
                "form": form,
                "url_origen": url_origen,
                "navegador": navegador,
                "ahora": timezone.now(),
            },
        )


class EnviarComentarioWidgetView(LoginRequiredMixin, View):
    """Guarda la valoración rápida 👍/👎 y comentario opcional con pantalla de origen."""

    def post(self, request):
        form = ComentarioWidgetForm(request.POST)
        pantalla = (request.POST.get("pantalla") or request.META.get("HTTP_REFERER") or "")[:500]
        if form.is_valid():
            comentario = form.save(commit=False)
            comentario.empresa = getattr(request, "empresa", None)
            comentario.usuario = request.user
            comentario.pantalla = (form.cleaned_data.get("pantalla") or pantalla)[:500]
            comentario.save()
            messages.success(request, "¡Gracias por tu opinión!")
        else:
            messages.error(request, "No se pudo guardar tu comentario.")
        return _redirigir_seguro(request, pantalla, fallback="dashboard")


class EnviarNPSView(LoginRequiredMixin, View):
    """Guarda la encuesta NPS (0 a 10) respetando el límite de 1 cada 90 días por usuario."""

    def post(self, request):
        if not usuario_puede_responder_nps(request.user):
            return HttpResponseBadRequest("Ya respondiste la encuesta NPS en los últimos 90 días.")

        form = EncuestaNPSForm(request.POST)
        pantalla = (request.POST.get("pantalla") or request.META.get("HTTP_REFERER") or "")[:500]
        if form.is_valid():
            nps = form.save(commit=False)
            nps.empresa = getattr(request, "empresa", None)
            nps.usuario = request.user
            nps.pantalla = (form.cleaned_data.get("pantalla") or pantalla)[:500]
            nps.save()
            messages.success(request, "¡Gracias por calificar tu experiencia en Intersoft!")
        else:
            messages.error(request, "El puntaje NPS debe estar entre 0 y 10.")
        return _redirigir_seguro(request, pantalla, fallback="dashboard")


class IdeasListaView(LoginRequiredMixin, View):
    """Permite a los negocios proponer ideas y votar por las existentes."""

    template_name = "soporte/ideas.html"

    def _contexto(self, request, form=None):
        """Ideas ordenadas por votos y las que ya votó el usuario."""
        ideas = Idea.objects.annotate(total_votos=Count("votos")).order_by("-total_votos", "-creado_en")
        mis_votos_ids = set(
            VotoIdea.objects.filter(usuario=request.user).values_list("idea_id", flat=True)
        )
        return {
            "ideas": ideas,
            "mis_votos_ids": mis_votos_ids,
            "form": form or IdeaForm(),
        }

    def get(self, request):
        return render(request, self.template_name, self._contexto(request))

    def post(self, request):
        form = IdeaForm(request.POST)
        if form.is_valid():
            idea = form.save(commit=False)
            idea.empresa = getattr(request, "empresa", None)
            idea.autor = request.user
            idea.save()
            VotoIdea.objects.get_or_create(idea=idea, usuario=request.user)
            messages.success(request, "Idea publicada y votada.")
            return redirect("soporte_ideas")
        return render(request, self.template_name, self._contexto(request, form=form))


class VotarIdeaView(LoginRequiredMixin, View):
    """Registra un voto único por usuario para una idea."""

    def post(self, request, pk):
        idea = get_object_or_404(Idea, pk=pk)
        _, creado = VotoIdea.objects.get_or_create(idea=idea, usuario=request.user)
        if creado:
            messages.success(request, f"Votaste por «{idea.titulo}».")
        else:
            messages.info(request, "Tu voto por esta idea ya estaba registrado.")
        return redirect("soporte_ideas")


class PlataformaErroresListView(PlataformaMixin, View):
    """Bandeja de errores 500 agrupados por huella y reportes de usuarios en /plataforma/errores/."""

    permiso = "errores"
    template_name = "soporte/plataforma_errores.html"

    def get(self, request):
        estado = (request.GET.get("estado") or "").strip()
        q = (request.GET.get("q") or "").strip()

        errores = ErrorRegistrado.objects.select_related("empresa", "usuario").all()
        if estado:
            errores = errores.filter(estado=estado)
        if q:
            errores = errores.filter(
                Q(tipo_excepcion__icontains=q)
                | Q(archivo__icontains=q)
                | Q(url__icontains=q)
                | Q(mensaje__icontains=q)
            )

        hace_7d = timezone.now() - timedelta(days=7)
        errores_nuevos_7d = ErrorRegistrado.objects.filter(primera_vez__gte=hace_7d).count()
        reportes = ReporteProblema.objects.select_related("empresa", "usuario")[:25]

        return render(
            request,
            self.template_name,
            {
                "errores": errores[:50],
                "errores_nuevos_7d": errores_nuevos_7d,
                "reportes": reportes,
                "estados": ErrorRegistrado.Estado.choices,
                "filtros": {"estado": estado, "q": q},
            },
        )


class PlataformaErrorDetalleView(PlataformaMixin, View):
    """Detalle de un error agrupado y cambio de estado (nuevo/investigando/resuelto/ignorado)."""

    permiso = "errores"
    template_name = "soporte/plataforma_error_detalle.html"

    def get(self, request, pk):
        error_obj = get_object_or_404(
            ErrorRegistrado.objects.select_related("empresa", "usuario"), pk=pk
        )
        form = ErrorEstadoForm(instance=error_obj)
        return render(request, self.template_name, {"error_obj": error_obj, "form": form})

    def post(self, request, pk):
        error_obj = get_object_or_404(ErrorRegistrado, pk=pk)
        estado_anterior = error_obj.estado
        form = ErrorEstadoForm(request.POST, instance=error_obj)
        if form.is_valid():
            actualizado = form.save()
            auditoria.registrar(
                actor=request.user,
                accion="actualizar_estado_error",
                objeto_tipo="ErrorRegistrado",
                objeto_id=str(actualizado.pk),
                detalle={
                    "huella": actualizado.huella[:12],
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": actualizado.estado,
                },
                request=request,
            )
            messages.success(request, "Estado del error actualizado.")
            return redirect("plataforma_error_detalle", pk=actualizado.pk)
        return render(request, self.template_name, {"error_obj": error_obj, "form": form})


class PlataformaComentariosListView(PlataformaMixin, View):
    """Bandeja de comentarios 👍/👎 y métricas NPS en /plataforma/comentarios/."""

    permiso = "comentarios"
    template_name = "soporte/plataforma_comentarios.html"

    def get(self, request):
        util = (request.GET.get("util") or "").strip()
        pantalla = (request.GET.get("pantalla") or "").strip()

        comentarios = ComentarioWidget.objects.select_related("empresa", "usuario").all()
        if util == "1":
            comentarios = comentarios.filter(util=True)
        elif util == "0":
            comentarios = comentarios.filter(util=False)
        if pantalla:
            comentarios = comentarios.filter(pantalla__icontains=pantalla)

        total_nps = EncuestaNPS.objects.count()
        if total_nps > 0:
            promotores = EncuestaNPS.objects.filter(puntaje__gte=9).count()
            detractores = EncuestaNPS.objects.filter(puntaje__lte=6).count()
            nps_actual = round(((promotores - detractores) / total_nps) * 100, 1)
        else:
            nps_actual = None

        encuestas_recientes = EncuestaNPS.objects.select_related("empresa", "usuario")[:20]

        return render(
            request,
            self.template_name,
            {
                "comentarios": comentarios[:50],
                "nps_actual": nps_actual,
                "total_nps": total_nps,
                "encuestas_recientes": encuestas_recientes,
                "filtros": {"util": util, "pantalla": pantalla},
            },
        )


class PlataformaIdeasListView(PlataformaMixin, View):
    """Bandeja de ideas más votadas y cambio de estado en /plataforma/ideas/."""

    permiso = "ideas"
    template_name = "soporte/plataforma_ideas.html"

    def get(self, request):
        estado = (request.GET.get("estado") or "").strip()
        ideas = Idea.objects.annotate(total_votos=Count("votos")).select_related("empresa", "autor")
        if estado:
            ideas = ideas.filter(estado=estado)
        ideas = ideas.order_by("-total_votos", "-creado_en")

        return render(
            request,
            self.template_name,
            {
                "ideas": ideas,
                "estados": Idea.Estado.choices,
                "filtro_estado": estado,
            },
        )

    def post(self, request):
        from core.http_utils import obtener_por_uuid_o_404

        idea = obtener_por_uuid_o_404(Idea, request.POST.get("idea_id"))
        estado_anterior = idea.estado
        form = IdeaEstadoForm(request.POST, instance=idea)
        if form.is_valid():
            actualizada = form.save()
            auditoria.registrar(
                actor=request.user,
                accion="cambiar_estado_idea",
                objeto_tipo="Idea",
                objeto_id=str(actualizada.pk),
                detalle={
                    "titulo": actualizada.titulo,
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": actualizada.estado,
                },
                request=request,
            )
            messages.success(request, f"Idea «{actualizada.titulo}» actualizada a {actualizada.get_estado_display()}.")
        return redirect("plataforma_ideas")
