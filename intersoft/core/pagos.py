"""Lógica de pagos. El monto siempre sale de la factura, nunca del navegador."""
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Factura, Pago

logger = logging.getLogger(__name__)

ESTADOS_WOMPI = {
    "APPROVED": Pago.Estado.APROBADO,
    "DECLINED": Pago.Estado.RECHAZADO,
    "VOIDED": Pago.Estado.ANULADO,
    "ERROR": Pago.Estado.ERROR,
}


class PagoNoPermitido(Exception):
    pass


def pasarela_simulada():
    """Doble seguro: el simulador jamás funciona con DEBUG=False (producción)."""
    return settings.DEBUG and settings.PASARELA_SIMULADA


def monto_en_centavos(total):
    """Wompi recibe enteros: $3.570,00 se envía como 357000."""
    return int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calcular_firma_integridad(*, referencia, monto_centavos, moneda, secreto):
    cadena = f"{referencia}{monto_centavos}{moneda}{secreto}"
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()


@transaction.atomic
def crear_pago(*, factura):
    # Bloquea la factura para que dos peticiones no la evalúen al mismo tiempo
    factura = Factura.objects.select_for_update().get(pk=factura.pk)

    if factura.estado == Factura.Estado.ANULADA:
        raise PagoNoPermitido("No se puede cobrar una factura anulada.")
    if factura.pagos.filter(estado=Pago.Estado.APROBADO).exists():
        raise PagoNoPermitido("Esta factura ya está pagada.")

    monto = monto_en_centavos(factura.total)
    if monto <= 0:
        raise PagoNoPermitido("La factura no tiene un valor por cobrar.")

    return Pago.objects.create(
        empresa_id=factura.empresa_id,
        factura=factura,
        referencia=f"INT-{uuid.uuid4().hex}",  # Única para cada intento
        monto_centavos=monto,
        moneda="COP",
    )


def es_direccion_local(url):
    """True si la URL apunta a este computador o a una red privada.
    El firewall de Wompi rechaza (403) un checkout cuyo redirect-url es local."""
    host = urlsplit(url).hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def url_checkout(*, pago, redirect_url):
    firma = calcular_firma_integridad(
        referencia=pago.referencia,
        monto_centavos=pago.monto_centavos,
        moneda=pago.moneda,
        secreto=settings.WOMPI_INTEGRITY_SECRET,
    )
    parametros = {
        "public-key": settings.WOMPI_PUBLIC_KEY,
        "currency": pago.moneda,
        "amount-in-cents": pago.monto_centavos,
        "reference": pago.referencia,
        "signature:integrity": firma,  # La firma viaja; el secreto nunca sale del servidor
    }
    # En desarrollo (127.0.0.1) no se envía: el estado se consulta por referencia
    if not es_direccion_local(redirect_url):
        parametros["redirect-url"] = redirect_url
    return f"{settings.WOMPI_CHECKOUT_URL}?{urlencode(parametros)}"


def calcular_checksum(evento, secreto):
    """Propiedades del evento + timestamp + secreto, en SHA-256."""
    cadena = ""
    for propiedad in evento["signature"]["properties"]:  # Se leen del evento: pueden cambiar
        valor = evento["data"]
        for parte in propiedad.split("."):
            valor = valor[parte]
        cadena += str(valor)
    cadena += f"{evento['timestamp']}{secreto}"
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()


def evento_es_valido(evento, secreto):
    if not secreto:
        return False
    try:
        esperado = calcular_checksum(evento, secreto)
        recibido = str(evento["signature"]["checksum"]).lower()
    except (KeyError, TypeError):
        return False
    return hmac.compare_digest(esperado, recibido)  # Compara sin filtrar información por tiempos


