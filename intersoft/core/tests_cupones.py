"""Pruebas de cupones de descuento por negocio en /panel/cupones/ y checkout del Marketplace."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import compras, reservas
from .models import CuponTienda, Pedido, Producto, Usuario
from .negocios import registrar_negocio
from .testing_pagos import conectar_pruebas

DATOS_ENVIO = {
    "tipo_documento": "CC",
    "numero_documento": "10101010",
    "nombre": "Ana Compradora",
    "email": "ana@ejemplo.co",
    "telefono": "3001234567",
    "departamento": "Antioquia",
    "ciudad": "Medellín",
    "direccion": "Calle 10 # 20-30",
    "indicaciones": "Apto 401",
}


class CuponesTiendaTests(TestCase):
    def setUp(self):
        self.dueno = Usuario.objects.create_user(
            username="dueno@alfa.co", email="dueno@alfa.co", password="Password123*", first_name="Carlos"
        )
        self.negocio = registrar_negocio(
            usuario=self.dueno,
            datos={
                "nombre": "Tienda Alfa",
                "nit": "900111222-1",
                "email": "alfa@negocio.co",
                "telefono": "3001112233",
                "direccion": "Calle 1 # 2-3",
            },
        )
        conectar_pruebas(self.negocio)
        otro_dueno = Usuario.objects.create_user(
            username="dueno@beta.co", email="dueno@beta.co", password="Password123*", first_name="Luis"
        )
        self.otra_empresa = registrar_negocio(
            usuario=otro_dueno,
            datos={
                "nombre": "Tienda Beta",
                "nit": "900333444-2",
                "email": "beta@negocio.co",
                "telefono": "3004445566",
                "direccion": "Calle 2 # 3-4",
            },
        )
        self.comprador = Usuario.objects.create_user(
            username="ana@ejemplo.co", email="ana@ejemplo.co", password="Password123*", first_name="Ana"
        )
        self.producto = Producto.objects.create(
            empresa=self.negocio,
            codigo="PROD-1",
            nombre="Teclado Mecánico",
            precio=Decimal("100000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=10,
            publicado=True,
            activo=True,
        )

    def test_panel_crud_cupones_y_validaciones(self):
        self.client.force_login(self.dueno)
        url = reverse("cupones_panel")

        # GET lista vacía
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Crear cupón porcentaje 10%
        resp = self.client.post(
            url,
            {
                "accion": "crear",
                "codigo": "bienvenido10",
                "tipo": "porcentaje",
                "valor": "10",
                "monto_minimo": "50000",
                "usos_maximos": "5",
                "activo": "on",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        cupon = CuponTienda.objects.get(empresa=self.negocio, codigo="BIENVENIDO10")
        self.assertEqual(cupon.valor, Decimal("10.00"))
        self.assertEqual(cupon.monto_minimo, Decimal("50000.00"))
        self.assertEqual(cupon.usos_maximos, 5)

        # Rechazar código duplicado
        resp_dup = self.client.post(
            url,
            {"accion": "crear", "codigo": "BIENVENIDO10", "tipo": "porcentaje", "valor": "15", "activo": "on"},
        )
        self.assertEqual(resp_dup.status_code, 400)

        # Rechazar porcentaje > 100
        resp_pct = self.client.post(
            url,
            {"accion": "crear", "codigo": "LOCO150", "tipo": "porcentaje", "valor": "150", "activo": "on"},
        )
        self.assertEqual(resp_pct.status_code, 400)

        # Desactivar y reactivar
        self.client.post(url, {"accion": "toggle", "cupon_id": str(cupon.pk)})
        cupon.refresh_from_db()
        self.assertFalse(cupon.activo)

        # Eliminar sin usos
        self.client.post(url, {"accion": "eliminar", "cupon_id": str(cupon.pk)})
        self.assertFalse(CuponTienda.objects.filter(pk=cupon.pk).exists())

    def test_aislamiento_multitenant_cupones(self):
        cupon_beta = CuponTienda.objects.create(
            empresa=self.otra_empresa,
            codigo="SOLOBETA",
            tipo=CuponTienda.Tipo.FIJO,
            valor=Decimal("10000"),
        )
        self.client.force_login(self.dueno)
        resp = self.client.post(reverse("cupones_panel"), {"accion": "toggle", "cupon_id": str(cupon_beta.pk)})
        self.assertEqual(resp.status_code, 404)

        # Tampoco puede aplicarse en una compra de Tienda Alfa
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.crear_pedido(
                usuario=self.comprador,
                negocio=self.negocio,
                lineas=[{"producto": self.producto, "cantidad": 1}],
                datos=DATOS_ENVIO,
                codigo_cupon="SOLOBETA",
            )

    def test_checkout_aplica_cupon_y_liberar_devuelve_uso(self):
        cupon = CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="PROMO20",
            tipo=CuponTienda.Tipo.PORCENTAJE,
            valor=Decimal("20"),
            monto_minimo=Decimal("50000"),
            usos_maximos=1,
        )
        self.client.force_login(self.comprador)
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})

        # Preview GET con cupón
        resp_get = self.client.get(f"{reverse('checkout', args=[self.negocio.slug])}?cupon=promo20")
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "PROMO20")
        self.assertEqual(resp_get.context["descuento"], Decimal("20000.00"))

        # POST crear pedido con cupón
        datos_post = dict(DATOS_ENVIO, cupon="PROMO20")
        resp_post = self.client.post(reverse("checkout", args=[self.negocio.slug]), datos_post)
        self.assertEqual(resp_post.status_code, 302)

        pedido = Pedido.objects.get(empresa=self.negocio)
        self.assertEqual(pedido.cupon_id, cupon.pk)
        self.assertEqual(pedido.cupon_codigo, "PROMO20")
        self.assertEqual(pedido.descuento, Decimal("20000.00"))
        self.assertEqual(pedido.neto_vendedor, Decimal("80000.00"))

        cupon.refresh_from_db()
        self.assertEqual(cupon.usos_actuales, 1)

        # Ya llegó al límite de 1 uso -> rechaza segundo pedido
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.crear_pedido(
                usuario=self.comprador,
                negocio=self.negocio,
                lineas=[{"producto": self.producto, "cantidad": 1}],
                datos=DATOS_ENVIO,
                codigo_cupon="PROMO20",
            )

        # Al liberar pedido pendiente, se devuelve el uso del cupón
        reservas.liberar_pedido(pedido, Pedido.Estado.CANCELADO)
        cupon.refresh_from_db()
        self.assertEqual(cupon.usos_actuales, 0)

    def test_validaciones_cupon_vencido_y_monto_minimo(self):
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="VENCIDO",
            tipo=CuponTienda.Tipo.FIJO,
            valor=Decimal("5000"),
            vence_en=timezone.now() - timedelta(hours=1),
        )
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="MIN500K",
            tipo=CuponTienda.Tipo.FIJO,
            valor=Decimal("50000"),
            monto_minimo=Decimal("500000"),
        )
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.evaluar_cupon(negocio=self.negocio, codigo="VENCIDO", total_productos=Decimal("100000"))
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.evaluar_cupon(negocio=self.negocio, codigo="MIN500K", total_productos=Decimal("100000"))
