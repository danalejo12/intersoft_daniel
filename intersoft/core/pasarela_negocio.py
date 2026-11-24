"""Llaves de Wompi de cada negocio: formato, modo (pruebas / producción) y verificación en línea."""
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from django.views.decorators.debug import sensitive_variables

from .models import ConfiguracionPagos

logger = logging.getLogger(__name__)

API_WOMPI = {
    ConfiguracionPagos.Modo.PRUEBAS: "https://sandbox.wompi.co/v1",
    ConfiguracionPagos.Modo.PRODUCCION: "https://production.wompi.co/v1",
}
SEGUNDOS_ENTRE_VERIFICACIONES = 10
TIEMPO_ESPERA = 10

_CUERPO = r"[A-Za-z0-9_-]{8,100}"
# Formato oficial de Wompi: el prefijo dice el tipo de llave y si es de pruebas o de producción
PATRONES = {
    "llave_publica": re.compile(rf"^pub_(test|prod)_{_CUERPO}$"),
    "llave_privada": re.compile(rf"^prv_(test|prod)_{_CUERPO}$"),
    "secreto_integridad": re.compile(rf"^(test|prod)_integrity_{_CUERPO}$"),
    "secreto_eventos": re.compile(rf"^(test|prod)_events_{_CUERPO}$"),
}
EJEMPLOS = {
    "llave_publica": "pub_test_… o pub_prod_…",
    "llave_privada": "prv_test_… o prv_prod_…",
    "secreto_integridad": "test_integrity_… o prod_integrity_…",
    "secreto_eventos": "test_events_… o prod_events_…",
}


def modo_de_llave(tipo: str, valor: str) -> str | None:
    """Pruebas / producción según el prefijo, o None si el formato no es válido."""
    coincidencia = PATRONES[tipo].match(valor or "")
    if not coincidencia:
        return None
    if coincidencia.group(1) == "test":
        return ConfiguracionPagos.Modo.PRUEBAS
    return ConfiguracionPagos.Modo.PRODUCCION


@dataclass(frozen=True)
class ResultadoVerificacion:
    """Resultado de verificar las llaves de Wompi de un negocio: si sirven, el comercio y los errores."""
    ok: bool
    comercio: str = ""
    errores: tuple[str, ...] = field(default_factory=tuple)


@sensitive_variables()
def _pedir_json(url: str, encabezados: dict | None = None) -> dict:
    """Hace una petición GET a la API de Wompi y devuelve el JSON."""
    peticion = Request(url, headers={"Accept": "application/json", **(encabezados or {})})
    with urlopen(peticion, timeout=TIEMPO_ESPERA) as respuesta:
        return json.load(respuesta)


def _verificar_publica(base: str, llave: str) -> tuple[str, str | None]:
    """(nombre del comercio, error). Wompi expone el comercio de cada llave pública."""
    try:
        datos = _pedir_json(f"{base}/merchants/{quote(llave, safe='')}")["data"]
        if not isinstance(datos, dict):
            raise ValueError("Respuesta inválida")
    except HTTPError as error:
        if error.code in (401, 404, 422):
            return "", "Wompi no reconoce la llave pública."
        logger.warning("Wompi respondió %s al verificar una llave pública", error.code)
        return "", "Wompi no respondió bien. Intenta de nuevo en unos minutos."
    except (OSError, HTTPException, ValueError, KeyError, TypeError) as error:
        logger.warning("No se pudo verificar una llave pública en Wompi (%s)", type(error).__name__)
        return "", "No pudimos conectarnos con Wompi. Intenta de nuevo en unos minutos."
    nombre = str(datos.get("legal_name") or datos.get("name") or "").strip()[:200]
    return nombre, None


@sensitive_variables()
def _verificar_privada(base: str, llave: str) -> str | None:
    """Consulta una referencia que no existe: con la llave correcta responde 200 y lista vacía."""
    referencia = f"intersoft-verificacion-{uuid.uuid4().hex}"
    try:
        datos = _pedir_json(f"{base}/transactions?{urlencode({'reference': referencia})}",
                            {"Authorization": f"Bearer {llave}"})
        if not isinstance(datos, dict) or not isinstance(datos.get("data"), list):
            raise ValueError("Respuesta inválida")
    except HTTPError as error:
        if error.code in (401, 403):
            return "Wompi rechazó la llave privada."
        logger.warning("Wompi respondió %s al verificar una llave privada", error.code)
        return "Wompi no respondió bien. Intenta de nuevo en unos minutos."
    except (OSError, HTTPException, ValueError, TypeError) as error:
        logger.warning("No se pudo verificar una llave privada en Wompi (%s)", type(error).__name__)
        return "No pudimos conectarnos con Wompi. Intenta de nuevo en unos minutos."
    return None


def verificar_llaves(config: ConfiguracionPagos) -> ResultadoVerificacion:
    """Comprueba en Wompi la llave pública y, si existe, la privada.
    Los secretos de integridad y de eventos no tienen consulta: se validan por formato."""
    base = API_WOMPI[config.modo]
    comercio, error = _verificar_publica(base, config.llave_publica)
    errores = [error] if error else []
    if not errores and config.llave_privada_cifrada:
        error = _verificar_privada(base, config.llave_privada)
        if error:
            errores.append(error)
    return ResultadoVerificacion(ok=not errores, comercio=comercio, errores=tuple(errores))
