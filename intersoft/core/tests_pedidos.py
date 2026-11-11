"""Pedidos con reserva: la factura nace con el pago."""
import threading
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import compras
from .models import Cliente, Empresa, Factura, MovimientoInventario, Pago, Pedido, Producto
from .pagos import (
    PagoNoPermitido,
    ResultadoWompi,
    WompiNoResponde,
    aplicar_transaccion,
    buscar_transaccion_por_referencia,
    calcular_firma_integridad,
    crear_pago,
    crear_pago_pedido,
    formato_expiracion,
    revisar_en_wompi,
    url_checkout,
)
from .reservas import actualizar_envio_pedido, marcar_pagado, registrar_reembolso
from .services import StockInsuficiente, anular_factura, crear_factura
from .tests_compra import Base, DATOS_ENVIO, crear_negocio, crear_producto, crear_usuario, transaccion

Usuario = get_user_model()


def crear_pedido_simple(empresa, comprador, numero=1):
    return Pedido.objects.create(
        empresa=empresa, comprador=comprador, numero=numero, total=Decimal("1190"),
        expira_en=timezone.now() + timedelta(minutes=30), tipo_documento="CC", numero_documento="1",
        nombre="Ana", email="a@c.co", telefono="3001234567", departamento="Meta", ciudad="Acacías", direccion="Calle 1",
    )


class RestriccionesPagoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Una", nit="1", slug="una")
        self.usuario = Usuario.objects.create_user(username="a@c.co", email="a@c.co", password="x")
        self.pedido = crear_pedido_simple(self.empresa, self.usuario)
        cliente = Cliente.objects.create(empresa=self.empresa, tipo_documento="CC", numero_documento="9", nombre="C")
        self.factura = Factura.objects.create(empresa=self.empresa, numero=1, cliente=cliente, creada_por=self.usuario)

    def pago(self, referencia="R-1", **campos):
        return Pago.objects.create(empresa=self.empresa, referencia=referencia, monto_centavos=100, **campos)

    def test_pago_con_pedido_o_con_factura_es_valido(self):
        self.pago("R-1", pedido=self.pedido)
        self.pago("R-2", factura=self.factura)
        self.assertEqual(Pago.objects.count(), 2)

    def test_no_permite_pago_con_pedido_y_factura(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pago(pedido=self.pedido, factura=self.factura)

    def test_no_permite_pago_sin_pedido_ni_factura(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pago()

    def test_un_solo_pago_aprobado_por_pedido(self):
        self.pago("R-1", pedido=self.pedido, estado="aprobado")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.pago("R-2", pedido=self.pedido, estado="aprobado")

    def test_numero_de_pedido_unico_por_empresa(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            crear_pedido_simple(self.empresa, self.usuario, numero=1)


class MigracionDatosPedidosTests(TransactionTestCase):
    ANTES = [("core", "0006_comentario_pedido")]
    DESPUES = [("core", "0009_pedido_reserva_restricciones")]

    def setUp(self):
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(self.ANTES)
        apps = ejecutor.loader.project_state(self.ANTES).apps
        self.addCleanup(self.volver_a_la_ultima)

        Empresa_ = apps.get_model("core", "Empresa")
        Usuario_ = apps.get_model("core", "Usuario")
        Cliente_ = apps.get_model("core", "Cliente")
        Producto_ = apps.get_model("core", "Producto")
        self.Factura_ = apps.get_model("core", "Factura")
        self.DetalleFactura_ = apps.get_model("core", "DetalleFactura")
        self.Pedido_ = apps.get_model("core", "Pedido")
        self.Pago_ = apps.get_model("core", "Pago")

        self.empresa = Empresa_.objects.create(nombre="Una", nit="1", slug="una")
        self.usuario = Usuario_.objects.create(username="a@c.co", email="a@c.co", password="x")
        self.cliente = Cliente_.objects.create(empresa=self.empresa, tipo_documento="CC", numero_documento="77", nombre="C")
        self.producto = Producto_.objects.create(empresa=self.empresa, codigo="P", nombre="P", precio=Decimal("1000"), stock=3)

    def volver_a_la_ultima(self):
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())

    def factura(self, numero, con_pedido=True, estado="emitida"):
        factura = self.Factura_.objects.create(
            empresa=self.empresa, numero=numero, cliente=self.cliente, creada_por=self.usuario, estado=estado,
            subtotal=Decimal("2000"), iva=Decimal("380"), total=Decimal("2380"),
        )
        self.DetalleFactura_.objects.create(
            empresa=self.empresa, factura=factura, producto=self.producto, cantidad=2,
            precio_unitario=Decimal("1000"), iva_porcentaje=Decimal("19"),
        )
        if con_pedido:
            self.Pedido_.objects.create(
                empresa=self.empresa, comprador=self.usuario, factura=factura, nombre="Ana", email="a@c.co",
                telefono="3001234567", departamento="Meta", ciudad="Acacías", direccion="Calle 1",
            )
        return factura

    def migrar_hasta_la_de_datos(self):
        """Ejecuta 0007, 0008 (datos) y 0009, y devuelve los modelos históricos de ese punto."""
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(self.DESPUES)
        return MigrationExecutor(connection).loader.project_state(self.DESPUES).apps

    def migrar_hasta_la_ultima(self):
        # Después se usan los modelos actuales, que pueden tener campos de migraciones posteriores
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())

    def test_adapta_los_tres_casos_y_no_toca_las_demas_facturas(self):
        pagada = self.factura(1)
        self.Pago_.objects.create(empresa=self.empresa, factura=pagada, referencia="R-1", monto_centavos=238000, estado="aprobado")
        self.factura(2, estado="anulada")
        sin_pagar = self.factura(3)
        self.Pago_.objects.create(empresa=self.empresa, factura=sin_pagar, referencia="R-3", monto_centavos=238000)
        suelta = self.factura(4, con_pedido=False)

        # 1. Justo después de la migración de datos, con los modelos de ese momento:
        #    así el resultado se le atribuye a la 0008 y no a una migración posterior
        apps = self.migrar_hasta_la_de_datos()
        Pedido_ = apps.get_model("core", "Pedido")
        self.assertEqual(
            dict(Pedido_.objects.values_list("factura__numero", "estado")),
            {1: "pagado", 2: "cancelado", 3: "cancelado"},
        )
        self.assertEqual(apps.get_model("core", "Producto").objects.get(pk=self.producto.pk).stock, 5)
        self.assertEqual(apps.get_model("core", "Factura").objects.get(numero=3).estado, "anulada")
        self.assertEqual(apps.get_model("core", "Factura").objects.get(numero=4).estado, "emitida")

        # 2. Con todas las migraciones aplicadas, el resultado se mantiene
        self.migrar_hasta_la_ultima()

        pedido = Pedido.objects.get(factura__numero=1)
        self.assertEqual(pedido.estado, "pagado")
        self.assertEqual(pedido.numero, 1)
        self.assertEqual(pedido.total, Decimal("2380"))
        self.assertEqual(pedido.numero_documento, "77")
        linea = pedido.lineas.get()
        self.assertEqual((linea.cantidad, linea.precio_unitario), (2, Decimal("1000.00")))
        self.assertEqual(Pago.objects.get(referencia="R-1").factura_id, pagada.pk)

        self.assertEqual(Pedido.objects.get(factura__numero=2).estado, "cancelado")

        pedido = Pedido.objects.get(factura__numero=3)
        self.assertEqual(pedido.estado, "cancelado")
        self.assertEqual(pedido.factura.estado, "anulada")

        # Solo la factura sin pagar devuelve stock: 3 iniciales + 2 liberadas
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 5)
        movimiento = MovimientoInventario.objects.get()
        self.assertEqual((movimiento.tipo, movimiento.referencia), ("entrada", "Liberación pedido 3"))

        self.assertEqual(Factura.objects.get(pk=suelta.pk).estado, "emitida")


