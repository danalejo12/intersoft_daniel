"""Autenticación por correo electrónico (sin distinguir mayúsculas) en lugar de nombre de usuario."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Inicia sesión con el correo sin distinguir mayúsculas."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        """Devuelve el usuario si el correo y la clave coinciden; calcula el hash aunque no exista la cuenta
        para que el tiempo de respuesta no revele qué correos están registrados.
        """
        Usuario = get_user_model()
        if username is None:
            username = kwargs.get(Usuario.USERNAME_FIELD)
        if username is None or password is None:
            return None

        usuarios = list(Usuario._default_manager.filter(email__iexact=username)[:2])
        if len(usuarios) != 1:
            # Se calcula el hash igual: así el tiempo de respuesta no revela si la cuenta existe
            Usuario().set_password(password)
            return None

        usuario = usuarios[0]
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
