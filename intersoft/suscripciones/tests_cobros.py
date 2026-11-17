"""Cobro de planes con la cuenta de Wompi de Intersoft."""
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Producto
from core.pagos import calcular_checksum

from . import cobros
from .models import CobroSuscripcion, Plan, Suscripcion
from .services import CUPOS_FUNDADOR, cambiar_plan
from .tests import LLAVES_PRUEBA, aprobar_cobro, crear_empresa_con_usuario

Estado = CobroSuscripcion.Estado


@override_settings(**LLAVES_PRUEBA)
class CobroPlanTests(TestCase):
    def setUp(self):
        self.empresa, self.usuario = crear_empresa_con_usuario("c")
        self.client.force_login(self.usuario)
        parche = mock.patch.object(cobros, "buscar_transaccion_por_referencia", return_value=None)
        self.buscar = parche.start()
        self.addCleanup(parche.stop)

    def suscripcion(self):
        return Suscripcion.objects.select_related("plan").get(empresa=self.empresa)

    def pedir_plan(self, plan="pro", ciclo="MENSUAL"):
        return self.client.post(reverse("suscripcion_panel"), {"plan": plan, "ciclo": ciclo})

    def test_plan_pago_va_a_wompi_y_no_se_activa_sin_pagar(self):
        respuesta = self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        self.assertTrue(respuesta.url.startswith("https://checkout.wompi.co/p/"))
        self.assertIn(cobro.referencia, respuesta.url)
        self.assertIn("pub_test_intersoft", respuesta.url)
        self.assertNotIn("test_integrity_intersoft", respuesta.url)  # el secreto nunca sale
        self.assertEqual(self.suscripcion().estado, Suscripcion.Estado.TRIAL)
        self.assertEqual(self.suscripcion().plan.codigo, "negocio")

    def test_precio_con_descuento_de_fundador_congelado(self):
        self.pedir_plan("pro", "ANUAL")
        cobro = CobroSuscripcion.objects.get()
        self.assertEqual(cobro.precio_lista, Decimal("1499000.00"))
        self.assertEqual(cobro.descuento_porcentaje, Decimal("50.00"))
        self.assertEqual(cobro.monto, Decimal("749500"))

    def test_sin_cupo_de_fundador_cobra_precio_completo(self):
        for i in range(CUPOS_FUNDADOR):
            otra, _ = crear_empresa_con_usuario(f"f{i}")
            Suscripcion.objects.filter(empresa=otra).update(es_fundador=True, descuento_porcentaje=Decimal("50"))
        self.pedir_plan("emprendedor")
        self.assertEqual(CobroSuscripcion.objects.get().monto, Decimal("29900"))

    def test_volver_de_wompi_aprobado_activa_el_plan(self):
        self.pedir_plan("pro", "ANUAL")
        cobro = CobroSuscripcion.objects.get()
        self.buscar.return_value = {
            "id": "tx-9", "reference": cobro.referencia, "status": "APPROVED",
            "amount_in_cents": cobro.monto_centavos, "currency": "COP", "payment_method_type": "NEQUI",
        }
        pagina = self.client.get(reverse("suscripcion_cobro", args=[cobro.pk]))
        self.assertContains(pagina, "Pago aprobado")
        sub = self.suscripcion()
        self.assertEqual((sub.plan.codigo, sub.estado, sub.ciclo), ("pro", "ACTIVA", "ANUAL"))
        self.assertTrue(sub.es_fundador)
        cobro.refresh_from_db()
        self.assertEqual((cobro.estado, cobro.metodo_pago), (Estado.APROBADO, "NEQUI"))

    def test_aprobar_dos_veces_no_suma_dias_dos_veces(self):
        self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        aprobar_cobro(cobro)
        vence = self.suscripcion().vence_en
        aprobar_cobro(cobro)
        self.assertEqual(self.suscripcion().vence_en, vence)
        self.assertEqual(self.suscripcion().historial.filter(motivo__startswith="Pago Wompi").count(), 1)

    def test_rechazado_no_cambia_el_plan(self):
        self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        aprobar_cobro(cobro, status="DECLINED", status_message="Fondos insuficientes")
        cobro.refresh_from_db()
        self.assertEqual((cobro.estado, cobro.detalle), (Estado.RECHAZADO, "Fondos insuficientes"))
        self.assertEqual(self.suscripcion().estado, Suscripcion.Estado.TRIAL)

    def test_monto_alterado_queda_en_revision_sin_activar(self):
        self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        with self.assertLogs("suscripciones.cobros", level="CRITICAL"):
            aprobar_cobro(cobro, amount_in_cents=100)
        cobro.refresh_from_db()
        self.assertEqual(cobro.estado, Estado.REQUIERE_REVISION)
        self.assertEqual(self.suscripcion().estado, Suscripcion.Estado.TRIAL)

    def test_renovar_suma_dias_al_vencimiento_actual(self):
        self.pedir_plan()
        aprobar_cobro(CobroSuscripcion.objects.get())
        vence = self.suscripcion().vence_en
        self.pedir_plan()  # renovar el mismo plan y ciclo
        aprobar_cobro(CobroSuscripcion.objects.filter(estado=Estado.PENDIENTE).get())
        self.assertEqual(self.suscripcion().vence_en, vence + timedelta(days=30))

    def test_no_cobra_un_plan_cuyos_limites_ya_se_superan(self):
        Plan.objects.filter(codigo="emprendedor").update(limites={"productos": 2, "usuarios": 2})
        for i in range(3):
            Producto.objects.create(empresa=self.empresa, codigo=f"P{i}", nombre=f"P{i}", precio=1)
        respuesta = self.client.post(reverse("suscripcion_panel"), {"plan": "emprendedor", "ciclo": "MENSUAL"},
                                     follow=True)
        self.assertContains(respuesta, "excede sus límites")
        self.assertFalse(CobroSuscripcion.objects.exists())

    def test_plan_gratis_cambia_sin_pago(self):
        self.pedir_plan("gratis")
        self.assertFalse(CobroSuscripcion.objects.exists())
        self.assertEqual(self.suscripcion().plan.codigo, "gratis")

    @override_settings(SUSCRIPCIONES_WOMPI_PUBLIC_KEY="")
    def test_sin_llaves_no_activa_ni_crea_cobro(self):
        respuesta = self.client.post(reverse("suscripcion_panel"), {"plan": "pro", "ciclo": "MENSUAL"}, follow=True)
        self.assertContains(respuesta, "todavía no está habilitado")
        self.assertFalse(CobroSuscripcion.objects.exists())
        self.assertEqual(self.suscripcion().estado, Suscripcion.Estado.TRIAL)

    def test_otra_empresa_no_ve_el_cobro(self):
        self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        _, intruso = crear_empresa_con_usuario("x")
        self.client.force_login(intruso)
        self.assertEqual(self.client.get(reverse("suscripcion_cobro", args=[cobro.pk])).status_code, 404)

    def test_un_id_de_otra_transaccion_no_aprueba(self):
        self.pedir_plan()
        cobro = CobroSuscripcion.objects.get()
        ajena = {"id": "tx-otra", "reference": "OTRA", "status": "APPROVED",
                 "amount_in_cents": cobro.monto_centavos, "currency": "COP"}
        with mock.patch.object(cobros, "consultar_transaccion", return_value=ajena):
            self.client.get(reverse("suscripcion_cobro", args=[cobro.pk]), {"id": "tx-otra"})
        cobro.refresh_from_db()
        self.assertEqual(cobro.estado, Estado.PENDIENTE)


