from django.utils.http import url_has_allowed_host_and_scheme


def destino_seguro(request):
    """Devuelve ?next= solo si apunta a este sitio; evita redirigir a páginas externas.

    Devuelve "" si no hay destino o no es seguro. Úsalo con HttpResponseRedirect, no con
    redirect(): el destino viene del usuario y no es un nombre de ruta.
    """
    destino = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return ""
