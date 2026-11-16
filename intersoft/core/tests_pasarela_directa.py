"""Regresiones del cobro directo: nunca usar la cuenta de la plataforma."""
import io
import json
from dataclasses import replace
from decimal import Decimal
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from . import compras
from .models import ConfiguracionPagos, Pago, Pedido
from .pagos import (
    PagoNoPermitido,
    crear_evento_simulado,
    crear_pago_pedido,
    sincronizar_pago,
    url_checkout,
)
from .pasarelas import credenciales_pago
from .tests_compra import (
    DATOS_ENVIO,
    Base,
    crear_negocio,
    crear_producto,
    crear_usuario,
)


def conectar(empresa, sufijo="12345678", **extra):
    config = ConfiguracionPagos(empresa=empresa, modo="pruebas", activa=True,
                               verificada_en=timezone.now(), llave_publica=f"pub_test_{sufijo}", **extra)
    for campo, valor in {
        "llave_privada": f"prv_test_{sufijo}",
        "secreto_integridad": f"test_integrity_{sufijo}",
        "secreto_eventos": f"test_events_{sufijo}",
    }.items():
        config.poner_secreto(campo, valor)
    config.save()
    return config


@override_settings(PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_prod_PLATAFORMA",
                   WOMPI_INTEGRITY_SECRET="PLATAFORMA", WOMPI_EVENTS_SECRET="PLATAFORMA")