@override_settings(**LLAVES_PRUEBA)
class WebhookYConciliacionTests(TestCase):
    def setUp(self):
        self.empresa, self.usuario = crear_empresa_con_usuario("w")
        self.cobro = cobros.iniciar_cobro(empresa=self.empresa, plan="pro", ciclo="MENSUAL", usuario=self.usuario)

    def transaccion(self, status="APPROVED"):
        return {"id": "tx-1", "reference": self.cobro.referencia, "status": status,
                "amount_in_cents": self.cobro.monto_centavos, "currency": "COP"}

    def evento(self, secreto="test_events_intersoft"):
        evento = {
            "event": "transaction.updated",
            "data": {"transaction": self.transaccion()},
            "signature": {"properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"]},
            "timestamp": 1700000000,
        }
        evento["signature"]["checksum"] = calcular_checksum(evento, secreto)
        return evento

    def enviar(self, evento):
        return self.client.post(reverse("wompi_webhook_suscripciones"), json.dumps(evento),
                                content_type="application/json")

    def test_webhook_firmado_activa_el_plan(self):
        with mock.patch("suscripciones.views_panel.consultar_transaccion", return_value=self.transaccion()):
            self.assertEqual(self.enviar(self.evento()).status_code, 200)
        self.cobro.refresh_from_db()
        self.assertEqual(self.cobro.estado, Estado.APROBADO)
        self.assertEqual(Suscripcion.objects.get(empresa=self.empresa).plan.codigo, "pro")

    def test_webhook_con_firma_falsa_se_rechaza(self):
        respuesta = self.enviar(self.evento(secreto="otro"))
        self.assertEqual(respuesta.status_code, 400)
        self.cobro.refresh_from_db()
        self.assertEqual(self.cobro.estado, Estado.PENDIENTE)

    def test_webhook_si_wompi_no_responde_pide_reintento(self):
        with mock.patch("suscripciones.views_panel.consultar_transaccion", return_value=None):
            self.assertEqual(self.enviar(self.evento()).status_code, 503)

    def test_conciliacion_aprueba_pendientes_y_anula_abandonados(self):
        viejo = cobros.iniciar_cobro(empresa=self.empresa, plan="pro", ciclo="ANUAL", usuario=self.usuario)
        CobroSuscripcion.objects.filter(pk=viejo.pk).update(creado_en=timezone.now() - timedelta(hours=49))

        def buscar(referencia, llaves):
            return self.transaccion() if referencia == self.cobro.referencia else None

        with mock.patch.object(cobros, "buscar_transaccion_por_referencia", side_effect=buscar):
            salida = StringIO()
            call_command("conciliar_cobros_suscripcion", stdout=salida)
        self.assertIn("Aprobados: 1", salida.getvalue())
        self.assertIn("Anulados sin pago: 1", salida.getvalue())
        viejo.refresh_from_db()
        self.assertEqual(viejo.estado, Estado.ANULADO)

    def test_pago_tardio_de_un_cobro_anulado_igual_activa(self):
        CobroSuscripcion.objects.filter(pk=self.cobro.pk).update(estado=Estado.ANULADO)
        cobros.aplicar_transaccion(self.transaccion())
        self.cobro.refresh_from_db()
        self.assertEqual(self.cobro.estado, Estado.APROBADO)

    def test_fundador_se_respeta_aunque_se_llenen_los_cupos_mientras_paga(self):
        self.assertEqual(self.cobro.descuento_porcentaje, Decimal("50.00"))
        for i in range(CUPOS_FUNDADOR):
            otra, _ = crear_empresa_con_usuario(f"g{i}")
            Suscripcion.objects.filter(empresa=otra).update(es_fundador=True, descuento_porcentaje=Decimal("50"))
        cobros.aplicar_transaccion(self.transaccion())
        self.assertTrue(Suscripcion.objects.get(empresa=self.empresa).es_fundador)

    def test_api_plan_pago_devuelve_enlace_de_pago(self):
        from rest_framework.test import APIClient
        api = APIClient()
        api.force_authenticate(self.usuario)
        respuesta = api.post(reverse("api_suscripcion_cambiar_plan"), {"plan": "negocio", "ciclo": "MENSUAL"},
                             format="json")
        self.assertEqual(respuesta.status_code, 202)
        self.assertTrue(respuesta.json()["checkout_url"].startswith("https://checkout.wompi.co/p/"))

    def test_cambiar_plan_directo_sigue_disponible_para_soporte(self):
        # El servicio no cobra: lo usa el pago aprobado y el /admin/ (soporte); las vistas exigen el pago
        sub = cambiar_plan(self.empresa, "pro")
        self.assertEqual(sub.plan.codigo, "pro")
