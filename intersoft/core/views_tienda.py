"""Vistas públicas del marketplace y registro de cuentas y negocios."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView

from .forms_tienda import RegistroCompradorForm, RegistroNegocioForm
from .marketplace import empresas_publicas, negocios_con_productos, productos_publicos
from .negocios import registrar_negocio
from .redirecciones import destino_seguro


class MarketplaceView(ListView):
    template_name = "core/tienda/inicio.html"
    context_object_name = "productos"
    paginate_by = 24

    def get_queryset(self):
        self.q = self.request.GET.get("q", "").strip()
        productos = productos_publicos()
        if self.q:
            productos = productos.filter(
                Q(nombre__icontains=self.q) | Q(empresa__nombre__icontains=self.q)
            )
        return productos

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["q"] = self.q
        contexto["negocios"] = negocios_con_productos()
        return contexto


class TiendaNegocioView(ListView):
    template_name = "core/tienda/negocio.html"
    context_object_name = "productos"
    paginate_by = 24

    def get_queryset(self):
        self.negocio = get_object_or_404(empresas_publicas(), slug=self.kwargs["slug"])
        return productos_publicos().filter(empresa=self.negocio)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["negocio"] = self.negocio
        return contexto


class ProductoPublicoView(DetailView):
    template_name = "core/tienda/producto.html"
    context_object_name = "producto"

    def get_queryset(self):
        return productos_publicos()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        comentarios = self.object.comentarios.select_related("autor")
        contexto["comentarios"] = comentarios[:30]
        contexto["opiniones"] = comentarios.aggregate(promedio=Avg("calificacion"), total=Count("id"))
        if self.request.user.is_authenticated:
            contexto["mi_comentario"] = comentarios.filter(autor=self.request.user).first()
        return contexto


class RegistroCompradorView(FormView):
    template_name = "core/tienda/registro.html"
    form_class = RegistroCompradorForm

    def _ir_al_destino(self):
        # HttpResponseRedirect y no redirect(): el destino viene del usuario y no es un nombre de ruta
        return HttpResponseRedirect(destino_seguro(self.request) or reverse("marketplace"))

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return self._ir_al_destino()
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Con django-axes hay dos backends: se indica el que de verdad autentica
        login(self.request, form.save(), backend="core.backends.EmailBackend")
        return self._ir_al_destino()

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["next"] = destino_seguro(self.request)
        return contexto


class RegistrarNegocioView(LoginRequiredMixin, FormView):
    login_url = "registro"
    template_name = "core/tienda/registrar_negocio.html"
    form_class = RegistroNegocioForm

    def form_valid(self, form):
        empresa = registrar_negocio(usuario=self.request.user, datos=form.cleaned_data)
        self.request.session["empresa_id"] = str(empresa.pk)  # la sesión solo guarda texto, no UUID
        messages.success(self.request, f"¡Listo! {empresa.nombre} ya está registrado.")
        return redirect("dashboard")


def despues_de_login(request):
    return redirect("dashboard" if request.empresa else "marketplace")