LLAVES = dict(PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_test_x", WOMPI_INTEGRITY_SECRET="test_integrity_x", WOMPI_PRIVATE_KEY="prv_test_x")


@override_settings(**LLAVES)
class PedidoBase(Base):
    def setUp(self):
        super().setUp()
        self.comprar(cantidad=2)
        self.pedido = Pedido.objects.get()

    def recargar(self):
        self.pedido.refresh_from_db()
        self.producto.refresh_from_db()

    def intento(self):
        return crear_pago_pedido(pedido=self.pedido)

    def vencer(self):
        Pedido.objects.filter(pk=self.pedido.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        self.recargar()

    def referencias(self):
        return list(MovimientoInventario.objects.order_by("creado_en").values_list("tipo", "referencia"))


class ReservaTests(PedidoBase):
    def test_reserva_queda_en_el_kardex(self):
        self.assertEqual(self.producto.__class__.objects.get(pk=self.producto.pk).stock, 3)
        self.assertEqual(self.referencias(), [("salida", f"Reserva pedido {self.pedido.numero}")])

    def test_precio_queda_congelado(self):
        Producto.objects.filter(pk=self.producto.pk).update(precio=Decimal("9000"))
        self.assertEqual(self.pedido.lineas.get().precio_unitario, Decimal("1999.98"))
        self.assertEqual(self.intento().monto_centavos, int(self.pedido.total * 100))

    def test_sin_stock_no_crea_nada(self):
        self.agregar(cantidad=3)
        Producto.objects.filter(pk=self.producto.pk).update(stock=2)
        with mock.patch("core.carrito.grupo_de", return_value=(self._grupo(cantidad=3), [])):
            self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(len(self.referencias()), 1)

    def _grupo(self, cantidad):
        producto = Producto.objects.get(pk=self.producto.pk)
        return {"negocio": self.negocio, "lineas": [{"producto": producto, "cantidad": cantidad}], "total": 0}

    def test_numero_de_pedido_consecutivo_por_negocio(self):
        self.agregar()
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        self.assertEqual(sorted(Pedido.objects.values_list("numero", flat=True)), [1, 2])


class AprobacionTests(PedidoBase):
    def aprobar(self, pago=None, **cambios):
        return aplicar_transaccion({**transaccion(pago or self.intento()), **cambios})

    def test_crea_una_factura_sin_descontar_otra_vez(self):
        self.aprobar()
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)
        self.assertEqual(self.producto.stock, 3)
        self.assertEqual(len(self.referencias()), 1)
        factura = self.pedido.factura
        self.assertEqual((factura.total, factura.subtotal), (self.pedido.total, self.pedido.subtotal))
        detalle = factura.detalles.get()
        self.assertEqual((detalle.cantidad, detalle.precio_unitario), (2, Decimal("1999.98")))
        self.assertEqual(factura.creada_por, self.comprador)

    def test_evento_repetido_crea_una_sola_factura(self):
        pago = self.intento()
        self.aprobar(pago)
        self.aprobar(pago)
        self.assertEqual(Factura.objects.count(), 1)
        self.assertEqual(len(self.referencias()), 1)

    def test_segundo_intento_aprobado_queda_en_error(self):
        primero, segundo = self.intento(), self.intento()
        self.aprobar(primero)
        with self.assertLogs("core.pagos", "CRITICAL"):
            self.aprobar(segundo)
        segundo.refresh_from_db()
        self.assertEqual(segundo.estado, Pago.Estado.ERROR)
        self.assertEqual(Factura.objects.count(), 1)

    def verificar_reembolso(self, pago):
        pago.refresh_from_db()
        self.recargar()
        self.assertEqual(pago.estado, Pago.Estado.ERROR)
        self.assertEqual(self.pedido.estado, Pedido.Estado.REQUIERE_REEMBOLSO)
        self.assertIsNone(self.pedido.factura)
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(self.referencias()[-1], ("entrada", f"Liberación pedido {self.pedido.numero}"))
        with self.assertRaises(PagoNoPermitido):
            self.intento()

    def test_monto_distinto_va_a_reembolso_y_devuelve_stock(self):
        pago = self.intento()
        with self.assertLogs("core.pagos", "CRITICAL"):
            self.aprobar(pago, amount_in_cents=pago.monto_centavos - 100)
        self.verificar_reembolso(pago)

    def test_moneda_distinta_va_a_reembolso_y_devuelve_stock(self):
        pago = self.intento()
        with self.assertLogs("core.pagos", "CRITICAL"):
            self.aprobar(pago, currency="USD")
        self.verificar_reembolso(pago)

    def test_monto_distinto_repetido_no_devuelve_dos_veces(self):
        pago = self.intento()
        with self.assertLogs("core.pagos", "CRITICAL"):
            self.aprobar(pago, amount_in_cents=1)
            self.aprobar(pago, amount_in_cents=1)
        self.recargar()
        self.assertEqual(self.producto.stock, 5)

    def test_rechazado_con_monto_distinto_no_toca_el_pedido(self):
        pago = self.intento()
        with self.assertLogs("core.pagos", "CRITICAL"):
            self.aprobar(pago, status="DECLINED", amount_in_cents=1)
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(self.producto.stock, 3)

    def test_referencia_de_otro_pago_no_cambia_nada(self):
        pago = self.intento()
        self.buscar.return_value = {**transaccion(pago), "reference": "INT-otra"}
        self.client.get(reverse("pedido_detalle", args=[self.pedido.pk]))
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_aprobado_tardio_con_stock_se_factura(self):
        pago = self.intento()
        compras.reservas.liberar_pedido(self.pedido, Pedido.Estado.VENCIDO)
        self.aprobar(pago)
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)
        self.assertEqual(Factura.objects.count(), 1)
        self.assertEqual(self.producto.stock, 3)
        self.assertEqual(self.referencias()[-1], ("salida", f"Reserva pedido {self.pedido.numero}"))

    def test_aprobado_tardio_sin_stock_requiere_reembolso(self):
        pago = self.intento()
        compras.reservas.liberar_pedido(self.pedido, Pedido.Estado.VENCIDO)
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)
        with self.assertLogs("core.reservas", "CRITICAL"):
            self.aprobar(pago)
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.REQUIERE_REEMBOLSO)
        self.assertFalse(Factura.objects.exists())
        self.assertEqual(self.producto.stock, 1)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)

    def test_aprobado_tras_cancelar_requiere_reembolso_sin_reservar(self):
        pago = self.intento()
        compras.reservas.liberar_pedido(self.pedido, Pedido.Estado.CANCELADO)
        with self.assertLogs("core.reservas", "CRITICAL"):
            self.aprobar(pago)
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.REQUIERE_REEMBOLSO)
        self.assertEqual(self.producto.stock, 5)

    def test_reutiliza_cliente_inactivo_sin_duplicarlo(self):
        existente = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="1020304", nombre="Antes", activo=False)
        self.aprobar()
        self.recargar()
        self.assertEqual(Cliente.objects.filter(empresa=self.negocio).count(), 1)
        self.assertEqual(self.pedido.factura.cliente, existente)


