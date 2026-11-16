"""Fase 1 de la pasarela por negocio: llaves cifradas, verificación con Wompi y permisos."""
import io
import json
import sys
import uuid
from unittest import mock
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.views.debug import ExceptionReporter

from .cifrado import SecretoIlegible, cifrar, descifrar
from .models import AuditoriaPagos, ConfiguracionPagos, Membresia, Rol
from .negocios import registrar_negocio
from .tests_compra import crear_usuario
from .tests_marketplace import datos_negocio

CLAVE = Fernet.generate_key().decode()
PUBLICA = "pub_test_AbCdEf123456"
PRIVADA = "prv_test_PrIvAdA987654"
INTEGRIDAD = "test_integrity_InTeGr1234"
EVENTOS = "test_events_EvEnTo5678"


def respuesta_json(datos):
    respuesta = mock.MagicMock()
    respuesta.__enter__.return_value = io.BytesIO(json.dumps(datos).encode())
    return respuesta


def error_http(codigo):
    return HTTPError("https://sandbox.wompi.co/v1", codigo, "error", {}, None)


@override_settings(PAGOS_CLAVES_CIFRADO=CLAVE)
class CifradoTests(TestCase):
    def test_reporte_de_errores_oculta_la_clave_maestra(self):
        from .cifrado import FiltroSecretosPago
        self.assertNotEqual(FiltroSecretosPago().cleanse_setting("PAGOS_CLAVES_CIFRADO", CLAVE), CLAVE)

    @override_settings(DEBUG=False, PAGOS_CLAVES_CIFRADO="clave-invalida")
    def test_error_de_cifrado_no_expone_el_secreto_en_el_reporte(self):
        self.secreto_sintetico = uuid.uuid4().hex
        try:
            cifrar(self.secreto_sintetico)
        except Exception:
            reporte = ExceptionReporter(RequestFactory().get("/"), *sys.exc_info()).get_traceback_text()
        self.assertNotIn(self.secreto_sintetico, reporte)

    def test_ida_y_vuelta_sin_texto_plano(self):
        token = cifrar(INTEGRIDAD)
        self.assertNotIn(INTEGRIDAD, token)
        self.assertEqual(descifrar(token), INTEGRIDAD)

    def test_vacio_se_queda_vacio(self):
        self.assertEqual(cifrar(""), "")
        self.assertEqual(descifrar(""), "")

    def test_otra_clave_no_puede_leerlo(self):
        token = cifrar(INTEGRIDAD)
        with override_settings(PAGOS_CLAVES_CIFRADO=Fernet.generate_key().decode()):
            with self.assertRaises(SecretoIlegible):
                descifrar(token)

    def test_rotacion_conserva_la_clave_anterior_para_leer(self):
        token = cifrar(INTEGRIDAD)
        nueva = Fernet.generate_key().decode()
        with override_settings(PAGOS_CLAVES_CIFRADO=f"{nueva},{CLAVE}"):
            self.assertEqual(descifrar(token), INTEGRIDAD)


@override_settings(PAGOS_CLAVES_CIFRADO=CLAVE)
class PagosNegocioBase(TestCase):
    def setUp(self):
        self.dueno = crear_usuario("dueno@correo.co")
        self.empresa = registrar_negocio(usuario=self.dueno, datos=datos_negocio("Dulce", "901"))
        self.client.force_login(self.dueno)

    def datos(self, **extra):
        return {
            "llave_publica": PUBLICA, "llave_privada": PRIVADA, "secreto_integridad": INTEGRIDAD,
            "secreto_eventos": EVENTOS, "cobrar_tarifa_al_comprador": "on",
            "tarifa_porcentaje": "2.65", "tarifa_fija": "700", **extra,
        }

    def guardar(self, **extra):
        return self.client.post(reverse("negocio_pagos"), self.datos(**extra))

    def config(self):
        return ConfiguracionPagos.objects.get(empresa=self.empresa)


