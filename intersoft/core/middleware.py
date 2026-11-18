from django.core.exceptions import PermissionDenied

from .models import Empresa, Membresia


class _RolSoporteVirtual:
    nombre = "Soporte InterSoft"
    es_admin = True


class _MembresiaSoporteVirtual:
    """Membresía virtual de solo sesión para que el equipo de soporte navegue el /panel/ de una empresa."""

    def __init__(self, empresa):
        self.empresa = empresa
        self.empresa_id = empresa.id
        self.rol = _RolSoporteVirtual()

    def tiene_permiso(self, _codigo: str) -> bool:
        return True


class TenantMiddleware:
    def __init__(self, get_response):
        # Django lo ejecuta UNA vez al arrancar el servidor
        self.get_response = get_response

    def __call__(self, request):
        # Esto se ejecuta en CADA petición
        request.empresa = None
        request.membresia = None
        request.membresias_activas = []
        request.modo_soporte = False
        request.soporte_solo_lectura = False

        if request.user.is_authenticated:
            if self._aplicar_modo_soporte(request):
                if (
                    request.soporte_solo_lectura
                    and request.path.startswith("/panel/")
                    and request.method not in ("GET", "HEAD", "OPTIONS")
                ):
                    raise PermissionDenied(
                        "Modo soporte de solo lectura: no se permiten cambios en este negocio."
                    )
            else:
                membresia = self._membresia_activa(request)
                if membresia:
                    request.empresa = membresia.empresa
                    request.membresia = membresia

        # Deja pasar la petición hacia la vista
        return self.get_response(request)

    def _aplicar_modo_soporte(self, request) -> bool:
        soporte_ctx = request.session.get("plataforma_soporte")
        if not soporte_ctx:
            return False
        if not request.user.is_staff:
            request.session.pop("plataforma_soporte", None)
            return False

        from plataforma.models import RolPlataforma

        rol_interno = RolPlataforma.objects.filter(
            usuario=request.user,
            activo=True,
            rol__in=(RolPlataforma.Rol.DUENO, RolPlataforma.Rol.SOPORTE),
        ).first()
        if rol_interno is None:
            request.session.pop("plataforma_soporte", None)
            return False

        empresa = Empresa.objects.filter(pk=soporte_ctx.get("empresa_id")).first()
        if empresa is None:
            request.session.pop("plataforma_soporte", None)
            return False

        request.empresa = empresa
        request.membresia = _MembresiaSoporteVirtual(empresa)
        request.modo_soporte = True
        request.soporte_solo_lectura = bool(soporte_ctx.get("solo_lectura", True))
        return True

    def _membresia_activa(self, request):
        # Siempre se parte de las membresías del usuario: la sesión nunca da acceso a una empresa ajena
        membresias = list(
            Membresia.objects
            .select_related("empresa", "rol")   # una sola consulta en vez de tres
            .filter(usuario=request.user, activa=True, empresa__activa=True)
            .order_by("empresa__nombre", "empresa_id")
        )
        request.membresias_activas = membresias
        if not membresias:
            return None

        empresa_id = request.session.get("empresa_id")
        if empresa_id:
            empresa_id_str = str(empresa_id)
            for m in membresias:
                if str(m.empresa_id) == empresa_id_str:
                    return m

        membresia = membresias[0]
        request.session["empresa_id"] = str(membresia.empresa_id)
        return membresia
