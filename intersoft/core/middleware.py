from django.core.exceptions import ValidationError

from .models import Membresia


class TenantMiddleware:
    def __init__(self, get_response):
        # Django lo ejecuta UNA vez al arrancar el servidor
        self.get_response = get_response

    def __call__(self, request):
        # Esto se ejecuta en CADA petición
        request.empresa = None
        request.membresia = None
        request.membresias_activas = []

        if request.user.is_authenticated:
            membresia = self._membresia_activa(request)
            if membresia:
                request.empresa = membresia.empresa
                request.membresia = membresia

        # Deja pasar la petición hacia la vista
        return self.get_response(request)

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
