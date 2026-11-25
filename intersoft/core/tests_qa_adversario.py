"""Pruebas adversarias de QA: fuzzing de UUIDs, borde $0 Wompi, sesión corrupta y XSS en correos."""
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from . import compras, reservas
from .models import CuponTienda, ItemCarrito, Producto, Usuario
from .negocios import registrar_negocio
from .testing_pagos import conectar_pruebas

DATOS_ENVIO = {
    "tipo_documento": "CC",
    "numero_documento": "10101010",
    "nombre": "Ana QA",
    "email": "ana-qa@ejemplo.co",
    "telefono": "3001234567",
    "departamento": "Antioquia",
    "ciudad": "Medellín",
    "direccion": "Calle 10 # 20-30",
    "indicaciones": "",
}


class QAAdversarioTests(TestCase):
    """Intenta romper el sistema con entradas maliciosas, UUIDs corruptos y casos borde financieros."""

    def setUp(self):
        self.dueno = Usuario.objects.create_user(
            username="qa-dueno@alfa.co", email="qa-dueno@alfa.co", password="Password123*", first_name="QA"
        )
        self.negocio = registrar_negocio(
            usuario=self.dueno,
            datos={
                "nombre": "QA Store",
                "nit": "900888777-1",
                "email": "qa@store.co",
                "telefono": "3007778899",
                "direccion": "Calle QA # 1-2",
            },
        )
        conectar_pruebas(self.negocio)
        self.comprador = Usuario.objects.create_user(
            username="ana-qa@ejemplo.co", email="ana-qa@ejemplo.co", password="Password123*", first_name="Ana"
        )
        self.producto = Producto.objects.create(
            empresa=self.negocio,
            codigo="QA-1",
            nombre="Producto QA",
            precio=Decimal("10000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=10,
            publicado=True,
            activo=True,
        )

    def test_uuids_corruptos_en_post_nunca_dan_500(self):
        """Enviar basura o SQLi en campos *_id por POST debe devolver 404 limpio, nunca HTTP 500."""
        self.client.force_login(self.dueno)
        url_cupones = reverse("cupones_panel")
        for malo in ("no-es-uuid", "", "' OR 1=1 --", "<script>alert(1)</script>"):
            resp_toggle = self.client.post(url_cupones, {"accion": "toggle", "cupon_id": malo})
            self.assertEqual(resp_toggle.status_code, 404)
            resp_del = self.client.post(url_cupones, {"accion": "eliminar", "cupon_id": malo})
            self.assertEqual(resp_del.status_code, 404)

    def test_cupon_no_puede_dejar_total_bajo_minimo_wompi(self):
        """Un cupón de 100% o monto mayor al pedido no puede crear un pedido impagable ($0) en Wompi."""
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="GRATIS100",
            tipo=CuponTienda.Tipo.PORCENTAJE,
            valor=Decimal("100"),
        )
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="BAJO1500",
            tipo=CuponTienda.Tipo.FIJO,
            valor=Decimal("9000"),
        )
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.evaluar_cupon(negocio=self.negocio, codigo="GRATIS100", total_productos=Decimal("10000"))
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.crear_pedido(
                usuario=self.comprador,
                negocio=self.negocio,
                lineas=[{"producto": self.producto, "cantidad": 1}],
                datos=DATOS_ENVIO,
                codigo_cupon="BAJO1500",
            )

    def test_sesion_carrito_corrupta_no_rompe_carrito_ni_login(self):
        """Claves no-UUID o cantidades inválidas en session['carrito'] se descartan sin HTTP 500."""
        cliente = Client()
        sesion = cliente.session
        sesion["carrito"] = {"basura-no-uuid": 2, str(self.producto.pk): 1}
        sesion.save()

        # Invitado ve /carrito/ sin 500 y conserva el producto válido
        resp_inv = cliente.get(reverse("carrito"))
        self.assertEqual(resp_inv.status_code, 200)
        self.assertEqual(resp_inv.context["grupos"][0]["unidades"], 1)

        # Inyecta otra clave corrupta antes de iniciar sesión -> fusión no da 500
        sesion = cliente.session
        sesion["carrito"] = {"otra-basura": "nan", str(self.producto.pk): 2}
        sesion.save()
        cliente.force_login(self.comprador)
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.producto).cantidad, 2)

    def test_xss_en_transportadora_escapado_en_correo_html(self):
        """Cualquier etiqueta HTML en transportadora o guía se escapa en el correo HTML."""
        pedido = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 1}],
            datos=DATOS_ENVIO,
        )
        reservas.marcar_pagado(pedido)
        mail.outbox.clear()

        reservas.actualizar_envio_pedido(
            pedido=pedido,
            estado_envio="enviado",
            transportadora='<script>alert("xss")</script>',
            numero_guia="<b>G-1</b>",
        )
        self.assertEqual(len(mail.outbox), 1)
        html, _ = mail.outbox[0].alternatives[0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>G-1</b>", html)

    def test_filtros_get_corruptos_en_pqrs_tienda_y_panel_no_dan_500(self):
        """Parámetros GET maliciosos (UUID inválido, fechas imposibles, páginas basura) nunca causan 500."""
        self.client.force_login(self.comprador)
        for ruta in (
            f"{reverse('pqrs_radicar')}?pedido=no-es-uuid",
            f"{reverse('pqrs_radicar')}?pedido=' OR 1=1 --",
            f"{reverse('marketplace')}?categoria=<script>&orden=invalido&page=abc",
            f"{reverse('mis_pedidos')}?estado=invalido&page=-5",
        ):
            resp = self.client.get(ruta)
            self.assertNotEqual(resp.status_code, 500, f"HTTP 500 inesperado en {ruta}")

        self.client.force_login(self.dueno)
        for ruta in (
            f"{reverse('dashboard')}?bodega=no-es-uuid",
            f"{reverse('pedidos_panel_lista')}?estado=basura&envio=basura&page=xyz",
        ):
            resp = self.client.get(ruta)
            self.assertNotEqual(resp.status_code, 500, f"HTTP 500 inesperado en {ruta}")
