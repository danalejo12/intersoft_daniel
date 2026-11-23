"""Vistas principales del panel: inicio, configuración del negocio, clientes y re-exportaciones."""
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.tokens import default_token_generator
from django.contrib.messages.views import SuccessMessageMixin
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.formats import date_format
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from .forms import ClienteForm, DatosNegocioForm, PerfilUsuarioForm
from .mixins import PermisoRequeridoMixin, TenantMixin
from .models import Bodega, Cliente, Factura, Membresia, Producto
from .primeros_pasos import pasos_del_negocio
from .redirecciones import destino_seguro
from .views_facturas import (
    FacturaAnularView,
    FacturaCobrarView,
    FacturaContabilizarView,
    FacturaCreateView,
    FacturaDetailView,
    FacturaEmitirDianView,
    FacturaListView,
    FacturaPDFView,
    PagoResultadoView,
    PagoSimuladorView,
    WompiWebhookView,
)
from .views_inventario import (
    CategoriaCreateView,
    CategoriaDeleteView,
    CategoriaFormMixin,
    CategoriaListView,
    CategoriaUpdateView,
    EliminarLogicoView,
    MovimientoCreateView,
    ProductoCreateView,
    ProductoDeleteView,
    ProductoFormMixin,
    ProductoKardexView,
    ProductoListView,
    ProductoUpdateView,
)


# ---------------------------------------------------------------
# Dashboard y Negocio
# ---------------------------------------------------------------
class DashboardView(TenantMixin, TemplateView):
    template_name = "core/dashboard.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        empresa = self.request.empresa

        # TemplateView NO pasa por get_queryset: filtramos por empresa a mano
        productos = Producto.objects.de_empresa(empresa).filter(activo=True)

        # Guía de primeros pasos: solo para quien administra el negocio y mientras falte algo
        if self.request.membresia.tiene_permiso("negocio.editar"):
            pasos = pasos_del_negocio(empresa, self.request.user)
            hechos = sum(paso.hecho for paso in pasos)
            if hechos < len(pasos):
                contexto["primeros_pasos"] = pasos
                contexto["pasos_hechos"] = hechos
                contexto["pasos_avance"] = round(100 * hechos / len(pasos))

        contexto["total_clientes"] = Cliente.objects.de_empresa(empresa).filter(activo=True).count()
        total_productos = productos.count()
        contexto["total_productos"] = total_productos
        # F("stock_minimo") compara dos columnas DENTRO de PostgreSQL
        stock_bajo = productos.filter(stock__lte=F("stock_minimo")).order_by("stock")
        contexto["stock_bajo"] = stock_bajo
        contexto["puede_mover"] = self.request.membresia.tiene_permiso("inventario.movimientos")

        # Salud del inventario: porcentaje de productos por encima de su mínimo
        n_stock_bajo = stock_bajo.count()
        contexto["n_stock_bajo"] = n_stock_bajo
        contexto["productos_sanos"] = total_productos - n_stock_bajo
        contexto["salud_inventario"] = (
            round(100 * (total_productos - n_stock_bajo) / total_productos) if total_productos else 100
        )

        # Ventas: solo si el rol tiene permiso de ver ventas o reportes
        puede_ver_ventas = (
            self.request.membresia.tiene_permiso("ventas.ver")
            or self.request.membresia.tiene_permiso("reportes.ver")
        )
        contexto["puede_ver_ventas"] = puede_ver_ventas
        bodegas_disponibles = list(Bodega.objects.filter(empresa=empresa, activa=True).order_by("-es_principal", "nombre"))
        bodega_id = (self.request.GET.get("bodega") or "").strip()
        bodega_activa = next((b for b in bodegas_disponibles if str(b.pk) == bodega_id), None)
        contexto["bodegas_disponibles"] = bodegas_disponibles
        contexto["bodega_activa"] = bodega_activa

        if puede_ver_ventas:
            ventas = Factura.objects.de_empresa(empresa).exclude(estado=Factura.Estado.ANULADA)
            if bodega_activa is not None:
                ventas = ventas.filter(bodega=bodega_activa)
            ahora = timezone.localtime()
            inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if inicio_mes.month == 1:
                inicio_mes_anterior = inicio_mes.replace(year=inicio_mes.year - 1, month=12)
            else:
                inicio_mes_anterior = inicio_mes.replace(month=inicio_mes.month - 1)
            del_mes = ventas.filter(creado_en__gte=inicio_mes).aggregate(total=Sum("total"), cantidad=Count("id"))
            anterior = ventas.filter(
                creado_en__gte=inicio_mes_anterior, creado_en__lt=inicio_mes
            ).aggregate(total=Sum("total"))
            ventas_mes = del_mes["total"] or 0
            ventas_mes_anterior = anterior["total"] or 0
            variacion_pct = (
                round(float((ventas_mes - ventas_mes_anterior) * 100 / ventas_mes_anterior), 1)
                if ventas_mes_anterior
                else None
            )
            contexto["ventas_mes"] = ventas_mes
            contexto["ventas_mes_anterior"] = ventas_mes_anterior
            contexto["variacion_mes_pct"] = variacion_pct
            contexto["facturas_mes"] = del_mes["cantidad"]
            contexto["ultimas_facturas"] = ventas.select_related("cliente").order_by("-numero")[:5]
            contexto["serie_meses"] = self.serie_meses(ventas, inicio_mes)
            contexto["serie_dias"] = self.serie_dias(ventas, ahora.date())
        else:
            contexto["ventas_mes"] = 0
            contexto["ventas_mes_anterior"] = 0
            contexto["variacion_mes_pct"] = None
            contexto["facturas_mes"] = 0
            contexto["ultimas_facturas"] = []
            contexto["serie_meses"] = {"etiquetas": [], "valores": []}
            contexto["serie_dias"] = {"etiquetas": [], "valores": []}
        contexto.update(self.contexto_bienvenida(empresa))
        return contexto

    def contexto_bienvenida(self, empresa):
        """Saludo y pendientes propios de esta persona para la parte de arriba del inicio."""
        from suscripciones.models import Suscripcion

        from .caja import turno_abierto

        usuario = self.request.user
        hora = timezone.localtime().hour
        saludo = "Buenos días" if hora < 12 else "Buenas tardes" if hora < 19 else "Buenas noches"
        extra = {
            "saludo": saludo,
            "nombre_saludo": (usuario.first_name or "").split(" ")[0],
            "hoy": timezone.localdate(),
            "caja_abierta": None,
            "aviso_plan": None,
        }
        if self.request.membresia.tiene_permiso("ventas.crear"):
            extra["caja_abierta"] = turno_abierto(empresa, usuario)
        if self.request.membresia.tiene_permiso("negocio.editar"):
            sub = Suscripcion.objects.filter(empresa=empresa).select_related("plan").first()
            if sub and sub.vence_en:
                dias = (timezone.localdate(sub.vence_en) - timezone.localdate()).days
                if 0 <= dias <= 7:
                    extra["aviso_plan"] = {
                        "dias": dias,
                        "es_prueba": sub.estado == Suscripcion.Estado.TRIAL,
                        "plan": sub.plan.nombre,
                    }
        return extra

    @staticmethod
    def serie_meses(ventas, inicio_mes, cantidad=6):
        """Total facturado en los últimos 6 meses, incluido el actual; los meses sin ventas valen 0."""
        meses = []
        anio, mes = inicio_mes.year, inicio_mes.month
        for _ in range(cantidad):
            meses.append((anio, mes))
            anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
        meses.reverse()
        desde = inicio_mes.replace(year=meses[0][0], month=meses[0][1])
        totales = {
            (fila["mes"].year, fila["mes"].month): fila["total"]
            for fila in ventas.filter(creado_en__gte=desde)
            .annotate(mes=TruncMonth("creado_en")).values("mes").annotate(total=Sum("total"))
        }
        return {
            "etiquetas": [date_format(date(anio, mes, 1), "M Y") for anio, mes in meses],
            "valores": [float(totales.get(clave, 0)) for clave in meses],
        }

    @staticmethod
    def serie_dias(ventas, hoy, cantidad=7):
        """Total facturado en los últimos 7 días, incluido hoy."""
        dias = [hoy - timedelta(days=atras) for atras in range(cantidad - 1, -1, -1)]
        totales = {
            fila["dia"]: fila["total"]
            for fila in ventas.filter(creado_en__date__gte=dias[0])
            .annotate(dia=TruncDate("creado_en")).values("dia").annotate(total=Sum("total"))
        }
        return {
            "etiquetas": [date_format(dia, "j M") for dia in dias],
            "valores": [float(totales.get(dia, 0)) for dia in dias],
        }