@transaction.atomic
def aplicar_transaccion(transaccion):
    """Actualiza el pago. Se puede repetir el mismo evento sin causar daño (idempotente)."""
    pago = Pago.objects.filter(referencia=transaccion.get("reference")).first()
    if pago is None:
        logger.warning("Evento con referencia desconocida: %s", transaccion.get("reference"))
        return None

    # Siempre en este orden: primero la factura y luego el pago
    factura = Factura.objects.select_for_update().get(pk=pago.factura_id)
    pago = Pago.objects.select_for_update().get(pk=pago.pk)

    nuevo_estado = ESTADOS_WOMPI.get(transaccion.get("status"))
    if nuevo_estado is None:
        return pago  # Estado no final, como PENDING: esperamos el siguiente evento

    if (
        transaccion.get("amount_in_cents") != pago.monto_centavos
        or transaccion.get("currency") != pago.moneda
    ):
        logger.error("Monto o moneda no coinciden en el pago %s", pago.referencia)
        nuevo_estado = Pago.Estado.ERROR
    elif nuevo_estado == Pago.Estado.APROBADO:
        otro_aprobado = factura.pagos.filter(estado=Pago.Estado.APROBADO).exclude(pk=pago.pk).exists()
        if otro_aprobado or factura.estado == Factura.Estado.ANULADA:
            logger.critical("Cobro para revisar y reembolsar: %s", pago.referencia)
            nuevo_estado = Pago.Estado.ERROR

    # Un pago aprobado solo puede pasar a anulado; los eventos viejos no lo cambian
    if pago.estado == Pago.Estado.APROBADO and nuevo_estado != Pago.Estado.ANULADO:
        return pago

    pago.estado = nuevo_estado
    pago.wompi_transaccion_id = str(transaccion.get("id", ""))[:60]
    pago.metodo_pago = str(transaccion.get("payment_method_type") or "")[:30]
    if nuevo_estado == Pago.Estado.APROBADO:
        pago.aprobado_en = timezone.now()
    pago.save()
    return pago


def url_api_wompi():
    # Las llaves pub_test_ solo existen en Sandbox; las demás van a producción
    if settings.WOMPI_PUBLIC_KEY.startswith("pub_test_"):
        return "https://sandbox.wompi.co/v1"
    return "https://production.wompi.co/v1"


ID_TRANSACCION = re.compile(r"^[A-Za-z0-9-]{1,60}$")


def consultar_transaccion(transaccion_id):
    """Pregunta a Wompi el estado real de una transacción. Devuelve su "data" o None."""
    if not ID_TRANSACCION.match(transaccion_id or ""):
        return None
    url = f"{url_api_wompi()}/transactions/{quote(transaccion_id, safe='')}"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=10) as respuesta:
            return json.load(respuesta)["data"]
    except (URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
        logger.warning("No se pudo consultar la transacción %s en Wompi: %s", transaccion_id, error)
        return None


def buscar_transaccion_por_referencia(referencia):
    """Busca en Wompi la transacción de una referencia. Exige la llave privada,
    que solo se usa aquí, en el servidor. Devuelve la más reciente o None."""
    if not settings.WOMPI_PRIVATE_KEY:
        return None
    url = f"{url_api_wompi()}/transactions?{urlencode({'reference': referencia})}"
    peticion = Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {settings.WOMPI_PRIVATE_KEY}",
    })
    try:
        with urlopen(peticion, timeout=10) as respuesta:
            transacciones = json.load(respuesta)["data"]
    except (URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
        logger.warning("No se pudo buscar la referencia %s en Wompi: %s", referencia, error)
        return None
    if not transacciones:
        return None
    return max(transacciones, key=lambda t: t.get("created_at") or "")


def sincronizar_pago(*, pago, transaccion_id=""):
    """Respaldo del webhook: el estado se lo pedimos a Wompi.
    Del navegador solo llega, si acaso, el id; nunca el estado ni el monto."""
    if pago.estado != Pago.Estado.PENDIENTE:
        return pago
    if transaccion_id:
        transaccion = consultar_transaccion(transaccion_id)
    else:
        transaccion = buscar_transaccion_por_referencia(pago.referencia)
    # El id debe corresponder a ESTE pago: así nadie usa el id de otra transacción
    if not transaccion or transaccion.get("reference") != pago.referencia:
        return pago
    return aplicar_transaccion(transaccion) or pago


def sincronizar_pendientes(factura):
    """Pregunta a Wompi por cada pago pendiente de la factura (respaldo del webhook)."""
    if pasarela_simulada():
        return
    for pago in factura.pagos.filter(estado=Pago.Estado.PENDIENTE):
        sincronizar_pago(pago=pago)


def crear_evento_simulado(*, pago, status, secreto):
    """Construye un evento con la misma forma de transaction.updated."""
    evento = {
        "event": "transaction.updated",
        "data": {
            "transaction": {
                "id": f"SIM-{uuid.uuid4().hex[:12]}",
                "amount_in_cents": pago.monto_centavos,
                "reference": pago.referencia,
                "currency": pago.moneda,
                "payment_method_type": "SIMULADO",
                "status": status,
            }
        },
        "signature": {
            "properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"],
        },
        "timestamp": int(time.time()),
    }
    evento["signature"]["checksum"] = calcular_checksum(evento, secreto)
    return evento