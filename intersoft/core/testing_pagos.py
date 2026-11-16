"""Datos de pasarela de prueba; ninguna llamada a Wompi."""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import ConfiguracionPagos


def conectar_pruebas(empresa):
    config = ConfiguracionPagos(
        empresa=empresa, modo="pruebas", activa=True, verificada_en=timezone.now(),
        llave_publica="pub_test_x", cobrar_tarifa_al_comprador=settings.WOMPI_COBRAR_TARIFA_AL_COMPRADOR,
        tarifa_porcentaje=Decimal(settings.WOMPI_TARIFA_PORCENTAJE),
        tarifa_fija=Decimal(settings.WOMPI_TARIFA_FIJA),
    )
    config.poner_secreto("llave_privada", "prv_test_x")
    config.poner_secreto("secreto_integridad", "test_integrity_x")
    config.poner_secreto("secreto_eventos", "secreto_eventos")
    config.save()
    return config
