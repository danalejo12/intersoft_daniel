"""
Pruebas automáticas de Intersoft.
Ejecutar:  python manage.py test core
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .forms import ProductoForm
from .models import Cliente, Empresa, Factura, Membresia, MovimientoInventario, Producto, Rol, Usuario
from .services import StockInsuficiente, anular_factura, crear_factura, registrar_movimiento
from django.db import IntegrityError, transaction

from .models import Pago
from .pagos import PagoNoPermitido, calcular_firma_integridad, crear_pago, monto_en_centavos

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


class EliminacionTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000020", slug="mia")
        self.ajena = Empresa.objects.create(nombre="Ajena", nit="900000021", slug="ajena")
        usuario = Usuario.objects.create_user(username="a@test.co", email="a@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(usuario)
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Mío"
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="E1", nombre="Producto", precio=Decimal("1000"), stock=5
        )

    def test_post_desactiva_cliente_sin_borrarlo(self):
        self.client.post(reverse("clientes_eliminar", args=[self.cliente.pk]))
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.activo)

    def test_post_desactiva_producto_sin_borrarlo(self):
        self.client.post(reverse("productos_eliminar", args=[self.producto.pk]))
        self.producto.refresh_from_db()
        self.assertFalse(self.producto.activo)

    def test_get_no_elimina(self):
        respuesta = self.client.get(reverse("clientes_eliminar", args=[self.cliente.pk]))
        self.assertEqual(respuesta.status_code, 405)
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.activo)

    def test_no_elimina_datos_de_otra_empresa(self):
        ajeno = Cliente.objects.create(
            empresa=self.ajena, tipo_documento="CC", numero_documento="2", nombre="Ajeno"
        )
        respuesta = self.client.post(reverse("clientes_eliminar", args=[ajeno.pk]))
        self.assertEqual(respuesta.status_code, 404)
        ajeno.refresh_from_db()
        self.assertTrue(ajeno.activo)
# pago -- pago 
class PagoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Empresa Pago", nit="900000030", slug="empresa-pago")
        self.usuario = Usuario.objects.create_user(username="p@test.co", email="p@test.co", password="x")
        cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente"
        )
        producto = Producto.objects.create(
            empresa=self.empresa, codigo="P1", nombre="Producto",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )
        self.factura = crear_factura(
            empresa=self.empresa, usuario=self.usuario, cliente=cliente,
            items=[{"producto": producto, "cantidad": 3}],
        )

    def test_firma_coincide_con_ejemplo_oficial_de_wompi(self):
        firma = calcular_firma_integridad(
            referencia="sk8-438k4-xmxm392-sn2m",
            monto_centavos=2490000,
            moneda="COP",
            secreto="prod_integrity_Z5mMke9x0k8gpErbDqwrJXMqsI6SFli6",
        )
        self.assertEqual(firma, "37c8407747e595535433ef8f6a811d853cd943046624a0ec04662b17bbf33bf5")

    def test_convierte_a_centavos(self):
        self.assertEqual(monto_en_centavos(Decimal("3570.00")), 357000)

    def test_el_monto_sale_de_la_factura(self):
        pago = crear_pago(factura=self.factura)
        self.assertEqual(pago.monto_centavos, 357000)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)
        self.assertEqual(pago.empresa_id, self.empresa.id)

    def test_no_cobra_factura_anulada(self):
        anular_factura(factura=self.factura, usuario=self.usuario)
        with self.assertRaises(PagoNoPermitido):
            crear_pago(factura=self.factura)

    def test_no_cobra_factura_ya_pagada(self):
        pago = crear_pago(factura=self.factura)
        pago.estado = Pago.Estado.APROBADO
        pago.save()
        with self.assertRaises(PagoNoPermitido):
            crear_pago(factura=self.factura)

    def test_la_base_impide_dos_pagos_aprobados(self):
        primero = crear_pago(factura=self.factura)
        segundo = crear_pago(factura=self.factura)
        primero.estado = Pago.Estado.APROBADO
        primero.save()
        segundo.estado = Pago.Estado.APROBADO
        with self.assertRaises(IntegrityError), transaction.atomic():
            segundo.save()