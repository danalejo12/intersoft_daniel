"""Cifrado en reposo de los secretos de pago de cada negocio.

Las llaves viven en PAGOS_CLAVES_CIFRADO (.env), separadas por comas: la primera cifra,
todas descifran. Para rotar, se pone la nueva primero y se ejecuta `rotar_secretos_pago`.
Sin esa variable se deriva una clave de SECRET_KEY y el chequeo de despliegue avisa.
"""
import base64
import hashlib
import re
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.checks import Warning, register
from django.core.exceptions import ImproperlyConfigured
from django.views.debug import SafeExceptionReporterFilter
from django.views.decorators.debug import sensitive_variables

CONTEXTO_DERIVACION = b"intersoft:pagos:v1:"


class SecretoIlegible(Exception):
    """El texto cifrado no corresponde a ninguna de las claves configuradas."""


class FiltroSecretosPago(SafeExceptionReporterFilter):
    # Django no reconoce «CLAVES» como secreto en los reportes de excepción.
    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern + r"|CIFRAD[OA]|CLAVES", re.IGNORECASE,
    )


def _claves_configuradas() -> tuple[str, ...]:
    crudo = getattr(settings, "PAGOS_CLAVES_CIFRADO", "") or ""
    return tuple(c.strip() for c in crudo.split(",") if c.strip())


@lru_cache(maxsize=8)
@sensitive_variables()
def _cifrador(claves: tuple[str, ...], secret_key: str) -> MultiFernet:
    if not claves:
        derivada = hashlib.sha256(CONTEXTO_DERIVACION + secret_key.encode()).digest()
        claves = (base64.urlsafe_b64encode(derivada).decode(),)
    try:
        return MultiFernet([Fernet(c.encode()) for c in claves])
    except (ValueError, TypeError) as error:
        raise ImproperlyConfigured(
            "PAGOS_CLAVES_CIFRADO tiene una clave inválida. Genera una con "
            "Fernet.generate_key()."
        ) from error


def cifrador() -> MultiFernet:
    return _cifrador(_claves_configuradas(), settings.SECRET_KEY)


@sensitive_variables()
def cifrar(texto: str) -> str:
    if not texto:
        return ""
    return cifrador().encrypt(texto.encode()).decode()


@sensitive_variables()
def descifrar(token: str) -> str:
    if not token:
        return ""
    try:
        return cifrador().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise SecretoIlegible("No se pudo descifrar el secreto de pago.") from error


@sensitive_variables()
def recifrar(token: str, *, incluir_clave_derivada=False) -> str:
    """Vuelve a cifrar con la clave principal (rotación)."""
    if not token:
        return ""
    actual = cifrador()
    if incluir_clave_derivada:
        if not _claves_configuradas():
            raise ImproperlyConfigured("Configura la nueva PAGOS_CLAVES_CIFRADO antes de migrar el cifrado.")
        derivada = base64.urlsafe_b64encode(hashlib.sha256(
            CONTEXTO_DERIVACION + settings.SECRET_KEY.encode()).digest()).decode()
        actual = _cifrador((*_claves_configuradas(), derivada), settings.SECRET_KEY)
    try:
        return actual.rotate(token.encode()).decode()
    except InvalidToken as error:
        raise SecretoIlegible("No se pudo recifrar el secreto de pago.") from error


@register(deploy=True)
def revisar_clave_de_cifrado(app_configs, **kwargs):
    if _claves_configuradas():
        return []
    return [Warning(
        "PAGOS_CLAVES_CIFRADO no está configurada: los secretos de pago se cifran con una "
        "clave derivada de SECRET_KEY y quedarían ilegibles si esta cambia.",
        hint="Genera una clave con Fernet.generate_key() y ponla en el .env.",
        id="core.W001",
    )]