class BusquedaWompiTests(TestCase):
    def setUp(self):
        parche = override_settings(**LLAVES)
        parche.enable()
        self.addCleanup(parche.disable)

    def test_falla_de_red_se_distingue(self):
        with mock.patch("core.pagos.urlopen", side_effect=URLError("sin red")):
            with self.assertRaises(WompiNoResponde):
                buscar_transaccion_por_referencia("INT-1")

    def test_sin_transacciones_devuelve_none(self):
        respuesta = mock.MagicMock()
        respuesta.__enter__.return_value.read.return_value = b'{"data": []}'
        with mock.patch("core.pagos.urlopen", return_value=respuesta):
            self.assertIsNone(buscar_transaccion_por_referencia("INT-1"))


class CancelarTests(PedidoBase):
    def cancelar(self):
        return self.client.post(reverse("pedido_cancelar", args=[self.pedido.pk]), follow=True)

    def test_sin_transaccion_en_wompi_se_cancela(self):
        self.intento()
        self.buscar.return_value = None
        self.assertContains(self.cancelar(), "Este pedido fue cancelado")
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CANCELADO)
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(self.referencias()[-1], ("entrada", f"Liberación pedido {self.pedido.numero}"))

    def test_aprobado_en_wompi_no_se_cancela(self):
        self.buscar.return_value = transaccion(self.intento())
        self.assertContains(self.cancelar(), "Gracias por tu compra")
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)

    def test_en_proceso_no_se_cancela(self):
        self.buscar.return_value = transaccion(self.intento(), status="PENDING")
        self.assertContains(self.cancelar(), "sigue en proceso")
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(self.producto.stock, 3)

    def test_wompi_no_responde_no_se_cancela(self):
        self.intento()
        self.buscar.side_effect = WompiNoResponde
        self.assertContains(self.cancelar(), "No pudimos confirmar")
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)

    def test_sin_llave_privada_no_se_cancela(self):
        self.intento()
        with override_settings(WOMPI_PRIVATE_KEY=""):
            self.assertEqual(revisar_en_wompi(self.pedido), ResultadoWompi.SIN_RESPUESTA)

    def test_sin_intentos_se_cancela_sin_consultar(self):
        self.cancelar()
        self.buscar.assert_not_called()
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.CANCELADO)

    def test_cancelar_dos_veces_no_devuelve_dos_veces(self):
        self.cancelar()
        self.assertContains(self.cancelar(), "ya no se puede cancelar")
        self.recargar()
        self.assertEqual(self.producto.stock, 5)


