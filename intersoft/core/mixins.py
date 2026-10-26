from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class TenantMixin(LoginRequiredMixin):
    """Exige login + empresa activa, y filtra todo por esa empresa."""

    def dispatch(self, request, *args, **kwargs):
        # dispatch es lo PRIMERO que se ejecuta en una vista basada en clases
        if not request.user.is_authenticated:
            return self.handle_no_permission()          # manda al login
        if request.empresa is None:
            raise PermissionDenied("No tienes una empresa activa.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # Toda consulta de la vista queda limitada a la empresa activa
        return super().get_queryset().filter(empresa=self.request.empresa)

    def form_valid(self, form):
        # Al crear o editar, la empresa la pone el servidor, NUNCA el usuario
        form.instance.empresa = self.request.empresa
        return super().form_valid(form)


class PermisoRequeridoMixin(TenantMixin):
    """Además exige que el rol tenga un permiso concreto."""

    permiso_requerido = None   # cada vista declara el suyo

    def dispatch(self, request, *args, **kwargs):
        membresia = request.membresia
        if membresia and self.permiso_requerido and not membresia.tiene_permiso(self.permiso_requerido):
            raise PermissionDenied("No tienes permiso para esta acción.")
        return super().dispatch(request, *args, **kwargs)