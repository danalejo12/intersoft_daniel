"""Pedidos con reserva: la factura nace con el pago."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from .models import Cliente, Empresa, Factura, Pago, Pedido
from .services import crear_factura

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

    def migrar(self):
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(self.DESPUES)

    def test_adapta_los_tres_casos_y_no_toca_las_demas_facturas(self):
        pagada = self.factura(1)
        self.Pago_.objects.create(empresa=self.empresa, factura=pagada, referencia="R-1", monto_centavos=238000, estado="aprobado")
        self.factura(2, estado="anulada")
        sin_pagar = self.factura(3)
        self.Pago_.objects.create(empresa=self.empresa, factura=sin_pagar, referencia="R-3", monto_centavos=238000)
        suelta = self.factura(4, con_pedido=False)

        self.migrar()

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
        from .models import MovimientoInventario, Producto
        self.assertEqual(Producto.objects.get(pk=self.producto.pk).stock, 5)
        movimiento = MovimientoInventario.objects.get()
        self.assertEqual((movimiento.tipo, movimiento.referencia), ("entrada", "Liberación pedido 3"))

        self.assertEqual(Factura.objects.get(pk=suelta.pk).estado, "emitida")
