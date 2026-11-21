"""Lógica de pagos. El monto siempre sale de la factura, nunca del navegador."""
from django.utils.translation import gettext
import datetime as dt
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import time
import uuid
from decimal import ROUND_HALF_UP, Decimal
from http.client import HTTPException
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from . import reservas
from .models import Factura, Pago, Pedido
from .pasarelas import PasarelaNoDisponible, credenciales_negocio, credenciales_pago

logger = logging.getLogger(__name__)

ESTADOS_WOMPI = {
    "APPROVED": Pago.Estado.APROBADO,
    "DECLINED": Pago.Estado.RECHAZADO,
    "VOIDED": Pago.Estado.ANULADO,
    "ERROR": Pago.Estado.ERROR,
}


class PagoNoPermitido(Exception):
    pass


class WompiNoResponde(Exception):
    """Falló la consulta: no se sabe si la transacción existe."""


class ResultadoWompi:
    APROBADO = "aprobado"
    EN_PROCESO = "en_proceso"  # Wompi la tiene en PENDING
    LIBRE = "libre"            # ningún intento sigue vivo en Wompi
    SIN_RESPUESTA = "sin_respuesta"


def pasarela_simulada():
    """Doble seguro: el simulador jamás funciona con DEBUG=False (producción)."""
    return settings.DEBUG and settings.PASARELA_SIMULADA


def monto_en_centavos(total):
    """Wompi recibe enteros: $3.570,00 se envía como 357000."""
    return int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@sensitive_variables()
def calcular_firma_integridad(*, referencia, monto_centavos, moneda, secreto, expiracion=""):
    # Orden de la documentación de Wompi; la expiración solo va cuando se envía en el checkout
    cadena = f"{referencia}{monto_centavos}{moneda}{expiracion}{secreto}"
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()


def formato_expiracion(fecha):
    """ISO 8601 en UTC, como el ejemplo de Wompi: 2023-06-09T20:28:50.000Z."""
    return fecha.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@transaction.atomic
def crear_pago(*, factura):
    # Bloquea la factura para que dos peticiones no la evalúen al mismo tiempo
    factura = Factura.objects.select_for_update().get(pk=factura.pk)

    if factura.estado == Factura.Estado.ANULADA:
        raise PagoNoPermitido(gettext("No se puede cobrar una factura anulada."))
    if factura.esta_pagada:
        raise PagoNoPermitido(gettext("Esta factura ya está pagada."))
    if hasattr(factura, "cuentacartera"):
        raise PagoNoPermitido(
            gettext("Esta factura ya se gestiona en cartera; registra sus abonos en Tesorería.")
        )

    monto = monto_en_centavos(factura.total)
    if monto <= 0:
        raise PagoNoPermitido(gettext("La factura no tiene un valor por cobrar."))

    try:
        credenciales = _credenciales_nuevas(factura.empresa_id)
    except PagoNoPermitido:
        if not pasarela_simulada():
            raise
        credenciales = ""

    return Pago.objects.create(
        empresa_id=factura.empresa_id,
        factura=factura,
        referencia=f"INT-{uuid.uuid4().hex}",  # Única para cada intento
        monto_centavos=monto,
        moneda="COP",
        credenciales_cifradas=credenciales,
        pasarela_propia=True,
    )