class GuardarLlavesTests(PagosNegocioBase):
    def test_auditoria_sin_secretos(self):
        self.guardar()
        evento = AuditoriaPagos.objects.get()
        self.assertEqual(evento.empresa, self.empresa)
        self.assertEqual(evento.usuario, self.dueno)
        self.assertEqual(evento.accion, "guardar")
        for secreto in (INTEGRIDAD, EVENTOS, PRIVADA):
            self.assertNotIn(secreto, str(evento.campos))

    def test_guarda_cifrado_y_nunca_lo_vuelve_a_mostrar(self):
        self.assertRedirects(self.guardar(), reverse("negocio_pagos"))
        config = self.config()
        self.assertEqual(config.modo, ConfiguracionPagos.Modo.PRUEBAS)
        self.assertEqual(config.secreto_integridad, INTEGRIDAD)
        self.assertEqual(config.secreto_integridad_final, "1234")
        with connection.cursor() as cursor:
            cursor.execute("SELECT secreto_integridad_cifrado, secreto_eventos_cifrado, llave_privada_cifrada "
                           "FROM core_configuracionpagos")
            fila = " ".join(cursor.fetchone())
        for secreto in (INTEGRIDAD, EVENTOS, PRIVADA):
            self.assertNotIn(secreto, fila)
        pagina = self.client.get(reverse("negocio_pagos")).content.decode()
        for secreto in (INTEGRIDAD, EVENTOS, PRIVADA):
            self.assertNotIn(secreto, pagina)
        self.assertIn("····1234", pagina)

    def test_secretos_vacios_al_editar_conservan_los_guardados(self):
        self.guardar()
        self.guardar(llave_privada="", secreto_integridad="", secreto_eventos="", tarifa_fija="500")
        config = self.config()
        self.assertEqual(config.secreto_eventos, EVENTOS)
        self.assertEqual(config.llave_privada, PRIVADA)
        self.assertEqual(str(config.tarifa_fija), "500.00")

    def test_secretos_obligatorios_la_primera_vez(self):
        respuesta = self.guardar(secreto_integridad="", secreto_eventos="")
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(ConfiguracionPagos.objects.exists())

    def test_formato_invalido(self):
        respuesta = self.guardar(llave_publica="sk_live_123456789")
        self.assertContains(respuesta, "No parece una llave pública de Wompi", status_code=400)

    def test_no_mezcla_pruebas_y_produccion(self):
        respuesta = self.guardar(secreto_eventos="prod_events_EvEnTo5678")
        self.assertContains(respuesta, "no mezcles llaves", status_code=400)
        self.assertFalse(ConfiguracionPagos.objects.exists())

    def test_cambiar_de_modo_exige_todos_los_secretos(self):
        self.guardar()
        respuesta = self.guardar(llave_publica="pub_prod_AbCdEf123456", llave_privada="",
                                 secreto_integridad="", secreto_eventos="")
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(self.config().modo, ConfiguracionPagos.Modo.PRUEBAS)

    def test_cambiar_llaves_obliga_a_verificar_otra_vez(self):
        self.guardar()
        ConfiguracionPagos.objects.update(verificada_en="2026-01-01T00:00Z", activa=True)
        self.guardar(llave_privada="", secreto_integridad="test_integrity_Otro99999", secreto_eventos="")
        config = self.config()
        self.assertIsNone(config.verificada_en)
        self.assertFalse(config.activa)

    def test_cambiar_solo_tarifas_no_pierde_la_verificacion(self):
        self.guardar()
        ConfiguracionPagos.objects.update(verificada_en="2026-01-01T00:00Z", activa=True)
        self.guardar(llave_privada="", secreto_integridad="", secreto_eventos="", tarifa_porcentaje="2.10")
        self.assertTrue(self.config().lista_para_cobrar)

    def test_repr_no_expone_secretos(self):
        self.guardar()
        self.assertNotIn("integrity", repr(self.config()))


