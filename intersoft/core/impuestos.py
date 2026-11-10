"""El único lugar donde se calcula el IVA. No importa modelos para poder usarse desde ellos."""
from decimal import ROUND_HALF_UP, Decimal

CENTAVOS = Decimal("0.01")


def redondear(valor):
    """Al centavo, con la mitad hacia arriba: 0,005 se vuelve 0,01."""
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_iva(base, porcentaje):
    """IVA de una base (precio por cantidad) con un porcentaje como 19 o 5."""
    return redondear(base * porcentaje / 100)
