from .models import Membresia


class TenantMiddleware:
    def __init__(self, get_response):
        # Django lo ejecuta UNA vez al arrancar el servidor
        self.get_response = get_response

    def __call__(self, request):
        # Esto se ejecuta en CADA petición
        request.empresa = None
        request.membresia = None

        if request.user.is_authenticated:
            membresia = (
                Membresia.objects
                .select_related("empresa", "rol")   # una sola consulta en vez de tres
                .filter(usuario=request.user, activa=True, empresa__activa=True)
                .first()
            )
            if membresia:
                request.empresa = membresia.empresa
                request.membresia = membresia

        # Deja pasar la petición hacia la vista
        return self.get_response(request)