class ExpiracionWompiTests(PedidoBase):
    def test_firma_con_expiracion_sigue_el_orden_documentado(self):
        # La documentación repite por error el hash del ejemplo sin expiración; este es el calculado
        firma = calcular_firma_integridad(
            referencia="sk8-438k4-xmxm392-sn2m",
            monto_centavos=2490000,
            moneda="COP",
            secreto="prod_integrity_Z5mMke9x0k8gpErbDqwrJXMqsI6SFli6",
            expiracion="2023-06-09T20:28:50.000Z",
        )
        self.assertEqual(firma, "e972f58e7de36b283fbb93d9318d39a54ffdff4e8e917b534f30d63c9d7bb89c")

    def test_formato_iso_utc_sin_microsegundos(self):
        fecha = timezone.datetime(2026, 11, 9, 15, 28, 50, 123456, tzinfo=timezone.get_fixed_timezone(-300))
        self.assertEqual(formato_expiracion(fecha), "2026-11-09T20:28:50.000Z")

    def test_url_y_firma_usan_el_mismo_texto(self):
        pago = self.intento()
        datos = parse_qs(urlsplit(url_checkout(pago=pago, redirect_url="https://intersoft.co/x/")).query)
        texto = datos["expiration-time"][0]
        self.assertEqual(texto, formato_expiracion(self.pedido.expira_en))
        esperada = calcular_firma_integridad(
            referencia=pago.referencia, monto_centavos=pago.monto_centavos, moneda="COP",
            secreto="test_integrity_x", expiracion=texto,
        )
        self.assertEqual(datos["signature:integrity"][0], esperada)

    def test_cobro_de_factura_no_lleva_expiracion(self):
        cliente = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="5", nombre="C")
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente, items=[{"producto": self.producto, "cantidad": 1}])
        url = url_checkout(pago=crear_pago(factura=factura), redirect_url="https://intersoft.co/x/")
        self.assertNotIn("expiration-time", url)