def crear_pago_pedido(*, pedido):
    """Intento de pago de un pedido. El monto siempre sale de pedido.total."""
    with transaction.atomic():
        pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if not pedido.pago_directo:
            raise PagoNoPermitido(gettext("Este pedido usa el cobro anterior. Crea un pedido nuevo para pagar al negocio."))
        if pedido.estado != Pedido.Estado.PENDIENTE:
            raise PagoNoPermitido(gettext("Este pedido ya no se puede pagar."))
        if pedido.expira_en > timezone.now():
            if pedido.necesita_renovar:
                raise PagoNoPermitido(gettext("A tu reserva le quedan muy pocos minutos. Renuévala para pagar con calma."))
            monto = monto_en_centavos(pedido.total)
            if monto <= 0:
                raise PagoNoPermitido(gettext("El pedido no tiene un valor por cobrar."))
            return Pago.objects.create(
                empresa_id=pedido.empresa_id,
                pedido=pedido,
                referencia=f"INT-{uuid.uuid4().hex}",
                monto_centavos=monto,
                moneda="COP",
                credenciales_cifradas=_credenciales_nuevas(pedido.empresa_id),
                pasarela_propia=True,
            )
        # Fuera del if: la liberación debe guardarse, así que el error se lanza al cerrar la transacción
        reservas.liberar_pedido(pedido, Pedido.Estado.VENCIDO)
    raise PagoNoPermitido(gettext("Tu reserva venció y liberamos los productos."))


def _credenciales_nuevas(empresa_id):
    try:
        return credenciales_negocio(empresa_id).cifradas()
    except PasarelaNoDisponible as error:
        raise PagoNoPermitido(str(error)) from None


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
    try:
        llaves = credenciales_pago(pago)
    except PasarelaNoDisponible as error:
        raise PagoNoPermitido(str(error)) from None
    # Un solo texto para la URL y la firma: un carácter distinto daría "firma inválida"
    expiracion = formato_expiracion(pago.pedido.expira_en) if pago.pedido_id else ""
    firma = calcular_firma_integridad(
        referencia=pago.referencia,
        monto_centavos=pago.monto_centavos,
        moneda=pago.moneda,
        secreto=llaves.integridad,
        expiracion=expiracion,
    )
    parametros = {
        "public-key": llaves.publica,
        "currency": pago.moneda,
        "amount-in-cents": pago.monto_centavos,
        "reference": pago.referencia,
        "signature:integrity": firma,  # La firma viaja; el secreto nunca sale del servidor
    }
    if expiracion:
        parametros["expiration-time"] = expiracion
    # En desarrollo (127.0.0.1) no se envía: el estado se consulta por referencia
    if not es_direccion_local(redirect_url):
        parametros["redirect-url"] = redirect_url
    return f"{settings.WOMPI_CHECKOUT_URL}?{urlencode(parametros)}"


@sensitive_variables()
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
        propiedades = evento["signature"]["properties"]
        if not isinstance(propiedades, list) or not all(isinstance(p, str) for p in propiedades):
            return False
        obligatorias = {"transaction.id", "transaction.status", "transaction.amount_in_cents"}
        if not obligatorias.issubset(propiedades):
            return False
        esperado = calcular_checksum(evento, secreto)
        recibido = str(evento["signature"]["checksum"]).lower()
    except (KeyError, TypeError, IndexError, AttributeError, UnicodeError):
        return False
    try:
        return hmac.compare_digest(esperado, recibido)
    except TypeError:
        return False


def _guardar_resultado(pago, nuevo_estado, transaccion):
    pago.estado = nuevo_estado
    pago.wompi_transaccion_id = str(transaccion.get("id", ""))[:60]
    pago.metodo_pago = str(transaccion.get("payment_method_type") or "")[:30]
    if nuevo_estado == Pago.Estado.APROBADO:
        pago.aprobado_en = timezone.now()
    pago.save()


