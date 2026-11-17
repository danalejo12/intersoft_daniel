"""Marketplace rediseñado: filtros por categoría, orden, valoraciones y modo día / noche."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .marketplace import DIAS_RANKING_VENTAS, con_valoraciones, negocios_con_valoracion
from .models import Categoria, Comentario, DetallePedido, Pedido, Producto
from .tests_compra import crear_negocio, crear_producto, crear_usuario
from .tests_pedidos import crear_pedido_simple
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

    def vender(self, producto, cantidad, estado=Pedido.Estado.PAGADO, hace_dias=0):
        self.numero_pedido = getattr(self, "numero_pedido", 0) + 1
        pedido = crear_pedido_simple(self.negocio, crear_usuario(f"p{self.numero_pedido}@correo.co"),
                                     numero=self.numero_pedido)
        Pedido.objects.filter(pk=pedido.pk).update(
            estado=estado, creado_en=timezone.now() - timedelta(days=hace_dias))
        DetallePedido.objects.create(empresa=self.negocio, pedido=pedido, producto=producto, cantidad=cantidad,
                                     precio_unitario=producto.precio, iva_porcentaje=producto.iva_porcentaje)

    def test_mas_vendidos_cuenta_solo_pedidos_pagados_recientes(self):
        self.vender(self.caro, 2)
        self.vender(self.barato, 50, estado=Pedido.Estado.CANCELADO)
        self.vender(self.barato, 50, hace_dias=DIAS_RANKING_VENTAS + 1)
        self.assertEqual(self.nombres(orden="mas_vendidos"), ["Opéra", "Brownie"])
        respuesta = self.client.get(reverse("marketplace"), {"orden": "mas_vendidos"})
        self.assertContains(respuesta, "2 vendidos")

    def test_relevancia_combina_ventas_y_opiniones(self):
        self.vender(self.caro, 3)  # 3 puntos por ventas
        for i in range(2):  # 2 opiniones x 2 = 4 puntos
            Comentario.objects.create(empresa=self.negocio, producto=self.barato, autor=crear_usuario(f"o{i}@c.co"),
                                      calificacion=4, texto="Bien")
        self.assertEqual(self.nombres(), ["Brownie", "Opéra"])
        self.vender(self.caro, 2)  # ahora 5 puntos
        self.assertEqual(self.nombres(), ["Opéra", "Brownie"])

    def test_ventas_no_multiplican_el_conteo_de_opiniones(self):
        Comentario.objects.create(empresa=self.negocio, producto=self.caro, autor=crear_usuario("x@c.co"),
                                  calificacion=5, texto="Top")
        self.vender(self.caro, 1)
        self.vender(self.caro, 1)
        producto = con_valoraciones(Producto.objects.filter(pk=self.caro.pk)).get()
        self.assertEqual((producto.num_opiniones, producto.vendidos), (1, 2))

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
