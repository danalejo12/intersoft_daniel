"""Mixins de control de acceso por rol interno para /plataforma/."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import RolPlataforma


class PlataformaMixin(LoginRequiredMixin):
    """Exige usuario autenticado con is_staff=True, RolPlataforma activo, permiso requerido y 2FA TOTP."""

    permiso = ""
    requiere_totp = True

    @classmethod
    def con_permiso(cls, permiso: str):
        """Permite declarar `PlataformaMixin.con_permiso('finanzas')` si se requiere un mixin parametrizado."""
        return type(f"Plataforma_{permiso}_Mixin", (cls,), {"permiso": permiso})

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            raise PermissionDenied("Acceso exclusivo para personal de la plataforma.")

        rol_plataforma = (
            RolPlataforma.objects.filter(usuario=request.user, activo=True).first()
        )
        if rol_plataforma is None:
            raise PermissionDenied("No tienes un rol interno asignado en la plataforma.")

        permiso_req = getattr(self, "permiso_plataforma", "") or self.permiso
        if permiso_req and not rol_plataforma.tiene_permiso(permiso_req):
            raise PermissionDenied("Tu rol interno no tiene permiso para esta sección.")

        request.rol_plataforma = rol_plataforma
        if self.requiere_totp and request.session.get("plataforma_totp_verificado") != str(request.user.pk):
            return redirect("plataforma_totp")
        return super().dispatch(request, *args, **kwargs)
