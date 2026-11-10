"""Pruebas del Sprint 1 "Cimientos": registros, datos del vendedor, IVA, Wompi, Inicio y límite de intentos."""
import logging
from logging.handlers import RotatingFileHandler
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.log import AdminEmailHandler

from . import reservas
from .models import Empresa, Pedido
from .tests_pedidos import PedidoBase


class RegistrosTests(TestCase):
    def test_pagos_y_reservas_escriben_en_archivo_y_avisan_a_admins(self):
        for nombre in ("core.pagos", "core.reservas"):
            with self.subTest(logger=nombre):
                tipos = {type(h) for h in logging.getLogger(nombre).handlers}
                self.assertIn(RotatingFileHandler, tipos)
                self.assertIn(AdminEmailHandler, tipos)

    @override_settings(ADMINS=["finanzas@intersoft.example"])
    def test_critical_queda_en_el_archivo(self):
        logger = logging.getLogger("core.reservas")
        logger.critical("Prueba de registro: aviso crítico de reembolso")
        archivo = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
        archivo.flush()
        with open(archivo.baseFilename, encoding="utf-8") as registro:
            self.assertIn("Prueba de registro: aviso crítico de reembolso", registro.read())

    def test_sin_admins_no_se_envia_correo(self):
        with override_settings(ADMINS=[]):
            logging.getLogger("core.pagos").critical("Sin destinatarios")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(ADMINS=["finanzas@intersoft.example"])
class AvisoDeReembolsoTests(PedidoBase):
    def test_un_reembolso_real_avisa_por_correo(self):
        reservas.registrar_monto_invalido(self.pedido)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("requiere reembolso", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["finanzas@intersoft.example"])


class DatosVendedorTests(TestCase):
    """Ley 1480, art. 53: el comprador debe poder identificar y contactar al vendedor."""

    def setUp(self):
        from .tests_compra import crear_negocio, crear_producto, crear_usuario

        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "900123", self.dueno)
        self.producto = crear_producto(self.negocio)

    def quitar_datos(self):
        Empresa.objects.filter(pk=self.negocio.pk).update(direccion="", telefono="")

    def test_registro_exige_direccion_y_telefono(self):
        from .tests_compra import crear_usuario

        self.client.force_login(crear_usuario("nuevo@correo.co"))
        respuesta = self.client.post(reverse("negocio_registrar"), {"nombre": "Nuevo", "nit": "77", "email": "", "telefono": "", "direccion": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("direccion", respuesta.context["form"].errors)
        self.assertIn("telefono", respuesta.context["form"].errors)
        self.assertFalse(Empresa.objects.filter(nit="77").exists())

    def test_registro_rechaza_telefono_invalido(self):
        from .tests_compra import crear_usuario

        self.client.force_login(crear_usuario("nuevo@correo.co"))
        respuesta = self.client.post(reverse("negocio_registrar"), {"nombre": "Nuevo", "nit": "77", "email": "", "telefono": "abc", "direccion": "Calle 2"})
        self.assertIn("telefono", respuesta.context["form"].errors)

    def test_sin_datos_sus_productos_no_se_publican(self):
        self.quitar_datos()
        self.assertNotContains(self.client.get(reverse("marketplace")), "Pan")
        self.assertEqual(self.client.get(reverse("tienda_producto", args=[self.producto.pk])).status_code, 404)

    def test_el_panel_avisa_y_al_completar_vuelven_a_publicarse(self):
        self.quitar_datos()
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse("dashboard")), "Completar ahora")
        respuesta = self.client.post(reverse("negocio_datos"), {"direccion": "Carrera 7 # 8-9", "telefono": "601 555 1234", "email": "ventas@pan.co"})
        self.assertRedirects(respuesta, reverse("dashboard"))
        self.negocio.refresh_from_db()
        self.assertTrue(self.negocio.datos_completos)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Completar ahora")
        self.assertEqual(self.client.get(reverse("tienda_producto", args=[self.producto.pk])).status_code, 200)

    def test_completar_datos_exige_los_dos(self):
        self.quitar_datos()
        self.client.force_login(self.dueno)
        respuesta = self.client.post(reverse("negocio_datos"), {"direccion": "", "telefono": "", "email": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.negocio.refresh_from_db()
        self.assertFalse(self.negocio.datos_completos)

    def test_no_se_pueden_cambiar_nombre_ni_nit_desde_el_panel(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse("negocio_datos"), {"direccion": "Calle 9", "telefono": "6015551234", "nombre": "Otro", "nit": "1"})
        self.negocio.refresh_from_db()
        self.assertEqual((self.negocio.nombre, self.negocio.nit), ("Panadería", "900123"))

    def test_rol_sin_permiso_no_edita_los_datos(self):
        from .models import Membresia, Rol
        from .tests_compra import crear_usuario

        empleado = crear_usuario("empleado@correo.co")
        rol = Rol.objects.create(empresa=self.negocio, nombre="Vendedor", es_admin=False)
        Membresia.objects.create(usuario=empleado, empresa=self.negocio, rol=rol)
        self.client.force_login(empleado)
        self.assertEqual(self.client.get(reverse("negocio_datos")).status_code, 403)

    def test_el_comprador_ve_los_datos_del_vendedor_en_su_pedido(self):
        from .tests_compra import DATOS_ENVIO, crear_usuario

        Empresa.objects.filter(pk=self.negocio.pk).update(email="ventas@pan.co")
        self.client.force_login(crear_usuario("compra@correo.co"))
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get()
        with mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None):
            respuesta = self.client.get(reverse("pedido_detalle", args=[pedido.pk]))
        for dato in ("Datos del vendedor", "Panadería", "NIT 900123", "Calle 1 # 2-3", "6011234567", "ventas@pan.co"):
            with self.subTest(dato=dato):
                self.assertContains(respuesta, dato)


class RedondeoIvaTests(TestCase):
    """Un caso de empate: 0,50 con IVA del 1 % da 0,005, que debe quedar en 0,01 en todas partes."""

    def setUp(self):
        from .tests_compra import crear_negocio, crear_producto, crear_usuario

        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "900123", self.dueno)
        self.producto = crear_producto(self.negocio, nombre="Galleta", precio="0.50", iva="1")

    def test_la_funcion_redondea_la_mitad_hacia_arriba(self):
        from decimal import Decimal

        from .impuestos import calcular_iva

        self.assertEqual(calcular_iva(Decimal("0.50"), Decimal("1")), Decimal("0.01"))
        self.assertEqual(calcular_iva(Decimal("1.50"), Decimal("1")), Decimal("0.02"))  # 0,015: también hacia arriba

    def test_catalogo_carrito_pedido_y_factura_dan_lo_mismo(self):
        from decimal import Decimal

        from .carrito import _linea
        from .models import Cliente
        from .reservas import marcar_pagado
        from .services import crear_factura
        from .tests_compra import DATOS_ENVIO, crear_usuario

        esperado = Decimal("0.51")
        self.assertEqual(self.producto.precio_con_iva, esperado)
        self.assertEqual(_linea(self.producto, 1)["total"], esperado)

        self.client.force_login(crear_usuario("compra@correo.co"))
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.total, esperado)
        marcar_pagado(pedido)
        self.assertEqual(pedido.factura.total, esperado)
        self.assertEqual(pedido.factura.detalles.get().valor_iva, Decimal("0.01"))

        cliente = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="5", nombre="C")
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente, items=[{"producto": self.producto, "cantidad": 1}])
        self.assertEqual(factura.total, esperado)
