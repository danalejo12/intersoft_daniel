"""Saludo de bienvenida que se muestra una sola vez, justo después de iniciar sesión."""
import re

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

CLAVE_SESION = "bienvenida_nombre"


def nombre_para_saludo(usuario) -> str:
    """Nombre de pila; si no hay, el usuario; si no, lo que va antes de la @ del correo."""
    nombre = (usuario.first_name or "").strip().split(" ")[0]
    if not nombre:
        usuario_txt = (usuario.username or "").strip()
        nombre = usuario_txt if usuario_txt and "@" not in usuario_txt else (usuario.email or "").split("@")[0]
    nombre = re.sub(r"[._\-\d]+", " ", nombre).strip() or "de nuevo"
    return nombre.split(" ")[0][:30].capitalize()


@receiver(user_logged_in)
def marcar_bienvenida(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        request.session[CLAVE_SESION] = nombre_para_saludo(user)


def bienvenida(request):
    """Context processor: entrega el nombre una sola vez y lo borra de la sesión."""
    if not hasattr(request, "session") or getattr(request, "headers", {}).get("x-requested-with") == "XMLHttpRequest":
        return {}
    nombre = request.session.pop(CLAVE_SESION, None)
    return {"bienvenida_nombre": nombre} if nombre else {}
