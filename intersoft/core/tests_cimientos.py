"""Pruebas del Sprint 1 "Cimientos": registros, datos del vendedor, IVA, Wompi, Inicio y límite de intentos."""
import logging
from logging.handlers import RotatingFileHandler

from django.core import mail
from django.test import TestCase, override_settings
from django.utils.log import AdminEmailHandler

from . import reservas
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