class RenovacionTests(PedidoBase):
    def faltan(self, minutos):
        Pedido.objects.filter(pk=self.pedido.pk).update(expira_en=timezone.now() + timedelta(minutes=minutos))
        self.recargar()

    def renovar(self):
        return self.client.post(reverse("pedido_renovar", args=[self.pedido.pk]), follow=True)

    def detalle(self):
        return self.client.get(reverse("pedido_detalle", args=[self.pedido.pk]))

    def test_con_poco_tiempo_no_abre_wompi(self):
        self.faltan(4)
        respuesta = self.client.post(reverse("pedido_pagar", args=[self.pedido.pk]), follow=True)
        self.assertFalse(Pago.objects.exists())
        self.assertContains(respuesta, "Renovar reserva")
        self.assertNotContains(respuesta, "Pagar con Wompi")

    def test_con_tiempo_suficiente_abre_wompi(self):
        self.faltan(6)
        self.assertTrue(self.client.post(reverse("pedido_pagar", args=[self.pedido.pk])).url.startswith("https://checkout.wompi.co/"))

    def test_renovar_extiende_el_plazo_normal(self):
        self.faltan(4)
        self.renovar()
        self.recargar()
        self.assertEqual(self.pedido.renovaciones, 1)
        self.assertGreater(self.pedido.expira_en, timezone.now() + timedelta(minutes=29))
        self.assertEqual(self.producto.stock, 3)

    def test_maximo_dos_renovaciones(self):
        for _ in range(2):
            self.faltan(4)
            self.renovar()
        self.faltan(4)
        respuesta = self.renovar()
        self.assertContains(respuesta, "Ya usaste las renovaciones")
        self.recargar()
        self.assertEqual(self.pedido.renovaciones, 2)

    def test_no_renueva_si_sigue_vigente(self):
        self.renovar()
        self.recargar()
        self.assertEqual(self.pedido.renovaciones, 0)

    def test_no_renueva_si_un_producto_se_desactivo(self):
        self.faltan(4)
        Producto.objects.filter(pk=self.producto.pk).update(activo=False)
        self.renovar()
        self.recargar()
        self.assertEqual(self.pedido.renovaciones, 0)

    def test_renovar_vencido_vuelve_a_reservar(self):
        compras.reservas.liberar_pedido(self.pedido, Pedido.Estado.VENCIDO)
        self.renovar()
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(self.producto.stock, 3)

    def test_renovar_vencido_sin_stock_no_renueva(self):
        compras.reservas.liberar_pedido(self.pedido, Pedido.Estado.VENCIDO)
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)
        self.assertContains(self.renovar(), "ya no hay unidades")
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.VENCIDO)
        self.assertEqual(self.producto.stock, 1)

    def test_pagar_reserva_vencida_la_libera(self):
        self.vencer()
        with self.assertRaises(PagoNoPermitido):
            self.intento()
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.VENCIDO)
        self.assertEqual(self.producto.stock, 5)
        self.assertFalse(Pago.objects.exists())


class ConvivenciaPanelTests(PedidoBase):
    def setUp(self):
        super().setUp()
        marcar_pagado(self.pedido)
        self.factura = self.pedido.factura

    def test_factura_del_marketplace_esta_pagada_sin_pagos_propios(self):
        self.assertFalse(self.factura.pagos.exists())
        self.assertTrue(self.factura.esta_pagada)

    def test_no_se_puede_cobrar_de_nuevo(self):
        with self.assertRaises(PagoNoPermitido):
            crear_pago(factura=self.factura)

    def test_no_se_puede_anular(self):
        with self.assertRaises(ValueError):
            anular_factura(factura=self.factura, usuario=self.dueno)

    def test_la_lista_del_panel_la_muestra_pagada(self):
        self.client.force_login(self.dueno)
        respuesta = self.client.get(reverse("facturas_lista"))
        self.assertTrue(respuesta.context["facturas"][0].pagada)
        self.assertContains(respuesta, "Pagada")

    def test_factura_normal_sigue_cobrandose(self):
        cliente = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="5", nombre="C")
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente, items=[{"producto": self.producto, "cantidad": 1}])
        self.assertFalse(factura.esta_pagada)
        pago = crear_pago(factura=factura)
        self.assertEqual(pago.factura, factura)
        self.assertIsNone(pago.pedido)


class ComandoVencimientoTests(PedidoBase):
    def ejecutar(self):
        salida = StringIO()
        call_command("liberar_pedidos_vencidos", stdout=salida)
        self.recargar()
        return salida.getvalue()

    def vencido_hace(self, minutos):
        Pedido.objects.filter(pk=self.pedido.pk).update(expira_en=timezone.now() - timedelta(minutes=minutos))
        self.recargar()

    def test_vence_y_devuelve_el_stock(self):
        self.vencido_hace(1)
        self.assertIn("Vencidos: 1", self.ejecutar())
        self.assertEqual(self.pedido.estado, Pedido.Estado.VENCIDO)
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(self.referencias()[-1], ("entrada", f"Liberación pedido {self.pedido.numero}"))

    def test_respeta_el_plazo(self):
        self.assertIn("Vencidos: 0", self.ejecutar())
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(self.producto.stock, 3)

    @override_settings(PEDIDO_MINUTOS_RESERVA=1)
    def test_el_plazo_es_configurable(self):
        self.agregar()
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        nuevo = Pedido.objects.get(numero=2)
        self.assertLess(nuevo.expira_en, timezone.now() + timedelta(minutes=2))

    def test_no_toca_pedidos_pagados(self):
        marcar_pagado(self.pedido)
        self.vencido_hace(10)
        self.ejecutar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)
        self.assertEqual(self.producto.stock, 3)

    def test_ejecutarlo_dos_veces_no_devuelve_dos_veces(self):
        self.vencido_hace(1)
        self.ejecutar()
        self.assertIn("Vencidos: 0", self.ejecutar())
        self.assertEqual(self.producto.stock, 5)

    def test_transaccion_pending_antes_del_limite_espera(self):
        self.buscar.return_value = transaccion(self.intento(), status="PENDING")
        self.vencido_hace(119)
        self.assertIn("Esperando a Wompi: 1", self.ejecutar())
        self.assertEqual(self.pedido.estado, Pedido.Estado.PENDIENTE)
        self.assertEqual(self.producto.stock, 3)

    def test_transaccion_pending_pasado_el_limite_vence(self):
        self.buscar.return_value = transaccion(self.intento(), status="PENDING")
        self.vencido_hace(121)
        self.assertIn("Vencidos: 1", self.ejecutar())
        self.assertEqual(self.pedido.estado, Pedido.Estado.VENCIDO)
        self.assertEqual(self.producto.stock, 5)

    @override_settings(PEDIDO_MAX_ESPERA_PENDIENTE_MINUTOS=5)
    def test_el_limite_de_espera_es_configurable(self):
        self.buscar.return_value = transaccion(self.intento(), status="PENDING")
        self.vencido_hace(6)
        self.assertIn("Vencidos: 1", self.ejecutar())

    def test_pasado_el_limite_el_aprobado_tardio_factura(self):
        pago = self.intento()
        self.buscar.return_value = transaccion(pago, status="PENDING")
        self.vencido_hace(121)
        self.ejecutar()
        aplicar_transaccion(transaccion(pago))
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)
        self.assertEqual(self.producto.stock, 3)
        self.assertEqual(Factura.objects.count(), 1)

    def test_si_wompi_ya_aprobo_queda_pagado(self):
        self.buscar.return_value = transaccion(self.intento())
        self.vencido_hace(1)
        self.assertIn("Pagados al revisar: 1", self.ejecutar())
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)

    def test_si_wompi_no_responde_vence_igual(self):
        self.intento()
        self.buscar.side_effect = WompiNoResponde
        self.vencido_hace(1)
        self.assertIn("Vencidos: 1", self.ejecutar())
        self.assertEqual(self.producto.stock, 5)

    def test_intento_que_nunca_llego_a_wompi_vence(self):
        self.intento()
        self.buscar.return_value = None
        self.vencido_hace(1)
        self.assertIn("Vencidos: 1", self.ejecutar())