class DatosNegocioView(PermisoRequeridoMixin, SuccessMessageMixin, UpdateView):
    """Dirección y teléfono legales del negocio. Sin ellos, sus productos no salen en el marketplace."""

    permiso_requerido = "negocio.editar"  # solo el rol administrador, que tiene todos los permisos
    form_class = DatosNegocioForm
    template_name = "core/negocio/datos.html"
    success_url = reverse_lazy("dashboard")
    success_message = "¡Listo! Guardamos los datos de tu negocio."

    def get_object(self, queryset=None):
        # El negocio es siempre el activo: nunca se recibe un id desde la URL
        return self.request.empresa

    def form_valid(self, form):
        # Se salta TenantMixin.form_valid: Empresa no tiene campo empresa
        return super(TenantMixin, self).form_valid(form)


class CambiarNegocioView(TenantMixin, View):
    """Cambia la empresa activa en la sesión solo si el usuario tiene membresía activa en ella."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        empresa_id = (request.POST.get("empresa_id") or "").strip()
        if not empresa_id:
            raise Http404("Negocio no especificado.")
        try:
            membresia = (
                Membresia.objects.select_related("empresa")
                .filter(
                    usuario=request.user,
                    empresa_id=empresa_id,
                    activa=True,
                    empresa__activa=True,
                )
                .first()
            )
        except (ValueError, ValidationError) as error:
            raise Http404("Identificador de negocio inválido.") from error

        if membresia is None:
            raise Http404("No tienes una membresía activa en ese negocio.")

        request.session["empresa_id"] = str(membresia.empresa_id)
        messages.success(request, f"Cambiaste al negocio «{membresia.empresa.nombre}».")
        return HttpResponseRedirect(destino_seguro(request) or reverse("dashboard"))


# ---------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------
class ClienteListView(PermisoRequeridoMixin, ListView):
    model = Cliente
    permiso_requerido = "clientes.ver"
    template_name = "core/clientes/lista.html"
    context_object_name = "clientes"
    paginate_by = 20

    def get_queryset(self):
        # super() ya trae solo los clientes de la empresa activa (TenantMixin)
        queryset = super().get_queryset().filter(activo=True).order_by("nombre")
        self.q = self.request.GET.get("q", "").strip()
        if self.q:
            queryset = queryset.filter(
                Q(nombre__icontains=self.q) | Q(numero_documento__icontains=self.q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        membresia = self.request.membresia
        contexto["q"] = self.q
        # La plantilla no puede llamar tiene_permiso("..."): se lo damos ya resuelto
        contexto["puede_crear"] = membresia.tiene_permiso("clientes.crear")
        contexto["puede_editar"] = membresia.tiene_permiso("clientes.editar")
        contexto["puede_eliminar"] = self.request.membresia.tiene_permiso("clientes.eliminar")
        return contexto


class ClienteFormMixin:
    """Configuración compartida por crear y editar (no repetir código)."""

    model = Cliente
    form_class = ClienteForm
    template_name = "core/clientes/form.html"
    success_url = reverse_lazy("clientes_lista")
    success_message = "Cliente «%(nombre)s» guardado correctamente."

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["empresa"] = self.request.empresa   # llega al __init__ del formulario
        return kwargs


class ClienteCreateView(PermisoRequeridoMixin, ClienteFormMixin, SuccessMessageMixin, CreateView):
    permiso_requerido = "clientes.crear"


class ClienteUpdateView(PermisoRequeridoMixin, ClienteFormMixin, SuccessMessageMixin, UpdateView):
    permiso_requerido = "clientes.editar"


class PerfilView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    """Permite a cualquier usuario autenticado ver su perfil, descripción y editar foto o datos."""

    form_class = PerfilUsuarioForm
    template_name = "core/perfil.html"
    success_url = reverse_lazy("perfil")
    success_message = "Tu perfil se actualizó correctamente."

    def get_object(self, queryset=None):
        return self.request.user

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["plantilla_base"] = (
            "core/base.html" if getattr(self.request, "empresa", None) else "core/tienda/base.html"
        )
        return contexto


class RecuperarContrasenaView(auth_views.PasswordResetView):
    """Solicita restablecimiento de contraseña y, solo en DEBUG=True, guarda un acceso de prueba en sesión."""

    template_name = "core/auth/password_reset_form.html"
    email_template_name = "core/auth/password_reset_email.txt"
    subject_template_name = "core/auth/password_reset_subject.txt"

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        if settings.DEBUG:
            correo = (form.cleaned_data.get("email") or "").strip()
            usuario = next(form.get_users(correo), None)
            if usuario is not None:
                uid = urlsafe_base64_encode(force_bytes(usuario.pk))
                token = default_token_generator.make_token(usuario)
                self.request.session["debug_reset_url"] = self.request.build_absolute_uri(
                    reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
                )
            else:
                self.request.session.pop("debug_reset_url", None)
        return respuesta


class RecuperarContrasenaEnviadoView(auth_views.PasswordResetDoneView):
    template_name = "core/auth/password_reset_done.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        if settings.DEBUG:
            contexto["debug_reset_url"] = self.request.session.pop("debug_reset_url", None)
        return contexto


class ClienteDeleteView(EliminarLogicoView):
    model = Cliente
    permiso_requerido = "clientes.eliminar"
    url_lista = "clientes_lista"


__all__ = [
    "DashboardView",
    "DatosNegocioView",
    "CambiarNegocioView",
    "PerfilView",
    "RecuperarContrasenaView",
    "RecuperarContrasenaEnviadoView",
    "ClienteListView",
    "ClienteFormMixin",
    "ClienteCreateView",
    "ClienteUpdateView",
    "ClienteDeleteView",
    "CategoriaListView",
    "CategoriaFormMixin",
    "CategoriaCreateView",
    "CategoriaUpdateView",
    "CategoriaDeleteView",
    "ProductoListView",
    "ProductoFormMixin",
    "ProductoCreateView",
    "ProductoUpdateView",
    "ProductoKardexView",
    "MovimientoCreateView",
    "ProductoDeleteView",
    "EliminarLogicoView",
    "FacturaListView",
    "FacturaDetailView",
    "FacturaPDFView",
    "FacturaCreateView",
    "FacturaAnularView",
    "FacturaEmitirDianView",
    "FacturaCobrarView",
    "PagoResultadoView",
    "PagoSimuladorView",
    "WompiWebhookView",
]
