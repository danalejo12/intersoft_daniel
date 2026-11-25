"""Pruebas de rate limiting HTTP 429 y límite anti-acaparamiento de inventario en pedidos."""
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from . import compras, reservas
from .models import Pedido, Producto, Usuario
from .negocios import registrar_negocio
from .testing_pagos import conectar_pruebas

DATOS_ENVIO = {
    "tipo_documento": "CC",
    "numero_documento": "10101010",
    "nombre": "Ana Limite",
    "email": "ana-rl@ejemplo.co",
    "telefono": "3001234567",
    "departamento": "Antioquia",
    "ciudad": "Medellín",
    "direccion": "Calle 10 # 20-30",
    "indicaciones": "",
}


class RateLimitYAntiAcaparamientoTests(TestCase):
    """Verifica límites de tasa HTTP 429 y tope de pedidos pendientes simultáneos."""

    def setUp(self):
        cache.clear()
        self.dueno = Usuario.objects.create_user(
            username="rl-dueno@alfa.co", email="rl-dueno@alfa.co", password="Password123*", first_name="Dueño"
        )
        self.negocio = registrar_negocio(
            usuario=self.dueno,
            datos={
                "nombre": "Tienda RL",
                "nit": "900777111-1",
                "email": "rl@tienda.co",
                "telefono": "3007771122",
                "direccion": "Calle 7 # 8-9",
            },
        )
        conectar_pruebas(self.negocio)
        self.comprador = Usuario.objects.create_user(
            username="ana-rl@ejemplo.co", email="ana-rl@ejemplo.co", password="Password123*", first_name="Ana"
        )
        self.producto = Producto.objects.create(
            empresa=self.negocio,
            codigo="RL-1",
            nombre="Producto RL",
            precio=Decimal("20000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=20,
            publicado=True,
            activo=True,
        )

    def test_rate_limit_recuperar_contrasena_devuelve_429(self):
        """Más de 6 solicitudes en 15 min a /recuperar-contrasena/ devuelven HTTP 429 con Retry-After."""
        url = reverse("password_reset")
        for _ in range(6):
            resp = self.client.post(url, {"email": "nadie@ejemplo.co"})
            self.assertNotEqual(resp.status_code, 429)
        resp_7 = self.client.post(url, {"email": "nadie@ejemplo.co"})
        self.assertEqual(resp_7.status_code, 429)
        self.assertIn("Retry-After", resp_7)

    def test_rate_limit_pqrs_y_soporte_por_usuario(self):
        """Más de 10 POST en 15 min a /pqrs/nueva/ o /soporte/reportar/ devuelven HTTP 429."""
        self.client.force_login(self.comprador)
        url_pqrs = reverse("pqrs_radicar")
        for _ in range(10):
            resp = self.client.post(url_pqrs, {})
            self.assertNotEqual(resp.status_code, 429)
        self.assertEqual(self.client.post(url_pqrs, {}).status_code, 429)

        url_sop = reverse("soporte_reportar_problema")
        for _ in range(10):
            resp = self.client.post(url_sop, {})
            self.assertNotEqual(resp.status_code, 429)
        self.assertEqual(self.client.post(url_sop, {}).status_code, 429)

    @override_settings(PEDIDO_MAX_PENDIENTES_POR_COMPRADOR=3)
    def test_tope_pedidos_pendientes_evita_acaparamiento_stock(self):
        """Un comprador no puede acumular más pedidos pendientes simultáneos que el tope configurado."""
        creados = []
        for _ in range(3):
            creados.append(
                compras.crear_pedido(
                    usuario=self.comprador,
                    negocio=self.negocio,
                    lineas=[{"producto": self.producto, "cantidad": 1}],
                    datos=DATOS_ENVIO,
                )
            )
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.crear_pedido(
                usuario=self.comprador,
                negocio=self.negocio,
                lineas=[{"producto": self.producto, "cantidad": 1}],
                datos=DATOS_ENVIO,
            )

        # Al cancelar uno, puede volver a crear otro pedido
        reservas.liberar_pedido(creados[0], Pedido.Estado.CANCELADO)
        nuevo = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 1}],
            datos=DATOS_ENVIO,
        )
        self.assertEqual(nuevo.estado, Pedido.Estado.PENDIENTE)