class AdminPedidosTests(TestCase):
    def test_filtro_por_estado_encuentra_los_reembolsos(self):
        empresa = Empresa.objects.create(nombre="Una", nit="1", slug="una")
        usuario = Usuario.objects.create_superuser(username="s@c.co", email="s@c.co", password="x")
        crear_pedido_simple(empresa, usuario, numero=1)
        reembolso = crear_pedido_simple(empresa, usuario, numero=2)
        Pedido.objects.filter(pk=reembolso.pk).update(estado=Pedido.Estado.REQUIERE_REEMBOLSO)
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("admin:core_pedido_changelist"), {"estado__exact": "requiere_reembolso"})
        self.assertEqual(list(respuesta.context["cl"].queryset), [reembolso])


class ConcurrenciaPedidosTests(TransactionTestCase):
    """Con hilos y conexiones reales: aquí sí compiten los bloqueos de PostgreSQL."""

    def setUp(self):
        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "111", self.dueno)
        self.producto = crear_producto(self.negocio, stock=10)
        self.compradores = [crear_usuario("a@correo.co"), crear_usuario("b@correo.co")]

    def en_paralelo(self, *funciones):
        barrera = threading.Barrier(len(funciones))
        resultados, errores = [], []

        def correr(funcion):
            try:
                barrera.wait(timeout=15)
                resultados.append(funcion())
            except Exception as error:
                errores.append(error)
            finally:
                connections.close_all()

        hilos = [threading.Thread(target=correr, args=[f]) for f in funciones]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=40)
            self.assertFalse(hilo.is_alive(), "un hilo quedó bloqueado")
        return resultados, errores

    def pedido(self, comprador, cantidad=1):
        producto = Producto.objects.get(pk=self.producto.pk)
        return compras.crear_pedido(
            usuario=comprador, negocio=self.negocio,
            lineas=[{"producto": producto, "cantidad": cantidad}],
            datos={**DATOS_ENVIO, "numero_documento": "1020304"},
        )

    def test_dos_pedidos_simultaneos_reciben_numeros_distintos(self):
        _, errores = self.en_paralelo(*[lambda c=c: self.pedido(c) for c in self.compradores])
        self.assertEqual(errores, [])
        self.assertEqual(sorted(Pedido.objects.values_list("numero", flat=True)), [1, 2])

    def test_la_ultima_unidad_la_obtiene_una_sola_persona(self):
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)
        resultados, errores = self.en_paralelo(*[lambda c=c: self.pedido(c) for c in self.compradores])
        self.assertEqual(len(resultados), 1)
        self.assertEqual([type(e) for e in errores], [StockInsuficiente])
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 0)

    def test_webhook_y_consulta_simultaneos_crean_una_sola_factura(self):
        pedido = self.pedido(self.compradores[0], cantidad=2)
        evento = transaccion(crear_pago_pedido(pedido=pedido))
        _, errores = self.en_paralelo(lambda: aplicar_transaccion(evento), lambda: aplicar_transaccion(evento))
        self.assertEqual(errores, [])
        self.assertEqual(Factura.objects.count(), 1)
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 8)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.PAGADO)

    def test_dos_ejecuciones_simultaneas_liberan_una_sola_vez(self):
        pedido = self.pedido(self.compradores[0], cantidad=2)
        Pedido.objects.filter(pk=pedido.pk).update(expira_en=timezone.now() - timedelta(minutes=1))
        resultados, errores = self.en_paralelo(lambda: compras.vencer_pedido(pedido.pk), lambda: compras.vencer_pedido(pedido.pk))
        self.assertEqual(errores, [])
        self.assertEqual(sorted(resultados), ["omitido", "vencido"])
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 10)
        self.assertEqual(MovimientoInventario.objects.filter(tipo="entrada").count(), 1)


