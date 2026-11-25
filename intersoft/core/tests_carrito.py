"""Pruebas de carrito persistente multi-dispositivo (ItemCarrito) y fusión al iniciar sesión."""
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from .models import ItemCarrito, Producto, Usuario
from .negocios import registrar_negocio
from .testing_pagos import conectar_pruebas


class CarritoPersistenteTests(TestCase):
    def setUp(self):
        self.dueno = Usuario.objects.create_user(
            username="dueno@tienda.co", email="dueno@tienda.co", password="Password123*", first_name="Luis"
        )
        self.negocio = registrar_negocio(
            usuario=self.dueno,
            datos={
                "nombre": "Tienda Multi",
                "nit": "900555666-1",
                "email": "multi@tienda.co",
                "telefono": "3002223344",
                "direccion": "Calle 5 # 10-20",
            },
        )
        conectar_pruebas(self.negocio)
        self.comprador = Usuario.objects.create_user(
            username="comprador@correo.co", email="comprador@correo.co", password="Password123*", first_name="Sofia"
        )
        self.prod_a = Producto.objects.create(
            empresa=self.negocio,
            codigo="P-A",
            nombre="Mouse Inalámbrico",
            precio=Decimal("80000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=10,
            publicado=True,
            activo=True,
        )
        self.prod_b = Producto.objects.create(
            empresa=self.negocio,
            codigo="P-B",
            nombre="Base Refrigerante",
            precio=Decimal("60000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=5,
            publicado=True,
            activo=True,
        )

    def test_sincronizacion_entre_dos_dispositivos(self):
        dispositivo_1 = Client()
        dispositivo_2 = Client()

        # Dispositivo 1 agrega 2 unidades de prod_a
        dispositivo_1.force_login(self.comprador)
        dispositivo_1.post(reverse("carrito_agregar", args=[self.prod_a.pk]), {"cantidad": 2})
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.prod_a).cantidad, 2)

        # Dispositivo 2 (otra sesión distinta) inicia sesión y ve exactamente las 2 unidades
        dispositivo_2.force_login(self.comprador)
        resp = dispositivo_2.get(reverse("carrito"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mouse Inalámbrico")
        self.assertEqual(resp.context["grupos"][0]["unidades"], 2)

        # Dispositivo 2 actualiza a 3 unidades -> Dispositivo 1 también ve 3
        dispositivo_2.post(reverse("carrito_actualizar", args=[self.prod_a.pk]), {"cantidad": 3})
        resp_1 = dispositivo_1.get(reverse("carrito"))
        self.assertEqual(resp_1.context["grupos"][0]["unidades"], 3)

    def test_fusion_de_carrito_invitado_al_iniciar_sesion(self):
        # Ya tenía 1 unidad de prod_a guardada en BD desde otro dispositivo
        ItemCarrito.objects.create(usuario=self.comprador, producto=self.prod_a, cantidad=1)

        # En un navegador nuevo como invitado agrega 2 de prod_a y 1 de prod_b
        navegador = Client()
        navegador.post(reverse("carrito_agregar", args=[self.prod_a.pk]), {"cantidad": 2})
        navegador.post(reverse("carrito_agregar", args=[self.prod_b.pk]), {"cantidad": 1})

        # Inicia sesión -> se fusionan (prod_a=3, prod_b=1) y se limpia la sesión temporal
        navegador.force_login(self.comprador)
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.prod_a).cantidad, 3)
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.prod_b).cantidad, 1)

        resp = navegador.get(reverse("carrito"))
        self.assertEqual(resp.context["grupos"][0]["unidades"], 4)

    def test_ajuste_de_stock_actualiza_bd(self):
        ItemCarrito.objects.create(usuario=self.comprador, producto=self.prod_b, cantidad=4)
        # Baja el stock a 2
        Producto.objects.filter(pk=self.prod_b.pk).update(stock=2)
        self.prod_b.existencias.update(cantidad=2)

        cliente = Client()
        cliente.force_login(self.comprador)
        resp = cliente.get(reverse("carrito"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.prod_b).cantidad, 2)
