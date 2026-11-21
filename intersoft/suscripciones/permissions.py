"""Permisos de Django REST Framework basados en el plan y aislamiento multi-tenant."""
from django.utils.translation import gettext, gettext_lazy
from rest_framework.permissions import BasePermission

from core.models import Membresia

from .services import crear_suscripcion_inicial


def obtener_empresa_de_request(request):
    """Obtiene la empresa activa del request garantizando aislamiento multi-tenant.

    1. Si `TenantMiddleware` ya asignó `request.empresa`, la reutiliza.
    2. Si se autentica por DRF (`force_authenticate` o token) donde el usuario se resuelve
       en la vista después del middleware, consulta su primera `Membresia` activa.
    """
    empresa = getattr(request, "empresa", None)
    if empresa is not None:
        return empresa

    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return None

    membresia = (
        Membresia.objects.select_related("empresa", "rol")
        .filter(usuario=usuario, activa=True, empresa__activa=True)
        .order_by("empresa__nombre", "empresa_id")
        .first()
    )
    if membresia is not None:
        request.empresa = membresia.empresa
        request.membresia = membresia
        return membresia.empresa
    return None


class TieneEmpresaActiva(BasePermission):
    """Exige que el usuario esté autenticado y pertenezca a una empresa activa."""

    message = gettext_lazy("Debes estar autenticado y pertenecer a una empresa activa.")

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return obtener_empresa_de_request(request) is not None


class RequiereFeature(BasePermission):
    """Permiso configurable de DRF que exige que el plan de la empresa incluya una feature.

    Uso en vistas DRF:
        permission_classes = [IsAuthenticated, RequiereFeature("pos")]
    """

    def __init__(self, feature: str):
        self.feature = feature
        self.message = {
            "code": "feature_not_available",
            "detail": gettext("Tu plan actual no incluye la funcionalidad '{feature}'.").format(feature=feature),
            "feature": feature,
        }

    def __call__(self):
        # DRF instancia cada elemento de permission_classes llamando `perm()`.
        # Al devolver `self`, `RequiereFeature("pos")` funciona tanto como clase en
        # `permission_classes = [RequiereFeature("pos")]` como instancia directa.
        return self

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        empresa = obtener_empresa_de_request(request)
        if empresa is None:
            return False
        suscripcion = getattr(empresa, "suscripcion", None) or crear_suscripcion_inicial(empresa)
        return suscripcion.puede(self.feature)


class SwaggerPermitido(BasePermission):
    """Permite Swagger/OpenAPI a cualquiera con DEBUG=True, y solo a is_staff cuando DEBUG=False."""

    def has_permission(self, request, view):
        from django.conf import settings

        if settings.DEBUG:
            return True
        return bool(request.user and request.user.is_staff)