class MarketplaceFase6Tests(PedidoBase):
    """Pruebas de Fase 6: reembolsos reales, comisiones por comercio y logística/seguimiento."""

    def test_flujo_completo_de_reembolso_desde_panel_y_vista_comprador(self):
        pago = self.intento()
        with self.assertLogs("core.pagos", "CRITICAL"):
            aplicar_transaccion({**transaccion(pago), "amount_in_cents": pago.monto_centavos - 100})
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.REQUIERE_REEMBOLSO)

        # Sin referencia falla
        with self.assertRaises(ValueError):
            registrar_reembolso(pedido=self.pedido, usuario=self.dueno, referencia="   ")

        # Desde el panel del negocio el dueño registra el reembolso
        self.client.force_login(self.dueno)
        respuesta = self.client.post(
            reverse("pedidos_panel_detalle", args=[self.pedido.pk]),
            {
                "accion": "reembolsar",
                "referencia": "REV-WOMPI-9001",
                "nota": "Reversión aprobada a tarjeta origen",
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Reembolso registrado")
        self.assertContains(respuesta, "REV-WOMPI-9001")

        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.REEMBOLSADO)
        self.assertEqual(self.pedido.reembolso_referencia, "REV-WOMPI-9001")
        self.assertEqual(self.pedido.reembolso_nota, "Reversión aprobada a tarjeta origen")
        self.assertEqual(self.pedido.reembolsado_por, self.dueno)
        self.assertIsNotNone(self.pedido.reembolsado_en)

        # No permite reembolsar dos veces
        with self.assertRaises(ValueError):
            registrar_reembolso(pedido=self.pedido, usuario=self.dueno, referencia="REV-2")

        # El comprador ve que su reembolso fue procesado con el comprobante
        self.client.force_login(self.comprador)
        vista_comprador = self.client.get(reverse("pedido_detalle", args=[self.pedido.pk]))
        self.assertContains(vista_comprador, "Tu reembolso fue procesado")
        self.assertContains(vista_comprador, "REV-WOMPI-9001")

    def test_comision_y_liquidacion_congeladas_por_pedido(self):
        Empresa.objects.filter(pk=self.negocio.pk).update(comision_porcentaje=Decimal("8.00"))
        self.negocio.refresh_from_db()
        Producto.objects.filter(pk=self.producto.pk).update(
            precio=Decimal("10000.00"), iva_porcentaje=Decimal("19.00"), stock=10
        )
        self.producto.refresh_from_db()

        nuevo = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 2}],
            datos=DATOS_ENVIO,
        )
        # 2 * 10.000 = 20.000 + 3.800 IVA = 23.800. Comisión 8% de 23.800 = 1.904. Neto = 21.896
        self.assertEqual(nuevo.subtotal, Decimal("20000.00"))
        self.assertEqual(nuevo.iva, Decimal("3800.00"))
        self.assertEqual(nuevo.total, Decimal("23800.00"))
        self.assertEqual(nuevo.comision_porcentaje, Decimal("8.00"))
        self.assertEqual(nuevo.comision_valor, Decimal("1904.00"))
        self.assertEqual(nuevo.neto_vendedor, Decimal("21896.00"))

        # Si el negocio cambia su comisión mañana, el pedido existente conserva su liquidación
        Empresa.objects.filter(pk=self.negocio.pk).update(comision_porcentaje=Decimal("12.00"))
        marcar_pagado(nuevo)

        self.client.force_login(self.dueno)
        panel = self.client.get(reverse("pedidos_panel_lista"))
        self.assertEqual(panel.status_code, 200)
        liquidacion = panel.context["liquidacion"]
        self.assertEqual(liquidacion["bruto"], Decimal("23800.00"))
        self.assertEqual(liquidacion["comision"], Decimal("1904.00"))
        self.assertEqual(liquidacion["neto"], Decimal("21896.00"))
        self.assertEqual(liquidacion["cantidad"], 1)

    def test_calculo_envio_por_peso_y_umbral_envio_gratis(self):
        Empresa.objects.filter(pk=self.negocio.pk).update(
            tarifa_envio_base=Decimal("5000.00"),
            tarifa_envio_por_kg=Decimal("2000.00"),
            envio_gratis_desde=Decimal("50000.00"),
            comision_porcentaje=Decimal("5.00"),
        )
        self.negocio.refresh_from_db()
        Producto.objects.filter(pk=self.producto.pk).update(
            precio=Decimal("10000.00"),
            iva_porcentaje=Decimal("0.00"),
            peso_gramos=600,
            stock=10,
        )
        self.producto.refresh_from_db()

        # 2 unidades = $20.000 y 1.200 g (2 kg redondeados hacia arriba) -> envío = 5.000 + 2 * 2.000 = $9.000
        pedido_con_envio = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 2}],
            datos=DATOS_ENVIO,
        )
        self.assertEqual(pedido_con_envio.peso_total_gramos, 1200)
        self.assertEqual(pedido_con_envio.costo_envio, Decimal("9000.00"))
        self.assertEqual(pedido_con_envio.total, Decimal("29000.00"))
        # La comisión se calcula sobre los productos ($20.000 * 5% = $1.000); el envío va íntegro al comercio
        self.assertEqual(pedido_con_envio.comision_valor, Decimal("1000.00"))
        self.assertEqual(pedido_con_envio.neto_vendedor, Decimal("28000.00"))

        # 5 unidades = $50.000 >= envio_gratis_desde ($50.000) -> envío gratis ($0)
        pedido_gratis = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 5}],
            datos=DATOS_ENVIO,
        )
        self.assertEqual(pedido_gratis.costo_envio, Decimal("0.00"))
        self.assertEqual(pedido_gratis.total, Decimal("50000.00"))

    def test_seguimiento_logistico_de_despacho_y_entrega(self):
        # No permite despachar un pedido aún no pagado
        with self.assertRaises(ValueError):
            actualizar_envio_pedido(
                pedido=self.pedido,
                estado_envio=Pedido.EstadoEnvio.ENVIADO,
                transportadora="Servientrega",
                numero_guia="GUIA-123",
            )

        marcar_pagado(self.pedido)
        self.client.force_login(self.dueno)
        respuesta = self.client.post(
            reverse("pedidos_panel_detalle", args=[self.pedido.pk]),
            {
                "accion": "actualizar_envio",
                "estado_envio": Pedido.EstadoEnvio.ENVIADO,
                "transportadora": "Servientrega",
                "numero_guia": "GUIA-778899",
            },
            follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.recargar()
        self.assertEqual(self.pedido.estado_envio, Pedido.EstadoEnvio.ENVIADO)
        self.assertEqual(self.pedido.transportadora, "Servientrega")
        self.assertEqual(self.pedido.numero_guia, "GUIA-778899")
        self.assertIsNotNone(self.pedido.enviado_en)
        self.assertIsNone(self.pedido.entregado_en)

        # El comprador ve la transportadora y la guía en el detalle de su pedido
        self.client.force_login(self.comprador)
        vista_comprador = self.client.get(reverse("pedido_detalle", args=[self.pedido.pk]))
        self.assertContains(vista_comprador, "Servientrega")
        self.assertContains(vista_comprador, "GUIA-778899")

        # Al marcar entregado queda registrada la fecha de entrega
        actualizar_envio_pedido(
            pedido=self.pedido,
            estado_envio=Pedido.EstadoEnvio.ENTREGADO,
            transportadora="Servientrega",
            numero_guia="GUIA-778899",
        )
        self.recargar()
        self.assertEqual(self.pedido.estado_envio, Pedido.EstadoEnvio.ENTREGADO)
        self.assertIsNotNone(self.pedido.entregado_en)

    def test_notificaciones_por_correo_en_pago_despacho_y_reembolso(self):
        from django.core import mail

        mail.outbox.clear()
        marcar_pagado(self.pedido)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"Pedido #{self.pedido.numero}", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, [self.pedido.email])

        # Estado 'preparando' no envía correo; 'enviado' sí envía con guía
        mail.outbox.clear()
        actualizar_envio_pedido(
            pedido=self.pedido,
            estado_envio=Pedido.EstadoEnvio.PREPARANDO,
        )
        self.assertEqual(len(mail.outbox), 0)

        actualizar_envio_pedido(
            pedido=self.pedido,
            estado_envio=Pedido.EstadoEnvio.ENVIADO,
            transportadora="Coordinadora",
            numero_guia="COORD-5544",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Enviado", mail.outbox[0].subject)
        self.assertIn("COORD-5544", mail.outbox[0].body)

        # Reembolso envía correo con el comprobante
        otro = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 1}],
            datos=DATOS_ENVIO,
        )
        Pedido.objects.filter(pk=otro.pk).update(estado=Pedido.Estado.REQUIERE_REEMBOLSO)
        otro.refresh_from_db()
        mail.outbox.clear()
        registrar_reembolso(
            pedido=otro,
            usuario=self.dueno,
            referencia="REV-CORREO-01",
            nota="Devolución aprobada",
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Reembolso procesado", mail.outbox[0].subject)
        self.assertIn("REV-CORREO-01", mail.outbox[0].body)

    def test_permisos_en_panel_de_pedidos(self):
        from .models import Membresia, Permiso, Rol

        lector = crear_usuario("solo-lectura-pedidos@correo.co")
        rol_ver = Rol.objects.create(empresa=self.negocio, nombre="Auditor Ventas", es_admin=False)
        perm_ver, _ = Permiso.objects.get_or_create(codigo="ventas.ver", defaults={"descripcion": "Ver ventas"})
        rol_ver.permisos.add(perm_ver)
        Membresia.objects.create(usuario=lector, empresa=self.negocio, rol=rol_ver)

        marcar_pagado(self.pedido)
        self.client.force_login(lector)
        self.assertEqual(self.client.get(reverse("pedidos_panel_lista")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("pedidos_panel_detalle", args=[self.pedido.pk])).status_code,
            200,
        )
        # No puede actualizar despacho ni registrar reembolsos con solo ventas.ver
        self.assertEqual(
            self.client.post(
                reverse("pedidos_panel_detalle", args=[self.pedido.pk]),
                {"accion": "actualizar_envio", "estado_envio": "enviado"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("pedidos_panel_detalle", args=[self.pedido.pk]),
                {"accion": "reembolsar", "referencia": "REV-X"},
            ).status_code,
            403,
        )


