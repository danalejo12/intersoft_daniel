"""Cargo de la pasarela de pagos (Wompi) que se le traslada al comprador del marketplace.

Wompi descuenta de cada transacción aprobada: porcentaje + valor fijo, y sobre esa comisión, IVA.
Para que el negocio reciba completo lo que vende, el cargo se calcula "hacia arriba":

    cobrado - (cobrado * porcentaje + fijo) * (1 + IVA) = monto

y se despeja `cobrado`. El cargo es la diferencia, redondeada al peso hacia arriba.
"""
from decimal import ROUND_CEILING, Decimal

from django.conf import settings

CIEN = Decimal("100")
PESO = Decimal("1")


def _factor_iva() -> Decimal:
    return 1 + Decimal(settings.WOMPI_TARIFA_IVA) / CIEN


def cargo_pasarela(monto, *, config=None) -> Decimal:
    """Lo que se suma a `monto` para que, tras la comisión de Wompi, el negocio reciba `monto`."""
    monto = Decimal(monto)
    if monto <= 0 or config is None or not config.lista_para_cobrar or not config.cobrar_tarifa_al_comprador:
        return Decimal("0.00")
    porcentaje = config.tarifa_porcentaje / CIEN * _factor_iva()
    fijo = config.tarifa_fija * _factor_iva()
    cobrado = (monto + fijo) / (1 - porcentaje)
    return (cobrado - monto).quantize(PESO, rounding=ROUND_CEILING).quantize(Decimal("0.01"))
