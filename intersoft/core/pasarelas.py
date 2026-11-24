"""Credenciales de cobro por negocio e instantáneas de los intentos existentes."""
import json
from dataclasses import dataclass, field

from .cifrado import SecretoIlegible, cifrar, descifrar


class PasarelaNoDisponible(Exception):
    """El negocio no tiene una pasarela activa y verificada, o sus llaves no se pueden leer."""


@dataclass(frozen=True, repr=False)
class CredencialesWompi:
    """Llaves de Wompi de un negocio o de Intersoft; los secretos no aparecen al imprimir el objeto."""
    publica: str
    modo: str
    privada: str = field(repr=False)
    integridad: str = field(repr=False)
    eventos: str = field(repr=False)

    @property
    def api_url(self):
        """URL de la API de Wompi según el modo (sandbox o producción)."""
        entorno = "sandbox" if self.modo == "pruebas" else "production"
        return f"https://{entorno}.wompi.co/v1"

    def cifradas(self):
        return cifrar(json.dumps(self.__dict__))


def configuracion_activa(empresa_id):
    """Configuración de pagos activa y verificada del negocio, o None."""
    from .models import ConfiguracionPagos
    return ConfiguracionPagos.objects.filter(empresa_id=empresa_id, activa=True,
                                            verificada_en__isnull=False).first()


def credenciales_negocio(empresa_id):
    """Llaves de Wompi del negocio para cobrar; falla si no hay pasarela activa o no se pueden leer."""
    config = configuracion_activa(empresa_id)
    if config is None:
        raise PasarelaNoDisponible("Compra en línea no disponible. El negocio debe activar su pasarela.")
    try:
        return CredencialesWompi(config.llave_publica, config.modo, config.llave_privada,
                                config.secreto_integridad, config.secreto_eventos)
    except SecretoIlegible:
        raise PasarelaNoDisponible("Compra en línea no disponible. El negocio debe revisar sus llaves.") from None


def credenciales_pago(pago):
    """Llaves guardadas en el propio intento de pago (sirven aunque el negocio cambie las suyas)."""
    if not pago.credenciales_cifradas:
        raise PasarelaNoDisponible("Este intento pertenece al sistema de cobro anterior; requiere conciliación manual.")
    try:
        return CredencialesWompi(**json.loads(descifrar(pago.credenciales_cifradas)))
    except (SecretoIlegible, ValueError, TypeError):
        raise PasarelaNoDisponible("No se pudieron leer las llaves de este pago.") from None
