"""Bodegas: stock por bodega, traslados, POS por bodega, marketplace desde la bodega en línea y reglas."""
import json
from decimal import Decimal
from unittest import mock

from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from suscripciones.services import cambiar_plan

from . import bodegas, caja
from .compras import crear_pedido, vencer_pedido
from .models import Bodega, Existencia, Factura, MovimientoInventario, Pedido, Producto
from .services import StockInsuficiente, anular_factura, crear_factura, registrar_movimiento
from .tests_compra import DATOS_ENVIO, crear_negocio, crear_producto, crear_usuario
from .testing_pagos import conectar_pruebas
from .caja import consumidor_final


class BaseBodegas(TestCase):
    def setUp(self):
        self.dueno = crear_usuario("dueno@correo.co")
        self.negocio = crear_negocio("Dulce Hogar", "900", self.dueno)
        self.producto = crear_producto(self.negocio, stock=10)  # stock inicial sin bodega: va a la Principal
        self.principal = bodegas.bodega_principal(self.negocio)
        cambiar_plan(self.negocio, "pro")  # el plan Pro permite varias bodegas
        self.norte = bodegas.guardar_bodega(empresa=self.negocio, nombre="Norte")

    def cantidad(self, bodega, producto=None):
        producto = producto or self.producto
        return Existencia.objects.filter(bodega=bodega, producto=producto).values_list("cantidad", flat=True).first() or 0

    def assertCuadra(self, producto=None):
        producto = Producto.objects.get(pk=(producto or self.producto).pk)
        suma = Existencia.objects.filter(producto=producto).aggregate(t=Sum("cantidad"))["t"] or 0
        self.assertEqual(producto.stock, suma, "Producto.stock debe ser la suma de sus bodegas")

    def trasladar(self, cantidad, origen=None, destino=None):
        bodegas.trasladar(empresa=self.negocio, producto=self.producto, origen=origen or self.principal,
                          destino=destino or self.norte, cantidad=cantidad, usuario=self.dueno)


class StockPorBodegaTests(BaseBodegas):
    def test_negocio_nuevo_nace_con_principal_que_vende_en_linea(self):
        self.assertTrue(self.principal.es_principal and self.principal.vende_en_linea)
        self.assertFalse(self.norte.es_principal or self.norte.vende_en_linea)

    def test_stock_inicial_sin_bodega_se_asigna_a_la_principal_al_moverse(self):
        registrar_movimiento(empresa=self.negocio, producto=self.producto, tipo="entrada", cantidad=2,
                             usuario=self.dueno)
        self.assertEqual(self.cantidad(self.principal), 12)
        self.assertCuadra()

    def test_trasladar_no_cambia_el_total_y_deja_dos_movimientos(self):
        self.trasladar(4)
        self.assertEqual((self.cantidad(self.principal), self.cantidad(self.norte)), (6, 4))
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 10)
        movimientos = MovimientoInventario.objects.filter(referencia__startswith="Traslado")
        self.assertEqual(sorted(movimientos.values_list("tipo", "bodega__nombre")),
                         [("entrada", "Norte"), ("salida", "Principal")])
        self.assertCuadra()

    def test_no_traslada_mas_de_lo_que_hay_en_el_origen(self):
        with self.assertRaises(StockInsuficiente):
            self.trasladar(11)
        # Todo se revierte: nada llega a Norte y el total sigue intacto
        self.assertEqual(self.cantidad(self.norte), 0)
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 10)
        self.assertEqual(bodegas.existencia(self.producto, self.principal), 10)

    def test_factura_valida_contra_la_bodega_no_contra_el_total(self):
        self.trasladar(8)  # Principal 2, Norte 8
        cliente = consumidor_final(self.negocio)
        with self.assertRaisesMessage(StockInsuficiente, "en Principal: hay 2"):
            crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente,
                          items=[{"producto": self.producto, "cantidad": 3}])
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente,
                                items=[{"producto": self.producto, "cantidad": 3}], bodega=self.norte)
        self.assertEqual((factura.bodega, self.cantidad(self.norte)), (self.norte, 5))
        self.assertCuadra()

    def test_anular_devuelve_a_la_bodega_de_la_venta(self):
        self.trasladar(5)
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=consumidor_final(self.negocio),
                                items=[{"producto": self.producto, "cantidad": 2}], bodega=self.norte)
        anular_factura(factura=factura, usuario=self.dueno)
        self.assertEqual((self.cantidad(self.principal), self.cantidad(self.norte)), (5, 5))
        self.assertCuadra()

    def test_bodega_de_otro_negocio_no_se_acepta(self):
        otro = crear_negocio("Otro", "901", crear_usuario("o@correo.co"))
        ajena = bodegas.bodega_principal(otro)
        with self.assertRaises(ValueError):
            registrar_movimiento(empresa=self.negocio, producto=self.producto, tipo="entrada", cantidad=1,
                                 usuario=self.dueno, bodega=ajena)

    def test_stock_editado_a_mano_se_cuadra_restando_de_la_principal(self):
        self.trasladar(3)
        Producto.objects.filter(pk=self.producto.pk).update(stock=8)  # alguien bajó 2 desde /admin/
        with self.assertLogs("core.bodegas", level="WARNING"):
            registrar_movimiento(empresa=self.negocio, producto=self.producto, tipo="entrada", cantidad=1,
                                 usuario=self.dueno, bodega=self.norte)
        self.assertEqual((self.cantidad(self.principal), self.cantidad(self.norte)), (5, 4))
        self.assertCuadra()


