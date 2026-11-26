"""Prueba de CAJA BLANCA de rendimiento (QA 2026-11-24): consultas a la base de datos por página.

Cada página clave se carga con pocos registros y con muchos. Si el número de consultas crece con la cantidad de
datos, hay un problema «N+1»: la página se vuelve más lenta a medida que el negocio crece.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import Cliente, Factura, Pedido, Producto, Usuario
from core.testing_pagos import conectar_pruebas
from plataforma.models import RolPlataforma

from .tests_compra import crear_negocio, crear_usuario

TOLERANCIA = 4   # consultas extra aceptables entre 3 y 30 registros (sesión, caché, etc.)


class ConsultasPorPaginaTests(TestCase):
    def setUp(self):
        self.duena = crear_usuario("duena@consultas.co", "Marta")
        self.negocio = crear_negocio("Pastelería Consultas", "900", self.duena)
        conectar_pruebas(self.negocio)
        self.cliente_f = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC",
                                                numero_documento="1", nombre="Cliente")
        self.creados = 0

    def poblar(self, hasta):
        while self.creados < hasta:
            i = self.creados
            producto = Producto.objects.create(empresa=self.negocio, codigo=f"P{i}", nombre=f"Producto {i}",
                                               precio=Decimal("1000"), stock=5, publicado=True)
            comprador = Usuario.objects.create_user(username=f"c{i}@x.co", email=f"c{i}@x.co", password="x", first_name="Ana", last_name="Prueba")
            Pedido.objects.create(empresa=self.negocio, comprador=comprador, numero=i + 1, total=Decimal("1190"),
                                  estado=Pedido.Estado.PAGADO, expira_en=timezone.now() + timedelta(minutes=30),
                                  tipo_documento="CC", numero_documento="1", nombre="N", email="n@x.co",
                                  telefono="3", departamento="D", ciudad="C", direccion="X")
            Factura.objects.create(empresa=self.negocio, numero=i + 1, cliente=self.cliente_f,
                                   creada_por=self.duena, total=Decimal("1190"))
            del producto
            self.creados += 1

    def contar(self, cliente, url):
        with CaptureQueriesContext(connection) as consultas:
            respuesta = cliente.get(url)
        self.assertEqual(respuesta.status_code, 200, url)
        return len(consultas)

    def medir(self, cliente, url):
        self.poblar(3)
        pocos = self.contar(cliente, url)
        self.poblar(30)
        muchos = self.contar(cliente, url)
        return pocos, muchos

    def assertSinNmas1(self, cliente, url):
        pocos, muchos = self.medir(cliente, url)
        self.assertLessEqual(muchos - pocos, TOLERANCIA,
                             f"{url}: {pocos} consultas con 3 registros y {muchos} con 30 (posible N+1)")

    def test_marketplace(self):
        from django.test import Client
        self.assertSinNmas1(Client(), reverse("marketplace"))

    def test_tienda_del_negocio(self):
        from django.test import Client
        self.assertSinNmas1(Client(), reverse("tienda_negocio", args=[self.negocio.slug]))

    def test_panel(self):
        self.client.force_login(self.duena)
        for nombre in ("dashboard", "productos_lista", "pedidos_panel_lista", "facturas_lista"):
            with self.subTest(pagina=nombre):
                self.creados = Producto.objects.filter(empresa=self.negocio).count()
                self.assertSinNmas1(self.client, reverse(nombre))

    def test_consola_negocios(self):
        jefe = Usuario.objects.create_user(username="jefe@x.co", email="jefe@x.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba")
        RolPlataforma.objects.create(usuario=jefe, rol=RolPlataforma.Rol.DUENO, activo=True)
        self.client.force_login(jefe)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(jefe.pk)
        sesion.save()
        for i in range(3):
            crear_negocio(f"Extra {i}", f"91{i}", crear_usuario(f"e{i}@x.co"))
        pocos = self.contar(self.client, reverse("plataforma_negocios"))
        for i in range(3, 25):
            crear_negocio(f"Extra {i}", f"91{i}", crear_usuario(f"e{i}@x.co"))
        muchos = self.contar(self.client, reverse("plataforma_negocios"))
        self.assertLessEqual(muchos - pocos, TOLERANCIA, f"Negocios: {pocos} → {muchos} consultas (posible N+1)")
