from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Cliente, Comentario, Empresa, Factura, Pago, Pedido, Producto
from .negocios import registrar_negocio
from .services import StockInsuficiente

Usuario = get_user_model()


def crear_usuario(correo="ana@correo.co", nombre="Ana", apellido="Pérez"):
    return Usuario.objects.create_user(
        username=correo, email=correo, password="ClaveSegura#2026", first_name=nombre, last_name=apellido
    )


def crear_negocio(nombre, nit, dueno):
    return registrar_negocio(usuario=dueno, datos={"nombre": nombre, "nit": nit, "email": "", "telefono": "", "direccion": ""})


def crear_producto(empresa, nombre="Pan", codigo="P-1", precio="1999.98", stock=5, publicado=True, iva="19"):
    return Producto.objects.create(
        empresa=empresa, nombre=nombre, codigo=codigo, precio=Decimal(precio),
        iva_porcentaje=Decimal(iva), stock=stock, publicado=publicado,
    )


DATOS_ENVIO = {
    "nombre": "Ana Pérez", "tipo_documento": "CC", "numero_documento": "1.020.304", "email": "ana@correo.co",
    "telefono": "300 123 4567", "departamento": "Antioquia", "ciudad": "Medellín",
    "direccion": "Calle 10 # 20-30", "indicaciones": "Torre 2",
}


def transaccion(pago, status="APPROVED"):
    return {
        "id": "t-1", "reference": pago.referencia, "status": status,
        "amount_in_cents": pago.monto_centavos, "currency": pago.moneda, "payment_method_type": "CARD",
    }


class Base(TestCase):
    def setUp(self):
        # Sin esto, una prueba podría terminar consultando a Wompi de verdad
        parche = mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None)
        self.buscar = parche.start()
        self.addCleanup(parche.stop)
        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "111", self.dueno)
        self.producto = crear_producto(self.negocio)
        self.comprador = crear_usuario()

    def agregar(self, producto=None, cantidad=1, **extra):
        producto = producto or self.producto
        return self.client.post(reverse("carrito_agregar", args=[producto.pk]), {"cantidad": cantidad, **extra})

    def cantidad_en_carrito(self):
        return self.client.session.get("carrito", {})

    def comprar(self, cantidad=2):
        self.client.force_login(self.comprador)
        self.agregar(cantidad=cantidad)
        return self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)


class CarritoTests(Base):
    def test_sin_cuenta_se_puede_agregar(self):
        respuesta = self.agregar(cantidad=2)
        self.assertRedirects(respuesta, reverse("carrito"))
        self.assertEqual(self.cantidad_en_carrito(), {str(self.producto.pk): 2})

    def test_no_supera_lo_disponible(self):
        self.agregar(cantidad=50)
        self.assertEqual(self.cantidad_en_carrito()[str(self.producto.pk)], 5)

    def test_producto_sin_publicar_responde_404(self):
        oculto = crear_producto(self.negocio, codigo="P-2", publicado=False)
        self.assertEqual(self.agregar(oculto).status_code, 404)

    def test_agotado_no_se_agrega(self):
        agotado = crear_producto(self.negocio, codigo="P-3", stock=0)
        self.agregar(agotado)
        self.assertEqual(self.cantidad_en_carrito(), {})

    def test_agregar_con_javascript_devuelve_json(self):
        respuesta = self.client.post(
            reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 3},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
        self.assertEqual(respuesta.json()["cantidad_total"], 3)
        self.assertTrue(respuesta.json()["ok"])

    def test_cantidad_invalida_no_rompe(self):
        self.assertEqual(self.agregar(cantidad="abc").status_code, 302)
        self.assertEqual(self.cantidad_en_carrito()[str(self.producto.pk)], 1)

    def test_actualizar_y_quitar(self):
        self.agregar()
        self.client.post(reverse("carrito_actualizar", args=[self.producto.pk]), {"cantidad": 4})
        self.assertEqual(self.cantidad_en_carrito()[str(self.producto.pk)], 4)
        self.client.post(reverse("carrito_actualizar", args=[self.producto.pk]), {"cantidad": 0})
        self.assertEqual(self.cantidad_en_carrito(), {})

    def test_el_carrito_quita_lo_que_dejo_de_publicarse(self):
        self.agregar()
        Producto.objects.filter(pk=self.producto.pk).update(publicado=False)
        respuesta = self.client.get(reverse("carrito"))
        self.assertContains(respuesta, "Tu carrito está vacío")
        self.assertEqual(self.cantidad_en_carrito(), {})

    def test_el_carrito_no_revela_el_stock_exacto(self):
        Producto.objects.filter(pk=self.producto.pk).update(stock=7391)
        self.agregar()
        self.assertNotContains(self.client.get(reverse("carrito")), "7391")

    def test_agrupa_por_negocio(self):
        otro = crear_negocio("Ferretería", "222", crear_usuario("o@correo.co"))
        martillo = crear_producto(otro, "Martillo")
        self.agregar()
        self.agregar(martillo)
        respuesta = self.client.get(reverse("carrito"))
        self.assertEqual(len(respuesta.context["grupos"]), 2)
        self.assertContains(respuesta, reverse("checkout", args=[otro.slug]))

    def test_comprar_ahora_va_a_los_datos_de_envio(self):
        self.client.force_login(self.comprador)
        respuesta = self.agregar(comprar_ahora="1")
        self.assertRedirects(respuesta, reverse("checkout", args=[self.negocio.slug]))