class PosPorBodegaTests(BaseBodegas):
    def test_la_caja_vende_desde_su_bodega(self):
        self.trasladar(3)
        self.client.force_login(self.dueno)
        self.client.post(reverse("pos_abrir"), {"base": "0", "bodega": self.norte.pk})
        turno = caja.turno_abierto(self.negocio, self.dueno)
        self.assertEqual(turno.bodega, self.norte)

        def vender(cantidad):
            return self.client.post(reverse("pos_vender"), json.dumps({
                "lineas": [{"producto": str(self.producto.pk), "cantidad": cantidad}],
                "pagos": [{"metodo": "efectivo", "recibido": "999999"}],
            }), content_type="application/json")

        self.assertIn("en Norte: hay 3", vender(4).json()["error"])
        self.assertTrue(vender(3).json()["ok"])
        self.assertEqual((self.cantidad(self.principal), self.cantidad(self.norte)), (7, 0))
        self.assertCuadra()

    def test_el_pos_muestra_el_stock_de_su_bodega(self):
        self.trasladar(3)
        self.client.force_login(self.dueno)
        self.client.post(reverse("pos_abrir"), {"base": "0", "bodega": self.norte.pk})
        datos = self.client.get(reverse("pos_productos"), {"q": self.producto.codigo}).json()
        self.assertEqual(datos["exacto"]["stock"], 3)

    def test_abrir_caja_ofrece_elegir_bodega(self):
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse("pos")), 'name="bodega"')


class MarketplacePorBodegaTests(BaseBodegas):
    def setUp(self):
        super().setUp()
        conectar_pruebas(self.negocio)
        self.comprador = crear_usuario("c@correo.co")

    def test_vende_y_reserva_desde_la_bodega_en_linea(self):
        self.trasladar(4)
        bodegas.guardar_bodega(empresa=self.negocio, bodega=self.norte, nombre="Norte", vende_en_linea=True)
        producto = Producto.objects.get(pk=self.producto.pk)
        from .marketplace import productos_publicos
        self.assertEqual(productos_publicos().get(pk=producto.pk).disponible, 4)

        with mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None):
            pedido = crear_pedido(usuario=self.comprador, negocio=self.negocio,
                                  lineas=[{"producto": producto, "cantidad": 3}], datos=DATOS_ENVIO)
            self.assertEqual((pedido.bodega, self.cantidad(self.norte)), (self.norte, 1))
            Pedido.objects.filter(pk=pedido.pk).update(expira_en=pedido.creado_en)
            vencer_pedido(pedido.pk)
        self.assertEqual((self.cantidad(self.principal), self.cantidad(self.norte)), (6, 4))
        self.assertCuadra()

    def test_el_carrito_no_deja_pasar_de_lo_que_hay_en_linea(self):
        self.trasladar(8)
        bodegas.guardar_bodega(empresa=self.negocio, bodega=self.norte, nombre="Norte", vende_en_linea=True)
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 50})
        self.assertEqual(self.client.session["carrito"][str(self.producto.pk)], 8)