def _aplicar_en_pedido(pago, transaccion):
    # Siempre en este orden: primero el pedido y luego el pago
    pedido = Pedido.objects.select_for_update().get(pk=pago.pedido_id)
    pago = Pago.objects.select_for_update().get(pk=pago.pk)

    nuevo_estado = ESTADOS_WOMPI.get(transaccion.get("status"))
    if nuevo_estado is None:
        return pago  # Estado no final, como PENDING: esperamos el siguiente evento
    # Va primero: un evento repetido no debe crear otra factura ni mover stock
    if pago.estado == Pago.Estado.APROBADO and nuevo_estado != Pago.Estado.ANULADO:
        return pago

    aprobado = nuevo_estado == Pago.Estado.APROBADO
    if (
        transaccion.get("amount_in_cents") != pago.monto_centavos
        or transaccion.get("currency") != pago.moneda
    ):
        logger.critical("Monto o moneda no coinciden en el pago %s", pago.referencia)
        _guardar_resultado(pago, Pago.Estado.ERROR, transaccion)
        if aprobado:
            reservas.registrar_monto_invalido(pedido)
        return pago

    if aprobado and pedido.pagos.filter(estado=Pago.Estado.APROBADO).exclude(pk=pago.pk).exists():
        logger.critical("Cobro duplicado para revisar y reembolsar: %s", pago.referencia)
        _guardar_resultado(pago, Pago.Estado.ERROR, transaccion)
        return pago

    if pago.estado == Pago.Estado.APROBADO:
        logger.critical("Wompi anuló el pago aprobado %s del pedido %s", pago.referencia, pedido.numero)
    _guardar_resultado(pago, nuevo_estado, transaccion)
    if aprobado:
        reservas.registrar_pago_aprobado(pedido)
    return pago


@transaction.atomic
def aplicar_transaccion(transaccion, *, empresa_id=None):
    """Actualiza el pago. Se puede repetir el mismo evento sin causar daño (idempotente)."""
    if not isinstance(transaccion, dict):
        return None
    pagos = Pago.objects.filter(referencia=transaccion.get("reference"))
    if empresa_id is not None:
        pagos = pagos.filter(empresa_id=empresa_id)
    pago = pagos.first()
    if pago is None:
        logger.warning("Evento con referencia desconocida: %s", transaccion.get("reference"))
        return None
    if pago.pedido_id:
        return _aplicar_en_pedido(pago, transaccion)

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

    _guardar_resultado(pago, nuevo_estado, transaccion)
    if nuevo_estado == Pago.Estado.APROBADO:
        from .contabilidad_automatica import contabilizar_recaudo_factura
        from .models import AsientoContable

        if AsientoContable.objects.filter(empresa_id=factura.empresa_id, referencia=f"FACT-{factura.numero}").exists():
            contabilizar_recaudo_factura(
                factura=factura,
                monto=factura.total,
                referencia_pago=pago.referencia,
                usuario=factura.creada_por,
            )
    return pago


def url_api_wompi(llaves):
    return llaves.api_url


ID_TRANSACCION = re.compile(r"^[A-Za-z0-9-]{1,60}$")


def consultar_transaccion(transaccion_id, *, llaves):
    """Pregunta a Wompi el estado real de una transacción. Devuelve su "data" o None."""
    if not isinstance(transaccion_id, str) or not ID_TRANSACCION.fullmatch(transaccion_id):
        return None
    url = f"{url_api_wompi(llaves)}/transactions/{quote(transaccion_id, safe='')}"
    try:
        with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=10) as respuesta:
            datos = json.load(respuesta)["data"]
            return datos if isinstance(datos, dict) else None
    except (OSError, HTTPException, ValueError, KeyError, TypeError) as error:
        logger.warning("No se pudo consultar la transacción %s en Wompi (%s)", transaccion_id, type(error).__name__)
        return None


@sensitive_variables()
def buscar_transaccion_por_referencia(referencia, *, llaves):
    """Busca en Wompi la transacción de una referencia. Exige la llave privada,
    que solo se usa aquí, en el servidor. Devuelve la más reciente, o None si no existe.
    Lanza WompiNoResponde si la consulta falla: no es lo mismo que "no existe"."""
    if not llaves.privada:
        return None
    url = f"{url_api_wompi(llaves)}/transactions?{urlencode({'reference': referencia})}"
    peticion = Request(url, headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {llaves.privada}",
    })
    try:
        with urlopen(peticion, timeout=10) as respuesta:
            transacciones = json.load(respuesta)["data"]
            if not isinstance(transacciones, list) or not all(isinstance(t, dict) for t in transacciones):
                raise ValueError(gettext("Respuesta inválida"))
    except (OSError, HTTPException, ValueError, KeyError, TypeError) as error:
        logger.warning("No se pudo buscar la referencia %s en Wompi (%s)", referencia, type(error).__name__)
        raise WompiNoResponde from error
    if not transacciones:
        return None
    return max(transacciones, key=lambda t: t.get("created_at") or "")