class CheckoutTests(Base):
    def test_sin_cuenta_pide_registro_y_conserva_el_carrito(self):
        self.agregar()
        url = reverse("checkout", args=[self.negocio.slug])
        self.assertRedirects(self.client.get(url), f"{reverse('registro')}?next={url}")
        self.client.post(reverse("registro") + f"?next={url}", {
            "first_name": "Nueva", "last_name": "Persona", "email": "n@correo.co",
            "password1": "ClaveSegura#2026", "password2": "ClaveSegura#2026",
        })
        self.assertEqual(self.cantidad_en_carrito(), {str(self.producto.pk): 1})

    def test_compra_crea_pedido_factura_cliente_y_reserva_stock(self):
        respuesta = self.comprar(cantidad=2)
        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse("pedido_detalle", args=[pedido.pk]))
        self.assertEqual(pedido.comprador, self.comprador)
        self.assertEqual(pedido.empresa, self.negocio)
        self.assertEqual(pedido.factura.cliente.numero_documento, "1020304")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)
        self.assertEqual(self.cantidad_en_carrito(), {})

    def test_el_total_mostrado_es_el_que_se_cobra(self):
        self.client.force_login(self.comprador)
        self.agregar(cantidad=3)
        url = reverse("checkout", args=[self.negocio.slug])
        mostrado = self.client.get(url).context["grupo"]["total"]
        self.client.post(url, DATOS_ENVIO)
        self.assertEqual(mostrado, Pedido.objects.get().factura.total)

    def test_solo_compra_el_negocio_elegido(self):
        otro = crear_negocio("Ferretería", "222", crear_usuario("o@correo.co"))
        martillo = crear_producto(otro, "Martillo")
        self.client.force_login(self.comprador)
        self.agregar()
        self.agregar(martillo)
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        self.assertEqual(self.cantidad_en_carrito(), {str(martillo.pk): 1})

    def test_datos_incompletos_no_crean_nada(self):
        self.client.force_login(self.comprador)
        self.agregar()
        respuesta = self.client.post(reverse("checkout", args=[self.negocio.slug]), {**DATOS_ENVIO, "direccion": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(Factura.objects.exists())

    def test_cliente_existente_se_reutiliza_sin_cambiarlo(self):
        Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="1020304", nombre="Nombre del negocio")
        self.comprar()
        cliente = Cliente.objects.get(empresa=self.negocio)
        self.assertEqual(cliente.nombre, "Nombre del negocio")

    def test_si_alguien_se_lleva_el_stock_no_revela_cantidades(self):
        self.client.force_login(self.comprador)
        self.agregar(cantidad=2)
        with mock.patch("core.compras.crear_factura", side_effect=StockInsuficiente("hay 1, se piden 2")):
            respuesta = self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO, follow=True)
        self.assertNotContains(respuesta, "hay 1")
        self.assertContains(respuesta, "Otra persona")
        self.assertFalse(Pedido.objects.exists())

    def test_si_cambia_el_stock_al_confirmar_vuelve_al_carrito(self):
        self.client.force_login(self.comprador)
        self.agregar(cantidad=4)
        Producto.objects.filter(pk=self.producto.pk).update(stock=2)
        respuesta = self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        self.assertRedirects(respuesta, reverse("carrito"))
        self.assertFalse(Pedido.objects.exists())

    def test_la_segunda_compra_recuerda_los_datos(self):
        self.comprar(cantidad=1)
        self.agregar()
        formulario = self.client.get(reverse("checkout", args=[self.negocio.slug])).context["form"]
        self.assertEqual(formulario.initial["direccion"], "Calle 10 # 20-30")
        self.assertEqual(formulario.initial["numero_documento"], "1020304")


