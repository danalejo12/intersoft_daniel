"""Vistas del panel para gestionar el equipo (membresías) y los roles/permisos del negocio."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .forms_equipo import MiembroCrearForm, MiembroEditarForm, RolForm
from .mixins import TenantMixin
from .models import Membresia, Rol
from .permisos import sincronizar_catalogo_permisos


def _puede_ver_equipo(membresia):
    """Indica si la membresía puede ver el equipo."""
    if not membresia:
        return False
    return any(
        membresia.tiene_permiso(p)
        for p in ("equipo.ver", "equipo.gestionar", "negocio.editar")
    )


def _puede_gestionar_equipo(membresia):
    """Indica si la membresía puede gestionar el equipo."""
    if not membresia:
        return False
    return any(
        membresia.tiene_permiso(p)
        for p in ("equipo.gestionar", "negocio.editar")
    )


class EquipoVerMixin(TenantMixin):
    """Exige poder ver el equipo (equipo.ver, equipo.gestionar o negocio.editar)."""
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.membresia and not _puede_ver_equipo(request.membresia):
            raise PermissionDenied("No tienes permiso para ver el equipo.")
        return super().dispatch(request, *args, **kwargs)


class EquipoGestionarMixin(TenantMixin):
    """Exige poder gestionar el equipo (equipo.gestionar o negocio.editar)."""
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.membresia and not _puede_gestionar_equipo(request.membresia):
            raise PermissionDenied("No tienes permiso para gestionar el equipo y los roles.")
        return super().dispatch(request, *args, **kwargs)


class EquipoView(EquipoVerMixin, View):
    """Lista los miembros del equipo y los roles del negocio. Ruta: `/panel/equipo/` («equipo_lista»)."""
    template_name = "core/equipo/lista.html"

    def get(self, request):
        sincronizar_catalogo_permisos()
        empresa = request.empresa
        membresias = (
            Membresia.objects.filter(empresa=empresa)
            .select_related("usuario", "rol")
            .order_by("-activa", "-rol__es_admin", "usuario__email")
        )
        roles = (
            Rol.objects.de_empresa(empresa)
            .prefetch_related("permisos")
            .annotate(total_miembros=Count("membresias"))
            .order_by("-es_admin", "nombre")
        )
        return render(
            request,
            self.template_name,
            {
                "membresias": membresias,
                "roles": roles,
                "puede_gestionar": _puede_gestionar_equipo(request.membresia),
            },
        )


class MiembroCreateView(EquipoGestionarMixin, View):
    """Agrega un miembro al equipo (cuenta nueva o existente), respetando el límite de usuarios del plan. Ruta:
    `/panel/equipo/miembros/nuevo/` («equipo_miembro_crear»).
    """
    template_name = "core/equipo/miembro_form.html"

    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and getattr(request, "empresa", None) is not None
            and request.membresia
            and request.membresia.tiene_permiso("equipo.gestionar")
        ):
            from suscripciones.exceptions import LimitePlanExcedido, verificar_limite

            try:
                verificar_limite(request.empresa, "usuarios")
            except LimitePlanExcedido as exc:
                messages.error(
                    request,
                    f"Alcanzaste el límite de {exc.limite} usuarios activos de tu plan ({exc.plan_actual}). "
                    "Mejora tu plan para agregar más miembros al equipo.",
                )
                return redirect("suscripcion_panel")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = MiembroCrearForm(empresa=request.empresa)
        return render(request, self.template_name, {"form": form, "es_nuevo": True})

    def post(self, request):
        form = MiembroCrearForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            membresia = form.guardar()
            messages.success(
                request,
                f"Agregaste a {membresia.usuario.email} con el rol {membresia.rol.nombre}.",
            )
            return redirect("equipo_lista")
        return render(request, self.template_name, {"form": form, "es_nuevo": True})


class MiembroUpdateView(EquipoGestionarMixin, View):
    """Cambia el rol o el estado de un miembro sin dejar al negocio sin administrador. Ruta:
    `/panel/equipo/miembros/<uuid:pk>/editar/` («equipo_miembro_editar»).
    """
    template_name = "core/equipo/miembro_form.html"

    def obtener(self, request, pk):
        return get_object_or_404(
            Membresia.objects.filter(empresa=request.empresa).select_related("usuario", "rol"),
            pk=pk,
        )

    def get(self, request, pk):
        membresia = self.obtener(request, pk)
        form = MiembroEditarForm(instance=membresia, empresa=request.empresa)
        return render(
            request,
            self.template_name,
            {"form": form, "membresia": membresia, "es_nuevo": False},
        )

    def post(self, request, pk):
        membresia = self.obtener(request, pk)
        form = MiembroEditarForm(request.POST, instance=membresia, empresa=request.empresa)
        if form.is_valid():
            form.save()
            messages.success(request, f"Actualizaste la membresía de {membresia.usuario.email}.")
            return redirect("equipo_lista")
        return render(
            request,
            self.template_name,
            {"form": form, "membresia": membresia, "es_nuevo": False},
        )


class RolCreateView(EquipoGestionarMixin, View):
    """Crea un rol con su conjunto de permisos. Ruta: `/panel/equipo/roles/nuevo/` («equipo_rol_crear»)."""
    template_name = "core/equipo/rol_form.html"

    def get(self, request):
        form = RolForm(empresa=request.empresa)
        return render(request, self.template_name, {"form": form, "es_nuevo": True})

    def post(self, request):
        form = RolForm(request.POST, empresa=request.empresa)
        if form.is_valid():
            rol = form.save()
            messages.success(request, f"Rol «{rol.nombre}» creado correctamente.")
            return redirect("equipo_lista")
        return render(request, self.template_name, {"form": form, "es_nuevo": True})


class RolUpdateView(EquipoGestionarMixin, View):
    """Edita el nombre y los permisos de un rol. Ruta: `/panel/equipo/roles/<uuid:pk>/editar/`
    («equipo_rol_editar»).
    """
    template_name = "core/equipo/rol_form.html"

    def obtener(self, request, pk):
        return get_object_or_404(Rol.objects.de_empresa(request.empresa), pk=pk)

    def get(self, request, pk):
        rol = self.obtener(request, pk)
        form = RolForm(instance=rol, empresa=request.empresa)
        return render(
            request,
            self.template_name,
            {"form": form, "rol": rol, "es_nuevo": False},
        )

    def post(self, request, pk):
        rol = self.obtener(request, pk)
        form = RolForm(request.POST, instance=rol, empresa=request.empresa)
        if form.is_valid():
            rol = form.save()
            messages.success(request, f"Rol «{rol.nombre}» actualizado.")
            return redirect("equipo_lista")
        return render(
            request,
            self.template_name,
            {"form": form, "rol": rol, "es_nuevo": False},
        )


class RolDeleteView(EquipoGestionarMixin, View):
    """Eliminación lógica: desactiva sin borrar. Ruta: `/panel/equipo/roles/<uuid:pk>/eliminar/`
    («equipo_rol_eliminar»).
    """
    http_method_names = ["post"]

    def post(self, request, pk):
        rol = get_object_or_404(Rol.objects.de_empresa(request.empresa), pk=pk)
        if rol.membresias.exists():
            messages.error(
                request,
                f"No puedes eliminar el rol «{rol.nombre}» porque tiene miembros asignados.",
            )
            return redirect("equipo_lista")
        nombre = rol.nombre
        rol.delete()
        messages.success(request, f"Rol «{nombre}» eliminado.")
        return redirect("equipo_lista")