class PasarelaDirectaTests(Base):
    conectar_pasarela = False
    def pedido(self):
        return compras.crear_pedido(usuario=self.comprador, negocio=self.negocio,
                                    lineas=[{"producto": self.producto, "cantidad": 1}], datos=DATOS_ENVIO)

    def test_sin_configuracion_no_reserva_ni_cobra_con_env(self):
        with self.assertRaises(PagoNoPermitido):
            self.pedido()
        self.assertFalse(Pedido.objects.filter(empresa=self.negocio).exists())
        self.assertContains(self.client.get(reverse("tienda_producto", args=[self.producto.pk])),
                            "Compra en línea no disponible")

    def test_checkout_y_tarifas_son_del_negocio(self):
        config = conectar(self.negocio, cobrar_tarifa_al_comprador=False)
        pedido = self.pedido()
        self.assertEqual(pedido.cargo_pasarela, Decimal("0"))
        self.assertEqual(pedido.comision_valor, Decimal("0"))
        pago = crear_pago_pedido(pedido=pedido)
        parametros = parse_qs(urlsplit(url_checkout(pago=pago, redirect_url="https://tienda.co/")).query)
        self.assertEqual(parametros["public-key"], [config.llave_publica])
        self.assertNotIn("PLATAFORMA", str(parametros))

    def enviar(self, empresa, evento):
        real = evento.get("data", {}).get("transaction") if isinstance(evento, dict) else None
        with mock.patch("core.pagos.consultar_transaccion", return_value=real):
            return self.client.post(reverse("wompi_webhook_negocio", args=[empresa.pk]),
                                    json.dumps(evento), content_type="application/json")

    def test_webhook_aislado_y_repetible(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        otro = crear_negocio("Otro", "902", crear_usuario("otro@c.co"))
        conectar(otro, "99999999")
        self.assertEqual(self.enviar(otro, evento).status_code, 400)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)
        self.assertEqual(self.enviar(self.negocio, evento).status_code, 200)
        self.assertEqual(self.enviar(self.negocio, evento).status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)

    def test_cambio_o_borrado_de_configuracion_conserva_intentos_anteriores(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        config.delete()
        self.assertEqual(self.enviar(self.negocio, evento).status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)

    def test_webhook_global_no_puede_aprobar_ventas(self):
        conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto="PLATAFORMA")
        self.client.post(reverse("wompi_webhook"), json.dumps(evento), content_type="application/json")
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_eventos_malformados_no_provocan_error_500(self):
        conectar(self.negocio)
        for evento in ([], {}, {"signature": {"properties": [0]}},
                       {"signature": {"properties": []}, "timestamp": 1, "data": {}}):
            self.assertEqual(self.enviar(self.negocio, evento).status_code, 400)

    def test_pausada_no_admite_nuevos_intentos(self):
        config = conectar(self.negocio)
        pedido = self.pedido()
        config.activa = False
        config.save()
        with self.assertRaises(PagoNoPermitido):
            crear_pago_pedido(pedido=pedido)

    def test_no_acepta_referencia_alterada_en_evento_firmado(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        otro = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        real = dict(evento["data"]["transaction"])
        evento["data"]["transaction"]["reference"] = otro.referencia
        with mock.patch("core.pagos.consultar_transaccion", return_value=real):
            respuesta = self.client.post(reverse("wompi_webhook_negocio", args=[self.negocio.pk]),
                                        json.dumps(evento), content_type="application/json")
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(Pago.objects.filter(estado=Pago.Estado.APROBADO).exists())

    def test_wompi_sin_respuesta_solicita_reintento(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        with mock.patch("core.pagos.consultar_transaccion", return_value=None):
            respuesta = self.client.post(reverse("wompi_webhook_negocio", args=[self.negocio.pk]),
                                        json.dumps(evento), content_type="application/json")
        self.assertEqual(respuesta.status_code, 503)

    def test_rotacion_incluye_las_instantaneas_de_pagos(self):
        vieja, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(PAGOS_CLAVES_CIFRADO=vieja):
            config = conectar(self.negocio)
            pago = crear_pago_pedido(pedido=self.pedido())
            original = credenciales_pago(pago)
        with override_settings(PAGOS_CLAVES_CIFRADO=f"{nueva},{vieja}"):
            call_command("rotar_secretos_pago", stdout=io.StringIO())
        with override_settings(PAGOS_CLAVES_CIFRADO=nueva):
            pago.refresh_from_db()
            self.assertEqual(credenciales_pago(pago), original)

    def test_primeros_pasos_depende_solo_del_negocio(self):
        from .primeros_pasos import pasos_del_negocio
        self.assertFalse(pasos_del_negocio(self.negocio, self.dueno)[3].hecho)
        conectar(self.negocio)
        self.negocio.refresh_from_db()
        self.assertTrue(pasos_del_negocio(self.negocio, self.dueno)[3].hecho)

    def test_orden_de_precios_incluye_tarifas_de_cada_negocio(self):
        from .marketplace import ordenar, productos_publicos
        conectar(self.negocio, tarifa_fija=Decimal("5000"))
        otro = crear_negocio("Otro", "902", crear_usuario("otro@c.co"))
        conectar(otro, "99999999", cobrar_tarifa_al_comprador=False)
        barato = crear_producto(otro, precio="2500")
        self.assertLess(barato.precio_marketplace, self.producto.precio_marketplace)
        self.assertEqual(list(ordenar(productos_publicos(), "precio_menor").values_list("pk", flat=True)),
                         [barato.pk, self.producto.pk])

    def test_pedido_directo_no_admite_dispersion(self):
        from .reservas import registrar_dispersion_pedido
        conectar(self.negocio)
        with self.assertRaisesMessage(ValueError, "no requieren dispersión"):
            registrar_dispersion_pedido(pedido=self.pedido(), referencia="DISP-1")

    def test_url_antigua_solo_concilia_intentos_historicos(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        Pago.objects.filter(pk=pago.pk).update(pasarela_propia=False)
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        with mock.patch("core.pagos.consultar_transaccion", return_value=evento["data"]["transaction"]):
            respuesta = self.client.post(reverse("wompi_webhook"), json.dumps(evento),
                                        content_type="application/json")
        self.assertEqual(respuesta.status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)

    def test_retorno_publico_no_prueba_que_el_negocio_recibio_el_pago(self):
        conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        pago.credenciales_cifradas = replace(credenciales_pago(pago), privada="").cifradas()
        pago.save()
        with mock.patch("core.pagos.consultar_transaccion") as publico:
            sincronizar_pago(pago=pago, transaccion_id="COBRO-OTRO-COMERCIO", forzar=True)
        publico.assert_not_called()
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_unicode_invalido_en_firma_se_rechaza(self):
        config = conectar(self.negocio)
        pago = crear_pago_pedido(pedido=self.pedido())
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto=config.secreto_eventos)
        evento["data"]["transaction"]["id"] = "\ud800"
        self.assertEqual(self.enviar(self.negocio, evento).status_code, 400)

    def test_no_renueva_pedidos_historicos(self):
        conectar(self.negocio)
        pedido = self.pedido()
        pedido.pago_directo = False
        pedido.save()
        self.assertFalse(pedido.puede_renovar)
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.renovar_reserva(pedido)

    def test_producto_gratis_se_ordena_sin_cargo_fijo(self):
        from .marketplace import ordenar, productos_publicos
        conectar(self.negocio, tarifa_fija=Decimal("5000"))
        self.producto.precio = Decimal("0")
        self.producto.save()
        self.assertEqual(ordenar(productos_publicos(), "precio_menor").get()._p,
                         self.producto.precio_marketplace)
