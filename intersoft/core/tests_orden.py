"""Compra unificada: un checkout para varios negocios y un pago por negocio."""
from unittest import mock

from django.urls import reverse

from .models import Orden, Pago, Pedido
from .services import StockInsuficiente
from .tests_compra import DATOS_ENVIO, Base, crear_negocio, crear_producto, crear_usuario, transaccion
from .testing_pagos import conectar_pruebas


class CompraUnificadaTests(Base):
    def setUp(self):
        super().setUp()
        self.otro = crear_negocio("Ferretería", "222", crear_usuario("o@correo.co"))
        conectar_pruebas(self.otro)
        self.martillo = crear_producto(self.otro, "Martillo", codigo="M-1", stock=3)
        self.client.force_login(self.comprador)
        self.agregar(cantidad=2)
        self.agregar(self.martillo)

    def comprar_todo(self):
        return self.client.post(reverse("checkout_todo"), DATOS_ENVIO)

    def test_el_carrito_ofrece_comprar_todo(self):
        respuesta = self.client.get(reverse("carrito"))
        self.assertContains(respuesta, reverse("checkout_todo"))
        self.assertContains(respuesta, "Comprar solo en este negocio")

    def test_crea_un_pedido_por_negocio_con_los_mismos_datos(self):
        respuesta = self.comprar_todo()
        orden = Orden.objects.get()
        self.assertRedirects(respuesta, reverse("orden_detalle", args=[orden.pk]), fetch_redirect_response=False)
        pedidos = list(orden.pedidos.all())
        self.assertEqual({p.empresa_id for p in pedidos}, {self.negocio.pk, self.otro.pk})
        self.assertTrue(all(p.direccion == DATOS_ENVIO["direccion"] for p in pedidos))
        self.assertEqual(self.cantidad_en_carrito(), {})
        self.producto.refresh_from_db()
        self.martillo.refresh_from_db()
        self.assertEqual((self.producto.stock, self.martillo.stock), (3, 2))  # reservado

    def test_todo_o_nada_si_un_negocio_se_queda_sin_stock(self):
        # El primer negocio reserva bien y el segundo falla justo al confirmar (otra compra se lo llevó)
        with mock.patch("core.reservas.reservar_stock", side_effect=[None, StockInsuficiente("sin stock")]):
            respuesta = self.comprar_todo()
        self.assertRedirects(respuesta, reverse("carrito"), fetch_redirect_response=False)
        self.assertFalse(Orden.objects.exists())
        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(len(self.cantidad_en_carrito()), 2)  # el carrito queda intacto

    def test_negocio_sin_compra_en_linea_queda_en_el_carrito(self):
        self.otro.configuracion_pagos.delete()
        respuesta = self.client.get(reverse("checkout_todo"))
        self.assertContains(respuesta, "No incluye Ferretería")
        self.comprar_todo()
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.empresa, self.negocio)
        self.assertEqual(list(self.cantidad_en_carrito()), [str(self.martillo.pk)])

    def test_un_solo_negocio_va_directo_al_pedido(self):
        self.client.post(reverse("carrito_quitar", args=[self.martillo.pk]))
        respuesta = self.comprar_todo()
        self.assertRedirects(respuesta, reverse("pedido_detalle", args=[Pedido.objects.get().pk]),
                             fetch_redirect_response=False)

    def test_pagar_vuelve_a_la_orden_y_concilia_solo_ese_pedido(self):
        self.comprar_todo()
        orden = Orden.objects.get()
        pan = orden.pedidos.get(empresa=self.negocio)
        with mock.patch("core.views_compra.url_checkout", return_value="https://checkout.wompi.co/p/") as checkout:
            self.client.post(reverse("pedido_pagar", args=[pan.pk]))
        destino = checkout.call_args.kwargs["redirect_url"]
        self.assertTrue(destino.endswith(f"{reverse('orden_detalle', args=[orden.pk])}?pedido={pan.pk}"))

        self.buscar.return_value = transaccion(Pago.objects.get())
        pagina = self.client.get(reverse("orden_detalle", args=[orden.pk]), {"pedido": pan.pk, "id": "t-1"})
        self.assertEqual(Pedido.objects.get(pk=pan.pk).estado, Pedido.Estado.PAGADO)
        self.assertEqual(orden.pedidos.get(empresa=self.otro).estado, Pedido.Estado.PENDIENTE)
        self.assertContains(pagina, "Te falta 1 pago")

    def test_otra_persona_no_ve_la_orden(self):
        self.comprar_todo()
        orden = Orden.objects.get()
        self.client.force_login(crear_usuario("intruso@correo.co"))
        self.assertEqual(self.client.get(reverse("orden_detalle", args=[orden.pk])).status_code, 404)

    def test_el_pedido_enlaza_a_toda_la_compra(self):
        self.comprar_todo()
        orden = Orden.objects.get()
        pedido = orden.pedidos.first()
        respuesta = self.client.get(reverse("pedido_detalle", args=[pedido.pk]))
        self.assertContains(respuesta, reverse("orden_detalle", args=[orden.pk]))
