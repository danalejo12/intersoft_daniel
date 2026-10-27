"""
Pruebas automáticas de Intersoft.
Ejecutar:  python manage.py test core
"""
from decimal import Decimal

from django.test import TestCase

from .forms import ProductoForm
from .models import Cliente, Empresa, Factura, MovimientoInventario, Producto, Usuario
from .services import StockInsuficiente, anular_factura, crear_factura, registrar_movimiento

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

class InventarioTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Empresa Inv", nit="900000010", slug="empresa-inv")
        self.usuario = Usuario.objects.create_user(username="i@test.co", email="i@test.co", password="x")
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="A1", nombre="Arroz", precio=Decimal("3000"), stock=0
        )

    def mover(self, tipo, cantidad):
        return registrar_movimiento(
            empresa=self.empresa, producto=self.producto, tipo=tipo, cantidad=cantidad, usuario=self.usuario
        )

    def test_entrada_y_ajuste_cambian_el_stock(self):
        self.mover(MovimientoInventario.Tipo.ENTRADA, 20)
        self.mover(MovimientoInventario.Tipo.AJUSTE, -3)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 17)
        self.assertEqual(MovimientoInventario.objects.filter(producto=self.producto).count(), 2)

    def test_ajuste_que_deja_negativo_no_registra_nada(self):
        self.mover(MovimientoInventario.Tipo.ENTRADA, 5)
        with self.assertRaises(StockInsuficiente):
            self.mover(MovimientoInventario.Tipo.AJUSTE, -6)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(MovimientoInventario.objects.filter(producto=self.producto).count(), 1)

    def test_codigo_repetido_en_la_misma_empresa_es_invalido(self):
        form = ProductoForm(
            data={"codigo": "a1", "nombre": "Otro", "precio": "100", "iva_porcentaje": "19", "stock_minimo": "0"},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("codigo", form.errors)