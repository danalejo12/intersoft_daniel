"""Credenciales de cobro por negocio e instantáneas de los intentos existentes."""
from django.utils.translation import gettext
import json
from dataclasses import dataclass, field

from .cifrado import SecretoIlegible, cifrar, descifrar


class PasarelaNoDisponible(Exception):
    pass


@dataclass(frozen=True, repr=False)
class CredencialesWompi:
    publica: str
    modo: str
    privada: str = field(repr=False)
    integridad: str = field(repr=False)
    eventos: str = field(repr=False)

    @property
    def api_url(self):
        entorno = "sandbox" if self.modo == "pruebas" else "production"
        return f"https://{entorno}.wompi.co/v1"

    def cifradas(self):
        return cifrar(json.dumps(self.__dict__))


def configuracion_activa(empresa_id):
    from .models import ConfiguracionPagos
    return ConfiguracionPagos.objects.filter(empresa_id=empresa_id, activa=True,
                                            verificada_en__isnull=False).first()


def credenciales_negocio(empresa_id):
    config = configuracion_activa(empresa_id)
    if config is None:
        raise PasarelaNoDisponible(gettext("Compra en línea no disponible. El negocio debe activar su pasarela."))
    try:
        return CredencialesWompi(config.llave_publica, config.modo, config.llave_privada,
                                config.secreto_integridad, config.secreto_eventos)
    except SecretoIlegible:
        raise PasarelaNoDisponible(gettext("Compra en línea no disponible. El negocio debe revisar sus llaves.")) from None


def credenciales_pago(pago):
    if not pago.credenciales_cifradas:
        raise PasarelaNoDisponible(gettext("Este intento pertenece al sistema de cobro anterior; requiere conciliación manual."))
    try:
        return CredencialesWompi(**json.loads(descifrar(pago.credenciales_cifradas)))
    except (SecretoIlegible, ValueError, TypeError):
        raise PasarelaNoDisponible(gettext("No se pudieron leer las llaves de este pago.")) from None
