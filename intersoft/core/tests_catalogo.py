"""Marketplace rediseñado: filtros por categoría, orden, valoraciones y modo día / noche."""
from django.test import TestCase
from django.urls import reverse

from .marketplace import negocios_con_valoracion
from .models import Categoria, Comentario
from .tests_compra import crear_negocio, crear_producto, crear_usuario
from .testing_pagos import conectar_pruebas


class CatalogoTests(TestCase):
    def setUp(self):
        self.dueno = crear_usuario("dueno@correo.co")
        self.negocio = crear_negocio("Dulce Hogar", "900123456", self.dueno)
        conectar_pruebas(self.negocio)
        self.tortas = Categoria.objects.create(empresa=self.negocio, nombre="Tortas")
        self.barato = crear_producto(self.negocio, nombre="Brownie", codigo="B-1", precio="5000")
        self.caro = crear_producto(self.negocio, nombre="Opéra", codigo="O-1", precio="90000")
        self.caro.categoria = self.tortas
        self.caro.save()

    def nombres(self, **params):
        respuesta = self.client.get(reverse("marketplace"), params)
        return [p.nombre for p in respuesta.context["productos"]]

    def test_ordena_por_precio(self):
        self.assertEqual(self.nombres(orden="precio_menor"), ["Brownie", "Opéra"])
        self.assertEqual(self.nombres(orden="precio_mayor"), ["Opéra", "Brownie"])

    def test_filtra_por_categoria(self):
        self.assertEqual(self.nombres(categoria="Tortas"), ["Opéra"])

    def test_valores_desconocidos_se_ignoran(self):
        self.assertEqual(sorted(self.nombres(categoria="<script>", orden="drop table")), ["Brownie", "Opéra"])

    def test_mejor_valorados_primero(self):
        comprador = crear_usuario("c@correo.co")
        Comentario.objects.create(empresa=self.negocio, producto=self.barato, autor=comprador, calificacion=5, texto="Rico")
        self.assertEqual(self.nombres(orden="mejor_valorados")[0], "Brownie")

    def test_destacado_solo_con_opiniones_reales(self):
        self.assertFalse(negocios_con_valoracion()[0].destacado)
        for i in range(3):
            autor = crear_usuario(f"c{i}@correo.co")
            Comentario.objects.create(empresa=self.negocio, producto=self.caro, autor=autor, calificacion=5, texto="Top")
        negocio = negocios_con_valoracion()[0]
        self.assertTrue(negocio.destacado)
        self.assertEqual(negocio.num_opiniones, 3)

    def test_pagina_tiene_interruptor_de_tema_y_filtros(self):
        respuesta = self.client.get(reverse("marketplace"))
        self.assertContains(respuesta, 'role="switch"')
        self.assertContains(respuesta, "data-tema-boton")
        self.assertContains(respuesta, 'name="categoria"')
        self.assertContains(respuesta, "Tiendas destacadas")
        self.assertContains(respuesta, 'name="comprar_ahora"')