class ReglasBodegaTests(BaseBodegas):
    def test_plan_sin_multisede_permite_una_sola_bodega(self):
        otro = crear_negocio("Pequeño", "902", crear_usuario("p@correo.co"))
        cambiar_plan(otro, "emprendedor")
        with self.assertRaisesMessage(bodegas.OperacionBodega, "plan Pro"):
            bodegas.guardar_bodega(empresa=otro, nombre="Segunda")

    def test_cambiar_la_principal_quita_la_marca_a_la_anterior(self):
        bodegas.guardar_bodega(empresa=self.negocio, bodega=self.norte, nombre="Norte", es_principal=True)
        self.principal.refresh_from_db()
        self.assertFalse(self.principal.es_principal)
        self.assertEqual(bodegas.bodega_principal(self.negocio), self.norte)
        self.assertTrue(self.principal.vende_en_linea)  # la otra marca no se toca

    def test_no_se_puede_dejar_sin_principal(self):
        with self.assertRaisesMessage(bodegas.OperacionBodega, "márcala en la bodega que la reemplaza"):
            bodegas.guardar_bodega(empresa=self.negocio, bodega=self.principal, nombre="Principal")

    def test_no_desactiva_con_mercancia_ni_la_principal(self):
        self.trasladar(1)
        with self.assertRaisesMessage(bodegas.OperacionBodega, "todavía tiene mercancía"):
            bodegas.desactivar_bodega(empresa=self.negocio, bodega=self.norte)
        with self.assertRaises(bodegas.OperacionBodega):
            bodegas.desactivar_bodega(empresa=self.negocio, bodega=self.principal)
        self.trasladar(1, origen=self.norte, destino=self.principal)
        bodegas.desactivar_bodega(empresa=self.negocio, bodega=self.norte)
        self.norte.refresh_from_db()
        self.assertFalse(self.norte.activa)

    def test_nombre_repetido(self):
        with self.assertRaisesMessage(bodegas.OperacionBodega, "Ya existe"):
            bodegas.guardar_bodega(empresa=self.negocio, nombre="norte")


class PanelBodegasTests(BaseBodegas):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.dueno)

    def test_lista_y_kardex_muestran_stock_por_bodega(self):
        self.trasladar(4)
        self.assertContains(self.client.get(reverse("bodegas_lista")), "Norte")
        kardex = self.client.get(reverse("productos_kardex", args=[self.producto.pk]))
        self.assertContains(kardex, "Stock por bodega")
        self.assertContains(kardex, reverse("productos_trasladar", args=[self.producto.pk]))

    def test_trasladar_desde_el_panel(self):
        respuesta = self.client.post(reverse("productos_trasladar", args=[self.producto.pk]),
                                     {"origen": self.principal.pk, "destino": self.norte.pk, "cantidad": 3})
        self.assertRedirects(respuesta, reverse("productos_kardex", args=[self.producto.pk]))
        self.assertEqual(self.cantidad(self.norte), 3)

    def test_movimiento_en_una_bodega_elegida(self):
        self.client.post(reverse("productos_movimiento", args=[self.producto.pk]),
                         {"tipo": "entrada", "cantidad": 5, "referencia": "Compra", "bodega": self.norte.pk})
        self.assertEqual(self.cantidad(self.norte), 5)
        self.assertCuadra()

    def test_crear_bodega_desde_el_panel(self):
        respuesta = self.client.post(reverse("bodegas_crear"), {"nombre": "Sur", "direccion": "Calle 5"})
        self.assertRedirects(respuesta, reverse("bodegas_lista"))
        self.assertTrue(Bodega.objects.filter(empresa=self.negocio, nombre="Sur").exists())

    def test_otro_negocio_no_ve_ni_traslada(self):
        intruso = crear_usuario("i@correo.co")
        crear_negocio("Intruso", "903", intruso)
        self.client.force_login(intruso)
        self.assertEqual(self.client.get(reverse("bodegas_editar", args=[self.norte.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("productos_trasladar", args=[self.producto.pk])).status_code, 404)
