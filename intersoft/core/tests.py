"""
Pruebas automáticas de Intersoft.
Ejecutar:  python manage.py test core
"""
from decimal import Decimal

from django.test import TestCase

from .models import Cliente, Empresa, Factura, MovimientoInventario, Producto, Usuario
from .services import StockInsuficiente, anular_factura, crear_factura


class FacturacionTests(TestCase):
    def setUp(self):
        # setUp se ejecuta ANTES de cada prueba, con una base de datos limpia
        self.empresa = Empresa.objects.create(nombre="Empresa Test", nit="900000001", slug="empresa-test")
        self.usuario = Usuario.objects.create_user(username="v@test.co", email="v@test.co", password="x")
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente Test"
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="P1", nombre="Producto Test",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )

    def vender(self, cantidad):
        return crear_factura(
            empresa=self.empresa, usuario=self.usuario, cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": cantidad}],
        )

    def test_calcula_totales_y_descuenta_stock(self):
        factura = self.vender(3)
        self.producto.refresh_from_db()   # vuelve a leer el producto desde la base
        self.assertEqual(factura.subtotal, Decimal("3000.00"))
        self.assertEqual(factura.iva, Decimal("570.00"))
        self.assertEqual(factura.total, Decimal("3570.00"))
        self.assertEqual(self.producto.stock, 7)
        self.assertEqual(MovimientoInventario.objects.count(), 1)

    def test_stock_insuficiente_no_deja_nada_a_medias(self):
        with self.assertRaises(StockInsuficiente):
            self.vender(11)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(Factura.objects.count(), 0)

    def test_consecutivo(self):
        self.assertEqual(self.vender(1).numero, 1)
        self.assertEqual(self.vender(1).numero, 2)

    def test_anular_devuelve_el_stock(self):
        factura = self.vender(4)
        anular_factura(factura=factura, usuario=self.usuario)
        self.producto.refresh_from_db()
        factura.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(factura.estado, Factura.Estado.ANULADA)

    def test_no_vende_producto_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", nit="900000002", slug="otra")
        ajeno = Producto.objects.create(empresa=otra, codigo="X", nombre="Ajeno", precio=Decimal("5"), stock=5)
        with self.assertRaises(ValueError):
            crear_factura(
                empresa=self.empresa, usuario=self.usuario, cliente=self.cliente,
                items=[{"producto": ajeno, "cantidad": 1}],
            )
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.stock, 5)