@override_settings(PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_test_x",
                   WOMPI_INTEGRITY_SECRET="test_integrity_x", WOMPI_PRIVATE_KEY="prv_test_x")
class PagoPedidoTests(Base):
    def setUp(self):
        super().setUp()
        self.comprar(cantidad=2)
        self.pedido = Pedido.objects.get()
        self.detalle = reverse("pedido_detalle", args=[self.pedido.pk])

    def pagar(self):
        return self.client.post(reverse("pedido_pagar", args=[self.pedido.pk]))

    def test_pagar_va_a_wompi_sin_exponer_el_secreto(self):
        respuesta = self.pagar()
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.url.startswith("https://checkout.wompi.co/p/"))
        self.assertNotIn("test_integrity_x", respuesta.url)
        self.assertIn(Pago.objects.get().referencia, respuesta.url)

    def test_el_monto_sale_de_la_factura(self):
        self.pagar()
        self.assertEqual(Pago.objects.get().monto_centavos, int(self.pedido.factura.total * 100))

    def test_aprobado_agradece_y_queda_pagado(self):
        self.pagar()
        self.buscar.return_value = transaccion(Pago.objects.get())
        respuesta = self.client.get(self.detalle)
        self.assertContains(respuesta, "Gracias por tu compra, Ana!")
        self.assertTrue(Factura.objects.get().esta_pagada)
        self.assertNotContains(respuesta, "Pagar con Wompi")

    def test_rechazado_permite_reintentar_y_conserva_la_reserva(self):
        self.pagar()
        self.buscar.return_value = transaccion(Pago.objects.get(), status="DECLINED")
        respuesta = self.client.get(self.detalle)
        self.assertContains(respuesta, "Tu pago no se aprobó")
        self.assertContains(respuesta, "Intentar de nuevo")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

    def test_el_estado_lo_decide_wompi_no_la_url(self):
        self.pagar()
        self.client.get(self.detalle + "?status=APPROVED&estado=pagado")
        self.assertEqual(Pago.objects.get().estado, Pago.Estado.PENDIENTE)

    def test_estado_json_para_la_pestana_que_espera(self):
        url = reverse("pedido_estado", args=[self.pedido.pk])
        self.assertEqual(self.client.get(url).json()["estado"], "por_pagar")
        self.pagar()
        self.assertEqual(self.client.get(url).json()["estado"], "procesando")
        self.buscar.return_value = transaccion(Pago.objects.get())
        self.assertEqual(self.client.get(url).json()["estado"], "pagado")

    def test_no_cobra_dos_veces_si_wompi_ya_aprobo(self):
        self.pagar()
        self.buscar.return_value = transaccion(Pago.objects.get())
        self.pagar()
        self.assertEqual(Pago.objects.count(), 1)

    def test_otra_persona_no_ve_ni_paga_el_pedido(self):
        self.client.force_login(crear_usuario("otra@correo.co"))
        self.assertEqual(self.client.get(self.detalle).status_code, 404)
        self.assertEqual(self.pagar().status_code, 404)
        self.assertEqual(self.client.get(reverse("pedido_estado", args=[self.pedido.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("pedido_cancelar", args=[self.pedido.pk])).status_code, 404)

    def test_cancelar_devuelve_el_stock(self):
        respuesta = self.client.post(reverse("pedido_cancelar", args=[self.pedido.pk]), follow=True)
        self.assertContains(respuesta, "Este pedido fue cancelado")
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)

    def test_no_cancela_si_wompi_ya_aprobo(self):
        self.pagar()
        self.buscar.return_value = transaccion(Pago.objects.get())
        self.client.post(reverse("pedido_cancelar", args=[self.pedido.pk]))
        self.pedido.factura.refresh_from_db()
        self.assertEqual(self.pedido.factura.estado, Factura.Estado.EMITIDA)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

    def test_mis_pedidos_solo_muestra_los_propios(self):
        self.assertContains(self.client.get(reverse("mis_pedidos")), "Panadería")
        self.client.force_login(crear_usuario("otra@correo.co"))
        self.assertNotContains(self.client.get(reverse("mis_pedidos")), "Panadería")

    def test_el_negocio_ve_los_datos_de_envio_en_su_panel(self):
        self.client.force_login(self.dueno)
        respuesta = self.client.get(reverse("facturas_detalle", args=[self.pedido.factura_id]))
        self.assertContains(respuesta, "Datos de envío")
        self.assertContains(respuesta, "Calle 10 # 20-30")


class ComentariosTests(Base):
    def setUp(self):
        super().setUp()
        self.url = reverse("comentar", args=[self.producto.pk])
        self.pagina = reverse("tienda_producto", args=[self.producto.pk])

    def test_sin_sesion_pide_ingresar_y_no_guarda(self):
        respuesta = self.client.post(self.url, {"calificacion": 5, "texto": "Rico"})
        self.assertRedirects(respuesta, f"{reverse('login')}?next={self.pagina}")
        self.assertFalse(Comentario.objects.exists())

    def test_publica_y_muestra_sin_revelar_el_correo(self):
        self.client.force_login(self.comprador)
        respuesta = self.client.post(self.url, {"calificacion": 4, "texto": "Muy rico"}, follow=True)
        self.assertContains(respuesta, "Muy rico")
        self.assertContains(respuesta, "Ana P.")
        self.client.logout()
        self.assertNotContains(self.client.get(self.pagina), "ana@correo.co")

    def test_una_opinion_por_persona(self):
        self.client.force_login(self.comprador)
        self.client.post(self.url, {"calificacion": 2, "texto": "Primera"})
        self.client.post(self.url, {"calificacion": 5, "texto": "Cambié de idea"})
        comentario = Comentario.objects.get()
        self.assertEqual(comentario.calificacion, 5)
        self.assertEqual(comentario.texto, "Cambié de idea")

    def test_calificacion_fuera_de_rango_se_rechaza(self):
        self.client.force_login(self.comprador)
        for valor in (0, 6, "x"):
            with self.subTest(valor=valor):
                self.client.post(self.url, {"calificacion": valor, "texto": "Hola"})
                self.assertFalse(Comentario.objects.exists())

    def test_el_html_se_escapa(self):
        self.client.force_login(self.comprador)
        respuesta = self.client.post(self.url, {"calificacion": 3, "texto": "<script>alert(1)</script>"}, follow=True)
        self.assertNotContains(respuesta, "<script>alert(1)</script>")
        self.assertContains(respuesta, "&lt;script&gt;")

    def test_compra_verificada_solo_con_pago_aprobado(self):
        self.client.force_login(self.comprador)
        self.client.post(self.url, {"calificacion": 5, "texto": "Sin comprar"})
        self.assertFalse(Comentario.objects.get().compra_verificada)

        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)  # carrito vacío: no compra
        self.agregar()
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get()
        Pago.objects.create(empresa=self.negocio, factura=pedido.factura, referencia="R-1", monto_centavos=100, estado="aprobado")
        self.client.post(self.url, {"calificacion": 5, "texto": "Ya compré", "compra_verificada": "on"})
        self.assertTrue(Comentario.objects.get().compra_verificada)

    def test_el_navegador_no_puede_marcar_compra_verificada(self):
        self.client.force_login(self.comprador)
        self.client.post(self.url, {"calificacion": 5, "texto": "Hola", "compra_verificada": "on"})
        self.assertFalse(Comentario.objects.get().compra_verificada)

    def test_solo_el_autor_elimina(self):
        self.client.force_login(self.comprador)
        self.client.post(self.url, {"calificacion": 5, "texto": "Mía"})
        comentario = Comentario.objects.get()
        self.client.force_login(crear_usuario("otra@correo.co"))
        self.assertEqual(self.client.post(reverse("comentario_eliminar", args=[comentario.pk])).status_code, 404)
        self.client.force_login(self.comprador)
        self.client.post(reverse("comentario_eliminar", args=[comentario.pk]))
        self.assertFalse(Comentario.objects.exists())

    def test_promedio_en_la_pagina(self):
        for correo, nota in (("a@c.co", 5), ("b@c.co", 4)):
            self.client.force_login(crear_usuario(correo))
            self.client.post(self.url, {"calificacion": nota, "texto": "Bien"})
        respuesta = self.client.get(self.pagina)
        self.assertEqual(respuesta.context["opiniones"]["total"], 2)
        self.assertContains(respuesta, "2 opiniones")


class EmpresaIntactaTests(TestCase):
    def test_login_usa_el_estilo_de_la_tienda_y_conserva_el_registro(self):
        respuesta = self.client.get(reverse("login"))
        self.assertTemplateUsed(respuesta, "core/tienda/base.html")
        self.assertContains(respuesta, "Créala aquí")
        self.assertFalse(Empresa.objects.exists())
