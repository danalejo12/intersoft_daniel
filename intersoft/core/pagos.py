"""Lógica de pagos. El monto siempre sale de la factura, nunca del navegador."""
import hashlib
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from .models import Factura, Pago


class PagoNoPermitido(Exception):
    pass


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