ESPERA_ENTRE_CONSULTAS = dt.timedelta(seconds=10)


def _tomar_turno_de_consulta(pago):
    """True si pasaron 10 s desde la última consulta. El UPDATE condicional es atómico:
    si dos peticiones llegan a la vez, solo una consulta a Wompi."""
    ahora = timezone.now()
    return bool(
        Pago.objects.filter(pk=pago.pk)
        .filter(Q(consultado_en__isnull=True) | Q(consultado_en__lte=ahora - ESPERA_ENTRE_CONSULTAS))
        .update(consultado_en=ahora)
    )


def sincronizar_pago(*, pago, transaccion_id="", forzar=False):
    """Respaldo del webhook: el estado se lo pedimos a Wompi.
    Del navegador solo llega, si acaso, el id; nunca el estado ni el monto.

    En las páginas que se recargan (forzar=False) no se consulta más de una vez cada 10 s y,
    mientras tanto, se responde con lo guardado. Antes de cobrar se usa forzar=True."""
    if pago.estado != Pago.Estado.PENDIENTE:
        return pago
    try:
        llaves = credenciales_pago(pago)
    except PasarelaNoDisponible:
        return pago
    if forzar:
        Pago.objects.filter(pk=pago.pk).update(consultado_en=timezone.now())
    elif not _tomar_turno_de_consulta(pago):
        return pago
    # El GET público por ID no demuestra quién recibió el dinero. El retorno del
    # comprador solo se concilia con una consulta autenticada al comercio correcto.
    if not llaves.privada:
        return pago
    try:
        transaccion = buscar_transaccion_por_referencia(pago.referencia, llaves=llaves)
    except WompiNoResponde:
        return pago
    # El id debe corresponder a ESTE pago: así nadie usa el id de otra transacción
    if not transaccion or transaccion.get("reference") != pago.referencia:
        return pago
    if transaccion_id and transaccion.get("id") != transaccion_id:
        return pago
    return aplicar_transaccion(transaccion, empresa_id=pago.empresa_id) or pago


def revisar_en_wompi(pedido):
    """Consulta los intentos sin respuesta del pedido, aplica lo que Wompi diga y resume el resultado."""
    if pedido.pagos.filter(estado=Pago.Estado.APROBADO).exists():
        return ResultadoWompi.APROBADO
    pendientes = list(pedido.pagos.filter(estado=Pago.Estado.PENDIENTE))
    if not pendientes:
        return ResultadoWompi.LIBRE
    resultado = ResultadoWompi.LIBRE
    for pago in pendientes:
        try:
            llaves = credenciales_pago(pago)
            if not llaves.privada:
                raise PasarelaNoDisponible
            transaccion = buscar_transaccion_por_referencia(pago.referencia, llaves=llaves)
        except (WompiNoResponde, PasarelaNoDisponible):
            if resultado == ResultadoWompi.LIBRE:
                resultado = ResultadoWompi.SIN_RESPUESTA
            continue
        # None: el intento nunca llegó a Wompi (por ejemplo, cerraron la pestaña sin pagar)
        if not transaccion or transaccion.get("reference") != pago.referencia:
            continue
        aplicar_transaccion(transaccion, empresa_id=pago.empresa_id)
        if transaccion.get("status") == "APPROVED":
            return ResultadoWompi.APROBADO
        if transaccion.get("status") == "PENDING":
            resultado = ResultadoWompi.EN_PROCESO
    return resultado


def sincronizar_pendientes(factura, forzar=False):
    """Pregunta a Wompi por cada pago pendiente de la factura (respaldo del webhook)."""
    if pasarela_simulada():
        return
    for pago in factura.pagos.filter(estado=Pago.Estado.PENDIENTE):
        sincronizar_pago(pago=pago, forzar=forzar)


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