class VerificarTests(PagosNegocioBase):
    def setUp(self):
        super().setUp()
        self.guardar()

    def verificar(self):
        return self.client.post(reverse("negocio_pagos_verificar"), follow=True)

    def test_llaves_correctas(self):
        respuestas = [respuesta_json({"data": {"legal_name": "Dulce SAS"}}), respuesta_json({"data": []})]
        with mock.patch("core.pasarela_negocio.urlopen", side_effect=respuestas) as abrir:
            pagina = self.verificar()
        self.assertContains(pagina, "Dulce SAS")
        config = self.config()
        self.assertIsNotNone(config.verificada_en)
        self.assertEqual(config.comercio_verificado, "Dulce SAS")
        peticion_publica, peticion_privada = (llamada.args[0] for llamada in abrir.call_args_list)
        self.assertTrue(peticion_publica.full_url.startswith("https://sandbox.wompi.co/v1/merchants/pub_test_"))
        self.assertEqual(peticion_privada.get_header("Authorization"), f"Bearer {PRIVADA}")

    def test_llave_publica_desconocida(self):
        with mock.patch("core.pasarela_negocio.urlopen", side_effect=error_http(404)):
            pagina = self.verificar()
        self.assertContains(pagina, "Wompi no reconoce la llave pública")
        self.assertIsNone(self.config().verificada_en)

    def test_llave_privada_rechazada(self):
        respuestas = [respuesta_json({"data": {"name": "Dulce"}}), error_http(401)]
        with mock.patch("core.pasarela_negocio.urlopen", side_effect=respuestas):
            pagina = self.verificar()
        self.assertContains(pagina, "Wompi rechazó la llave privada")
        self.assertIsNone(self.config().verificada_en)

    def test_wompi_caido(self):
        with mock.patch("core.pasarela_negocio.urlopen", side_effect=URLError("sin red")):
            pagina = self.verificar()
        self.assertContains(pagina, "No pudimos conectarnos con Wompi")

    def test_no_consulta_dos_veces_seguidas(self):
        with mock.patch("core.pasarela_negocio.urlopen", side_effect=error_http(404)) as abrir:
            self.verificar()
            pagina = self.verificar()
        self.assertEqual(abrir.call_count, 1)
        self.assertContains(pagina, "Espera 10 segundos")

    def test_activar_exige_verificacion(self):
        pagina = self.client.post(reverse("negocio_pagos_activar"), {"activa": "1"}, follow=True)
        self.assertContains(pagina, "Verifica tus llaves")
        self.assertFalse(self.config().activa)
        ConfiguracionPagos.objects.update(verificada_en="2026-01-01T00:00Z")
        self.client.post(reverse("negocio_pagos_activar"), {"activa": "1"})
        self.assertTrue(self.config().lista_para_cobrar)
        self.client.post(reverse("negocio_pagos_activar"), {"activa": "0"})
        self.assertFalse(self.config().activa)

    def test_borrar(self):
        self.client.post(reverse("negocio_pagos_eliminar"))
        self.assertFalse(ConfiguracionPagos.objects.exists())

    def test_solo_post(self):
        self.assertEqual(self.client.get(reverse("negocio_pagos_verificar")).status_code, 405)

    def test_verificacion_vieja_no_activa_llaves_nuevas(self):
        from .pasarela_negocio import ResultadoVerificacion

        def cambiar(config):
            self.guardar(secreto_integridad="test_integrity_Nuevo1234")
            return ResultadoVerificacion(ok=True, comercio="Llaves anteriores")

        with mock.patch("core.views_pagos.verificar_llaves", side_effect=cambiar):
            self.verificar()
        self.assertIsNone(self.config().verificada_en)
        self.assertFalse(self.config().activa)

    def test_respuesta_publica_malformada_no_verifica(self):
        with mock.patch("core.pasarela_negocio.urlopen", return_value=respuesta_json({"data": []})):
            self.verificar()
        self.assertIsNone(self.config().verificada_en)


