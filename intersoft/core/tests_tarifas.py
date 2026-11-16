"""Cargo de la pasarela (Wompi) trasladado al comprador del marketplace."""
from decimal import Decimal

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import compras
from .models import ConfiguracionPagos, Empresa, Producto
from .tarifas import cargo_pasarela
from .tests_compra import DATOS_ENVIO
from .tests_pedidos import PedidoBase

TARIFA = {
    "WOMPI_COBRAR_TARIFA_AL_COMPRADOR": True,
    "WOMPI_TARIFA_PORCENTAJE": "2.65",
    "WOMPI_TARIFA_FIJA": "700",
    "WOMPI_TARIFA_IVA": "19",
}


def descuento_wompi(cobrado):
    """Lo que Wompi le descuenta al negocio de una transacción aprobada."""
    return (cobrado * Decimal("0.0265") + Decimal("700")) * Decimal("1.19")


@override_settings(**TARIFA)
class CargoPasarelaTests(SimpleTestCase):
    def setUp(self):
        self.config = ConfiguracionPagos(activa=True, verificada_en=timezone.now())

    def test_cargo_cubre_la_comision_y_el_negocio_recibe_su_precio(self):
        for monto in (Decimal("1000"), Decimal("23800"), Decimal("199920"), Decimal("1234567.89")):
            with self.subTest(monto=monto):
                cobrado = monto + cargo_pasarela(monto, config=self.config)
                self.assertGreaterEqual(cobrado - descuento_wompi(cobrado), monto)
                # Redondeado al peso: nunca cobra más de un peso de sobra
                self.assertLess(cobrado - descuento_wompi(cobrado) - monto, Decimal("1"))

    def test_valor_conocido(self):
        # (23.800 + 833) / (1 - 0,031535) = 25.435,10 → cargo 1.636 redondeado hacia arriba
        self.assertEqual(cargo_pasarela(Decimal("23800"), config=self.config), Decimal("1636.00"))

    def test_monto_cero_o_negativo_no_genera_cargo(self):
        self.assertEqual(cargo_pasarela(Decimal("0")), Decimal("0.00"))
        self.assertEqual(cargo_pasarela(Decimal("-5")), Decimal("0.00"))

    @override_settings(WOMPI_COBRAR_TARIFA_AL_COMPRADOR=False)
    def test_desactivado_no_cobra(self):
        self.config.cobrar_tarifa_al_comprador = False
        self.assertEqual(cargo_pasarela(Decimal("23800"), config=self.config), Decimal("0.00"))


@override_settings(**TARIFA)
class CargoPasarelaPedidoTests(PedidoBase):
    def preparar(self):
        Empresa.objects.filter(pk=self.negocio.pk).update(comision_porcentaje=Decimal("8.00"))
        self.negocio.refresh_from_db()
        Producto.objects.filter(pk=self.producto.pk).update(
            precio=Decimal("10000.00"), iva_porcentaje=Decimal("19.00"), stock=10, publicado=True
        )
        self.producto.refresh_from_db()

    def test_pedido_suma_el_cargo_y_el_neto_del_negocio_no_cambia(self):
        self.preparar()
        pedido = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 2}],
            datos=DATOS_ENVIO,
        )
        self.assertEqual(pedido.cargo_pasarela, Decimal("1636.00"))
        self.assertEqual(pedido.total, Decimal("25436.00"))
        self.assertEqual(pedido.comision_valor, Decimal("0.00"))
        self.assertEqual(pedido.neto_vendedor, Decimal("23800.00"))

    def test_producto_muestra_precio_con_cargo(self):
        self.preparar()
        self.assertEqual(self.producto.precio_marketplace, Decimal("11900.00") + cargo_pasarela(
            Decimal("11900"), config=self.negocio.configuracion_pagos))
        respuesta = self.client.get(reverse("tienda_producto", args=[self.producto.pk]))
        self.assertContains(respuesta, "cargo de pasarela incluidos")

    def test_carrito_y_pedido_cobran_lo_mismo(self):
        self.preparar()
        self.client.force_login(self.comprador)
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 2})
        respuesta = self.client.get(reverse("carrito"))
        self.assertContains(respuesta, "Cargo pasarela de pagos (Wompi)")
        self.assertContains(respuesta, "$25.436")