class AislamientoYPermisosTests(PagosNegocioBase):
    def test_otro_negocio_no_ve_ni_borra_las_llaves(self):
        self.guardar()
        otro = crear_usuario("otro@correo.co")
        registrar_negocio(usuario=otro, datos=datos_negocio("Otra", "902"))
        self.client.force_login(otro)
        self.assertContains(self.client.get(reverse("negocio_pagos")), "Sin conectar")
        self.client.post(reverse("negocio_pagos_eliminar"))
        self.assertTrue(ConfiguracionPagos.objects.filter(empresa=self.empresa).exists())

    def test_empleado_sin_permiso_recibe_403(self):
        empleado = crear_usuario("cajero@correo.co")
        rol = Rol.objects.get(empresa=self.empresa, nombre="Cajero POS")
        Membresia.objects.create(usuario=empleado, empresa=self.empresa, rol=rol)
        self.client.force_login(empleado)
        self.assertEqual(self.client.get(reverse("negocio_pagos")).status_code, 403)
        self.assertEqual(self.client.post(reverse("negocio_pagos"), self.datos()).status_code, 403)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("negocio_pagos"))

    def test_administrador_ve_el_enlace_en_el_menu(self):
        self.assertContains(self.client.get(reverse("dashboard")), reverse("negocio_pagos"))


class RotacionTests(PagosNegocioBase):
    def test_migrar_desde_la_derivacion_de_secret_key(self):
        with override_settings(PAGOS_CLAVES_CIFRADO=""):
            self.guardar()
        with override_settings(PAGOS_CLAVES_CIFRADO=CLAVE):
            call_command("rotar_secretos_pago", desde_secret_key=True, stdout=io.StringIO())
            self.assertEqual(self.config().secreto_eventos, EVENTOS)

    def test_rotar_recifra_con_la_clave_nueva(self):
        self.guardar()
        nueva = Fernet.generate_key().decode()
        with override_settings(PAGOS_CLAVES_CIFRADO=f"{nueva},{CLAVE}"):
            call_command("rotar_secretos_pago", stdout=io.StringIO())
        with override_settings(PAGOS_CLAVES_CIFRADO=nueva):
            config = self.config()
            self.assertEqual(config.secreto_integridad, INTEGRIDAD)
            self.assertEqual(config.llave_privada, PRIVADA)


@override_settings(PAGOS_CLAVES_CIFRADO=CLAVE, WOMPI_PUBLIC_KEY=PUBLICA,
                   WOMPI_PRIVATE_KEY=PRIVADA, WOMPI_INTEGRITY_SECRET=INTEGRIDAD,
                   WOMPI_EVENTS_SECRET=EVENTOS)
class MigracionCredencialesTests(TransactionTestCase):
    def test_conserva_credenciales_anteriores_sin_activar_negocios(self):
        antes = [("core", "0020_configuracion_pagos")]
        despues = [("core", "0021_pagos_directos_auditoria")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(despues))
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(antes)
        apps = ejecutor.loader.project_state(antes).apps
        empresa = apps.get_model("core", "Empresa").objects.create(nombre="Histórico", nit="990", slug="historia")
        usuario = apps.get_model("core", "Usuario").objects.create(username="historia@c.co", email="historia@c.co")
        cliente = apps.get_model("core", "Cliente").objects.create(empresa=empresa, nombre="Cliente", numero_documento="1")
        factura = apps.get_model("core", "Factura").objects.create(
            empresa=empresa, numero=1, cliente=cliente, creada_por=usuario)
        pago = apps.get_model("core", "Pago").objects.create(
            empresa=empresa, factura=factura, referencia="HIST-1", monto_centavos=100)
        MigrationExecutor(connection).migrate(despues)
        from .models import Pago
        from .pasarelas import credenciales_pago

        nuevo = Pago.objects.get(pk=pago.pk)
        self.assertFalse(nuevo.pasarela_propia)
        self.assertEqual(credenciales_pago(nuevo).eventos, EVENTOS)
        self.assertFalse(ConfiguracionPagos.objects.exists())
