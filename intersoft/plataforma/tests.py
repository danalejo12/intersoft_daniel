"""Pruebas automatizadas de la consola interna /plataforma/."""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import EjecucionTarea, Empresa, Membresia, Rol, Usuario
from core.pasarela_negocio import ResultadoVerificacion
from core.tareas import ejecutar_pendientes
from suscripciones import cobros as cobros_suscripcion
from suscripciones.cobros import credenciales_intersoft
from suscripciones.models import (
    CobroSuscripcion,
    ConfiguracionSuscripciones,
    CuponPlan,
    HistorialSuscripcion,
    Plan,
    RecordatorioVencimiento,
    Suscripcion,
)
from suscripciones.services import cambiar_plan, crear_suscripcion_inicial, cupos_fundador_actuales

from . import auditoria
from .metricas import calcular_metricas_saas
from .models import AuditoriaPlataforma, ConfiguracionCobroPlataforma, RolPlataforma
from .totp import codigo_totp_actual


class _TotpAutoMixin:
    """Marca la sesión TOTP verificada tras force_login en pruebas que no prueban el flujo 2FA."""

    def setUp(self):
        super().setUp()
        original = self.client.force_login

        def _force_login_con_totp(user, backend=None):
            original(user, backend=backend)
            s = self.client.session
            s["plataforma_totp_verificado"] = str(user.pk)
            s.save()

        self.client.force_login = _force_login_con_totp


class PlataformaAccesoYRolesTests(_TotpAutoMixin, TestCase):
    """Verifica aislamiento is_staff, RolPlataforma y permisos por rol en /plataforma/."""

    def setUp(self):
        super().setUp()
        self.no_staff = Usuario.objects.create_user(
            username="cliente@test.co", email="cliente@test.co", password="x", is_staff=False, first_name="Ana", last_name="Prueba"
        )
        self.staff_sin_rol = Usuario.objects.create_user(
            username="sinrol@intersoft.co", email="sinrol@intersoft.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        self.dueno = self._crear_staff_con_rol("dueno@intersoft.co", RolPlataforma.Rol.DUENO)
        self.finanzas = self._crear_staff_con_rol("finanzas@intersoft.co", RolPlataforma.Rol.FINANZAS)
        self.soporte = self._crear_staff_con_rol("soporte@intersoft.co", RolPlataforma.Rol.SOPORTE)
        self.dev = self._crear_staff_con_rol("dev@intersoft.co", RolPlataforma.Rol.DESARROLLADOR)

    def _crear_staff_con_rol(self, correo: str, rol: str) -> Usuario:
        usuario = Usuario.objects.create_user(
            username=correo, email=correo, password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        RolPlataforma.objects.create(usuario=usuario, rol=rol, activo=True)
        return usuario

    def test_acceso_denegado_a_no_staff_y_a_staff_sin_rol(self):
        # Anónimo redirige al login
        self.assertEqual(self.client.get(reverse("plataforma_inicio")).status_code, 302)

        # No-staff recibe 403
        self.client.force_login(self.no_staff)
        self.assertEqual(self.client.get(reverse("plataforma_inicio")).status_code, 403)

        # Staff sin RolPlataforma recibe 403
        self.client.force_login(self.staff_sin_rol)
        self.assertEqual(self.client.get(reverse("plataforma_inicio")).status_code, 403)

        # Staff con RolPlataforma inactivo recibe 403
        RolPlataforma.objects.create(usuario=self.staff_sin_rol, rol=RolPlataforma.Rol.SOPORTE, activo=False)
        self.assertEqual(self.client.get(reverse("plataforma_inicio")).status_code, 403)

    def test_permisos_por_rol_y_secciones_proximamente(self):
        # Soporte: entra a inicio, negocios, pqrs, errores, comentarios; 403 en finanzas y operación
        self.client.force_login(self.soporte)
        for ruta in ("plataforma_inicio", "plataforma_negocios", "plataforma_pqrs", "plataforma_errores", "plataforma_comentarios"):
            resp = self.client.get(reverse(ruta))
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(reverse("plataforma_planes_cobros")).status_code, 403)
        self.assertEqual(self.client.get(reverse("plataforma_operacion")).status_code, 403)

        # Finanzas: ve planes y cobros, pero no puede editar llaves (403 en POST) ni entrar a operación
        self.client.force_login(self.finanzas)
        self.assertEqual(self.client.get(reverse("plataforma_planes_cobros")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("plataforma_planes_cobros"), {"accion": "guardar"}).status_code,
            403,
        )
        self.assertEqual(self.client.get(reverse("plataforma_operacion")).status_code, 403)

        # Desarrollador: ve inicio, errores y operación; 403 en planes y pqrs
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse("plataforma_operacion")).status_code, 200)
        self.assertEqual(self.client.get(reverse("plataforma_errores")).status_code, 200)
        self.assertEqual(self.client.get(reverse("plataforma_planes_cobros")).status_code, 403)
        self.assertEqual(self.client.get(reverse("plataforma_pqrs")).status_code, 403)

    def test_inicio_muestra_metricas_y_fallos_de_tareas_periodicas(self):
        emp1 = Empresa.objects.create(nombre="Negocio Trial", nit="900111", slug="negocio-trial", activa=True)
        emp2 = Empresa.objects.create(nombre="Negocio Pago", nit="900222", slug="negocio-pago", activa=True)
        cambiar_plan(emp2, "emprendedor", ciclo=Suscripcion.Ciclo.MENSUAL)

        plan_pro = Plan.objects.get(codigo="pro")
        CobroSuscripcion.objects.create(
            empresa=emp1,
            plan=plan_pro,
            ciclo=Suscripcion.Ciclo.MENSUAL,
            referencia="SUS-PEND-1",
            precio_lista=Decimal("149900.00"),
            monto=Decimal("149900.00"),
            estado=CobroSuscripcion.Estado.PENDIENTE,
        )
        CobroSuscripcion.objects.create(
            empresa=emp2,
            plan=plan_pro,
            ciclo=Suscripcion.Ciclo.MENSUAL,
            referencia="SUS-REV-1",
            precio_lista=Decimal("149900.00"),
            monto=Decimal("149900.00"),
            estado=CobroSuscripcion.Estado.REQUIERE_REVISION,
        )
        EjecucionTarea.objects.create(
            nombre="conciliar_cobros_suscripcion",
            ultima_ejecucion=timezone.now(),
            ejecuciones=12,
            fallos_seguidos=3,
            ultimo_error="Timeout consultando Wompi",
        )

        self.client.force_login(self.dueno)
        resp = self.client.get(reverse("plataforma_inicio"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["negocios_activos"], 2)
        self.assertEqual(resp.context["negocios_prueba"], 1)
        self.assertEqual(resp.context["negocios_plan_pago"], 1)
        self.assertEqual(resp.context["cobros_pendientes"], 1)
        self.assertEqual(resp.context["cobros_revision"], 1)
        self.assertContains(resp, "conciliar_cobros_suscripcion")
        self.assertContains(resp, "3 fallos")


class PlataformaLlavesYAuditoriaTests(_TotpAutoMixin, TestCase):
    """Verifica cifrado, ocultamiento de secretos en HTML, verificación, auditoría y credenciales_intersoft."""

    def setUp(self):
        super().setUp()
        self.dueno = Usuario.objects.create_user(
            username="dueno-llaves@intersoft.co", email="dueno-llaves@intersoft.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        RolPlataforma.objects.create(usuario=self.dueno, rol=RolPlataforma.Rol.DUENO, activo=True)

    def test_llaves_cifradas_no_aparecen_en_html_y_se_auditan_sin_secretos(self):
        self.client.force_login(self.dueno)
        llave_pub = "pub_test_1234567890ABCDEF"
        llave_priv = "prv_test_SECRET_PRIV_9876"
        sec_int = "test_integrity_SECRET_INT_4321"
        sec_ev = "test_events_SECRET_EV_5566"

        resp = self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "guardar",
                "modo": "pruebas",
                "llave_publica": llave_pub,
                "llave_privada": llave_priv,
                "secreto_integridad": sec_int,
                "secreto_eventos": sec_ev,
                "activa": "on",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        # La llave pública y los últimos 4 caracteres sí pueden mostrarse; los secretos completos JAMÁS
        self.assertIn(llave_pub, html)
        self.assertIn("••••9876", html)
        self.assertIn("••••4321", html)
        self.assertIn("••••5566", html)
        self.assertNotIn(llave_priv, html)
        self.assertNotIn(sec_int, html)
        self.assertNotIn(sec_ev, html)

        # Verificar que en BD quedaron cifradas y descifran bien
        config = ConfiguracionCobroPlataforma.obtener()
        self.assertNotEqual(config.llave_privada_cifrada, llave_priv)
        self.assertEqual(config.llave_privada, llave_priv)
        self.assertEqual(config.secreto_integridad, sec_int)
        self.assertEqual(config.secreto_eventos, sec_ev)

        # Verificar auditoría sin secretos
        registro = AuditoriaPlataforma.objects.get(accion="actualizar_llaves_wompi")
        self.assertEqual(registro.actor, self.dueno)
        texto_detalle = str(registro.detalle)
        self.assertNotIn(llave_priv, texto_detalle)
        self.assertNotIn(sec_int, texto_detalle)
        self.assertNotIn(sec_ev, texto_detalle)

        # Botón verificar reutiliza verificar_llaves y registra auditoría
        with mock.patch(
            "plataforma.views.verificar_llaves",
            return_value=ResultadoVerificacion(ok=True, comercio="InterSoft SAS Test"),
        ) as mock_verif:
            resp_ver = self.client.post(
                reverse("plataforma_planes_cobros"),
                {"accion": "verificar"},
                follow=True,
            )
        self.assertEqual(resp_ver.status_code, 200)
        mock_verif.assert_called_once()
        config.refresh_from_db()
        self.assertIsNotNone(config.verificada_en)
        self.assertEqual(config.comercio_verificado, "InterSoft SAS Test")
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="verificar_llaves_wompi").exists())

    def test_auditoria_sanitiza_claves_sensibles(self):
        registro = auditoria.registrar(
            actor=self.dueno,
            accion="prueba_sanitizado",
            detalle={"modo": "pruebas", "secreto_integridad": "NO_GUARDAR", "password": "123"},
        )
        self.assertEqual(registro.detalle, {"modo": "pruebas"})

    @override_settings(
        SUSCRIPCIONES_WOMPI_PUBLIC_KEY="pub_test_SETTINGS_FALLBACK_0000",
        SUSCRIPCIONES_WOMPI_PRIVATE_KEY="prv_test_SETTINGS_FALLBACK_0000",
        SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET="test_integrity_SETTINGS_0000",
        SUSCRIPCIONES_WOMPI_EVENTS_SECRET="test_events_SETTINGS_0000",
    )
    def test_credenciales_intersoft_prefiere_bd_sobre_settings(self):
        # 1. Sin configuración activa en BD -> usa settings
        cred_settings = credenciales_intersoft()
        self.assertEqual(cred_settings.publica, "pub_test_SETTINGS_FALLBACK_0000")
        self.assertEqual(cred_settings.integridad, "test_integrity_SETTINGS_0000")

        # 2. Al activar configuración en BD -> prefiere la base de datos sobre settings
        config = ConfiguracionCobroPlataforma.obtener()
        config.modo = ConfiguracionCobroPlataforma.Modo.PRUEBAS
        config.llave_publica = "pub_test_BASEDATOS_11112222"
        config.poner_secreto("llave_privada", "prv_test_BASEDATOS_33334444")
        config.poner_secreto("secreto_integridad", "test_integrity_BD_55556666")
        config.poner_secreto("secreto_eventos", "test_events_BD_77778888")
        config.activa = True
        config.save()

        cred_bd = credenciales_intersoft()
        self.assertEqual(cred_bd.publica, "pub_test_BASEDATOS_11112222")
        self.assertEqual(cred_bd.privada, "prv_test_BASEDATOS_33334444")
        self.assertEqual(cred_bd.integridad, "test_integrity_BD_55556666")
        self.assertEqual(cred_bd.eventos, "test_events_BD_77778888")


class PlataformaPlanesCobrosCortesiasYMetricasTests(_TotpAutoMixin, TestCase):
    """Pruebas del editor de planes, cobros, cortesías, fundadores y métricas SaaS."""

    def setUp(self):
        super().setUp()
        self.finanzas = self._crear_staff("finanzas-ops@intersoft.co", RolPlataforma.Rol.FINANZAS)
        self.soporte = self._crear_staff("soporte-ops@intersoft.co", RolPlataforma.Rol.SOPORTE)
        self.dev = self._crear_staff("dev-ops@intersoft.co", RolPlataforma.Rol.DESARROLLADOR)

    def _crear_staff(self, correo: str, rol: str) -> Usuario:
        usuario = Usuario.objects.create_user(
            username=correo, email=correo, password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        RolPlataforma.objects.create(usuario=usuario, rol=rol, activo=True)
        return usuario

    def test_editor_de_planes_permisos_validacion_gratis_y_auditoria(self):
        plan_emp = Plan.objects.get(codigo="emprendedor")
        plan_gratis = Plan.objects.get(codigo="gratis")
        url_emp = reverse("plataforma_editar_plan", args=[plan_emp.pk])
        url_gratis = reverse("plataforma_editar_plan", args=[plan_gratis.pk])

        # Soporte y Desarrollador reciben 403
        self.client.force_login(self.soporte)
        self.assertEqual(self.client.get(url_emp).status_code, 403)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(url_emp, {"nombre": "Hack"}).status_code, 403)

        # Finanzas puede editar límites (null=ilimitado), precios, features, comisión y activo
        self.client.force_login(self.finanzas)
        resp = self.client.post(
            url_emp,
            {
                "nombre": "Emprendedor Plus",
                "precio_mensual": "34900.00",
                "precio_anual": "349000.00",
                "comision_porcentaje": "3.50",
                "limite_productos": "",
                "limite_usuarios": "4",
                "features": ["marketplace", "pos", "multisede"],
                "activo": "on",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        plan_emp.refresh_from_db()
        self.assertEqual(plan_emp.nombre, "Emprendedor Plus")
        self.assertEqual(plan_emp.precio_mensual, Decimal("34900.00"))
        self.assertEqual(plan_emp.comision_porcentaje, Decimal("3.50"))
        self.assertIsNone(plan_emp.limites["productos"])
        self.assertEqual(plan_emp.limites["usuarios"], 4)
        self.assertEqual(plan_emp.features, ["marketplace", "pos", "multisede"])
        self.assertTrue(
            AuditoriaPlataforma.objects.filter(accion="editar_plan", objeto_id=str(plan_emp.pk)).exists()
        )

        # Validación: el plan gratis no puede tener precio > 0 ni desactivarse
        resp_gratis = self.client.post(
            url_gratis,
            {
                "nombre": "Gratis",
                "precio_mensual": "10000.00",
                "precio_anual": "0.00",
                "comision_porcentaje": "6.00",
                "limite_productos": "20",
                "limite_usuarios": "1",
                "features": ["marketplace"],
                # activo omitido -> False
            },
        )
        self.assertEqual(resp_gratis.status_code, 200)
        plan_gratis.refresh_from_db()
        self.assertEqual(plan_gratis.precio_mensual, Decimal("0.00"))
        self.assertTrue(plan_gratis.activo)

    def test_cobros_filtros_reconsultar_wompi_y_aplicar_manualmente(self):
        emp = Empresa.objects.create(nombre="Comercial Alfa", nit="901001", slug="comercial-alfa", activa=True)
        plan_neg = Plan.objects.get(codigo="negocio")
        plan_pro = Plan.objects.get(codigo="pro")

        cobro_rev = CobroSuscripcion.objects.create(
            empresa=emp,
            plan=plan_neg,
            ciclo=Suscripcion.Ciclo.MENSUAL,
            referencia="SUS-REV-MANUAL-1",
            precio_lista=Decimal("69900.00"),
            monto=Decimal("69900.00"),
            estado=CobroSuscripcion.Estado.REQUIERE_REVISION,
            detalle="Monto no coincide",
        )
        CobroSuscripcion.objects.create(
            empresa=emp,
            plan=plan_pro,
            ciclo=Suscripcion.Ciclo.ANUAL,
            referencia="SUS-PEN-FILTRO-2",
            precio_lista=Decimal("1499000.00"),
            monto=Decimal("1499000.00"),
            estado=CobroSuscripcion.Estado.PENDIENTE,
        )

        # Soporte recibe 403 en acciones de cobros
        self.client.force_login(self.soporte)
        self.assertEqual(
            self.client.post(
                reverse("plataforma_planes_cobros"),
                {"accion": "aplicar_cobro_manual", "cobro_id": str(cobro_rev.pk), "motivo": "Prueba"},
            ).status_code,
            403,
        )

        # Filtros por estado, plan y negocio
        self.client.force_login(self.finanzas)
        resp_filtro = self.client.get(
            reverse("plataforma_planes_cobros"),
            {"estado": CobroSuscripcion.Estado.PENDIENTE, "plan": "pro", "negocio": "Alfa"},
        )
        self.assertEqual(resp_filtro.status_code, 200)
        self.assertContains(resp_filtro, "SUS-PEN-FILTRO-2")
        referencias_filtradas = [c.referencia for c in resp_filtro.context["cobros_recientes"]]
        self.assertEqual(referencias_filtradas, ["SUS-PEN-FILTRO-2"])

        # Acción 1: Reconsultar en Wompi usa cobros.sincronizar_cobro(..., forzar=True) y registra auditoría
        with mock.patch(
            "plataforma.views.cobros_suscripcion.sincronizar_cobro",
            return_value=cobro_rev,
        ) as mock_sinc:
            resp_recons = self.client.post(
                reverse("plataforma_planes_cobros"),
                {"accion": "reconsultar_cobro", "cobro_id": str(cobro_rev.pk)},
                follow=True,
            )
        self.assertEqual(resp_recons.status_code, 200)
        mock_sinc.assert_called_once_with(cobro_rev, forzar=True)
        self.assertTrue(
            AuditoriaPlataforma.objects.filter(
                accion="reconsultar_cobro_wompi", objeto_id=str(cobro_rev.pk)
            ).exists()
        )

        # Acción 2: Aplicar manualmente exige motivo
        resp_sin_motivo = self.client.post(
            reverse("plataforma_planes_cobros"),
            {"accion": "aplicar_cobro_manual", "cobro_id": str(cobro_rev.pk), "motivo": "   "},
            follow=True,
        )
        self.assertEqual(resp_sin_motivo.status_code, 200)
        cobro_rev.refresh_from_db()
        self.assertEqual(cobro_rev.estado, CobroSuscripcion.Estado.REQUIERE_REVISION)

        # Con motivo válido: cambia plan, crea HistorialSuscripcion, marca aprobado y registra auditoría
        resp_manual = self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "aplicar_cobro_manual",
                "cobro_id": str(cobro_rev.pk),
                "motivo": "Transferencia verificada con soporte",
            },
            follow=True,
        )
        self.assertEqual(resp_manual.status_code, 200)
        cobro_rev.refresh_from_db()
        self.assertEqual(cobro_rev.estado, CobroSuscripcion.Estado.APROBADO)
        self.assertIn("Aplicado manualmente por", cobro_rev.detalle)
        self.assertEqual(emp.suscripcion.plan.codigo, "negocio")
        self.assertTrue(
            HistorialSuscripcion.objects.filter(
                suscripcion=emp.suscripcion,
                motivo__icontains="Transferencia verificada con soporte",
            ).exists()
        )
        self.assertTrue(
            AuditoriaPlataforma.objects.filter(
                accion="aplicar_cobro_manual", objeto_id=str(cobro_rev.pk)
            ).exists()
        )

    def test_cortesias_dias_gratis_y_plan_de_cortesia_con_historial_y_auditoria(self):
        emp = Empresa.objects.create(nombre="Tienda Sol", nit="902001", slug="tienda-sol", activa=True)
        sub = crear_suscripcion_inicial(emp)
        vence_inicial = sub.vence_en

        # Soporte recibe 403
        self.client.force_login(self.soporte)
        self.assertEqual(
            self.client.post(
                reverse("plataforma_planes_cobros"),
                {"accion": "otorgar_cortesia", "empresa": str(emp.pk), "dias": "10", "motivo": "Prueba"},
            ).status_code,
            403,
        )

        # Finanzas otorga 10 días gratis
        self.client.force_login(self.finanzas)
        resp_dias = self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "otorgar_cortesia",
                "empresa": str(emp.pk),
                "dias": "10",
                "motivo": "Extensión por onboarding",
            },
            follow=True,
        )
        self.assertEqual(resp_dias.status_code, 200)
        sub.refresh_from_db()
        self.assertAlmostEqual(
            (sub.vence_en - vence_inicial).total_seconds(),
            timedelta(days=10).total_seconds(),
            delta=5,
        )
        self.assertTrue(
            HistorialSuscripcion.objects.filter(
                suscripcion=sub, motivo__icontains="Extensión por onboarding"
            ).exists()
        )
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="otorgar_cortesia").exists())

        # Finanzas otorga plan Pro de cortesía por 15 días
        plan_pro = Plan.objects.get(codigo="pro")
        resp_plan = self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "otorgar_cortesia",
                "empresa": str(emp.pk),
                "plan": str(plan_pro.pk),
                "dias": "15",
                "motivo": "Alianza estratégica",
            },
            follow=True,
        )
        self.assertEqual(resp_plan.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.plan, plan_pro)
        self.assertEqual(sub.estado, Suscripcion.Estado.ACTIVA)
        self.assertFalse(sub.es_fundador)
        self.assertTrue(
            HistorialSuscripcion.objects.filter(
                suscripcion=sub, plan_nuevo=plan_pro, motivo__icontains="Alianza estratégica"
            ).exists()
        )

    def test_cupos_fundador_configurables_en_base_de_datos(self):
        self.client.force_login(self.finanzas)
        resp = self.client.post(
            reverse("plataforma_planes_cobros"),
            {"accion": "actualizar_cupos_fundador", "cupos_fundador": "1"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ConfiguracionSuscripciones.obtener().cupos_fundador, 1)
        self.assertEqual(cupos_fundador_actuales(), 1)
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="actualizar_cupos_fundador").exists())

        # Con cupo = 1, la primera empresa paga obtiene fundador y la segunda ya no
        emp1 = Empresa.objects.create(nombre="Fundadora 1", nit="903001", slug="fundadora-1", activa=True)
        emp2 = Empresa.objects.create(nombre="Normal 2", nit="903002", slug="normal-2", activa=True)
        sub1 = cambiar_plan(emp1, "emprendedor", Suscripcion.Ciclo.MENSUAL)
        sub2 = cambiar_plan(emp2, "emprendedor", Suscripcion.Ciclo.MENSUAL)
        self.assertTrue(sub1.es_fundador)
        self.assertEqual(sub1.descuento_porcentaje, Decimal("50.00"))
        self.assertFalse(sub2.es_fundador)
        self.assertEqual(sub2.descuento_porcentaje, Decimal("0.00"))

    def test_metricas_mrr_con_descuento_fundador_arr_conversion_vencimientos_e_ingresos(self):
        ahora = timezone.now()
        # Aseguramos cupo fundador = 1 para probar 1 con 50% de descuento y 1 sin descuento
        cfg = ConfiguracionSuscripciones.obtener()
        cfg.cupos_fundador = 1
        cfg.save(update_fields=["cupos_fundador"])

        # Empresa 1: Plan Emprendedor mensual ($29.900) con 50% descuento fundador -> $14.950 MRR
        emp_fund = Empresa.objects.create(nombre="MRR Fundador", nit="904001", slug="mrr-fund", activa=True)
        sub_fund = cambiar_plan(emp_fund, "emprendedor", Suscripcion.Ciclo.MENSUAL)
        self.assertEqual(sub_fund.descuento_porcentaje, Decimal("50.00"))

        # Empresa 2: Plan Pro anual ($1.499.000 / 12 = $124.916,666...) sin descuento
        emp_anual = Empresa.objects.create(nombre="MRR Anual", nit="904002", slug="mrr-anual", activa=True)
        cambiar_plan(emp_anual, "pro", Suscripcion.Ciclo.ANUAL)

        # Empresa 3: En TRIAL que vence en 3 días (cuenta en prueba y en vencimientos próximos 7d)
        emp_trial = Empresa.objects.create(nombre="Trial Corto", nit="904003", slug="trial-corto", activa=True)
        sub_trial = crear_suscripcion_inicial(emp_trial)
        sub_trial.vence_en = ahora + timedelta(days=3)
        sub_trial.save(update_fields=["vence_en"])

        # Cobro aprobado este mes
        plan_emp = Plan.objects.get(codigo="emprendedor")
        CobroSuscripcion.objects.create(
            empresa=emp_fund,
            plan=plan_emp,
            ciclo=Suscripcion.Ciclo.MENSUAL,
            referencia="SUS-APROB-MET-1",
            precio_lista=Decimal("29900.00"),
            descuento_porcentaje=Decimal("50.00"),
            monto=Decimal("14950.00"),
            estado=CobroSuscripcion.Estado.APROBADO,
            resuelto_en=ahora,
        )

        metricas = calcular_metricas_saas(ahora=ahora)
        esperado_mrr = (Decimal("14950.00") + (Decimal("1499000.00") / Decimal("12"))).quantize(Decimal("0.01"))
        self.assertEqual(metricas["mrr"], esperado_mrr)
        self.assertEqual(metricas["arr"], (esperado_mrr * Decimal("12")).quantize(Decimal("0.01")))
        self.assertEqual(metricas["negocios_prueba"], 1)
        self.assertEqual(metricas["convertidos_30d"], 2)
        self.assertEqual(metricas["base_trial_30d"], 3)
        self.assertEqual(metricas["total_vencimientos_7d"], 1)
        self.assertEqual(len(metricas["ingresos_por_mes"]), 6)
        self.assertEqual(metricas["total_ingresos_6m"], Decimal("14950.00"))

        self.client.force_login(self.finanzas)
        resp = self.client.get(reverse("plataforma_inicio"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ingresos cobrados por mes")


class SaludYSwaggerTests(TestCase):
    """Verifica el endpoint /salud/ y el acceso restringido a Swagger en producción."""

    def test_salud_responde_200_con_bd_activa_y_503_si_falla(self):
        resp_ok = self.client.get(reverse("salud"))
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.json()["estado"], "ok")

        with mock.patch("core.views_salud.connections") as mock_conns:
            mock_conns.__getitem__.return_value.cursor.side_effect = RuntimeError("BD caída")
            resp_err = self.client.get(reverse("salud"))
        self.assertEqual(resp_err.status_code, 503)

    @override_settings(DEBUG=False)
    def test_swagger_restringido_a_is_staff(self):
        no_staff = Usuario.objects.create_user(
            username="nostaff-api@test.co", email="nostaff-api@test.co", password="x", is_staff=False, first_name="Ana", last_name="Prueba"
        )
        staff = Usuario.objects.create_user(
            username="staff-api@test.co", email="staff-api@test.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )

        # Anónimo y no-staff no pueden acceder
        self.assertIn(self.client.get(reverse("api_schema")).status_code, (401, 403))
        self.assertIn(self.client.get(reverse("api_docs")).status_code, (401, 403))

        self.client.force_login(no_staff)
        self.assertEqual(self.client.get(reverse("api_schema")).status_code, 403)
        self.assertEqual(self.client.get(reverse("api_docs")).status_code, 403)

        # is_staff sí accede
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("api_schema")).status_code, 200)
        self.assertEqual(self.client.get(reverse("api_docs")).status_code, 200)


class PlataformaEntrarComoYAnunciosTests(_TotpAutoMixin, TestCase):
    """Pruebas de «Entrar como» (solo lectura/escritura), aislamiento, auditoría y anuncios globales."""

    def setUp(self):
        super().setUp()
        self.empresa = Empresa.objects.create(
            nombre="Comercio Soporte", nit="950001", slug="comercio-soporte", activa=True
        )
        self.soporte = Usuario.objects.create_user(
            username="sop-entrar@intersoft.co", email="sop-entrar@intersoft.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        RolPlataforma.objects.create(usuario=self.soporte, rol=RolPlataforma.Rol.SOPORTE, activo=True)

        self.finanzas = Usuario.objects.create_user(
            username="fin-entrar@intersoft.co", email="fin-entrar@intersoft.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        RolPlataforma.objects.create(usuario=self.finanzas, rol=RolPlataforma.Rol.FINANZAS, activo=True)

        self.cliente_normal = Usuario.objects.create_user(
            username="normal-entrar@test.co", email="normal-entrar@test.co", password="x", is_staff=False, first_name="Ana", last_name="Prueba"
        )

    def test_entrar_como_solo_lectura_franja_roja_auditoria_y_salir(self):
        # Finanzas y usuario normal no pueden entrar a /plataforma/negocios/
        self.client.force_login(self.finanzas)
        self.assertEqual(self.client.get(reverse("plataforma_negocios")).status_code, 403)
        self.client.force_login(self.cliente_normal)
        self.assertEqual(self.client.get(reverse("plataforma_negocios")).status_code, 403)

        # Soporte entra en modo solo lectura
        self.client.force_login(self.soporte)
        resp_entrar = self.client.post(
            reverse("plataforma_negocios"),
            {"accion": "entrar_como", "empresa_id": str(self.empresa.pk), "modo": "lectura"},
            follow=True,
        )
        self.assertEqual(resp_entrar.status_code, 200)
        self.assertContains(resp_entrar, "MODO SOPORTE")
        self.assertContains(resp_entrar, self.empresa.nombre)
        self.assertContains(resp_entrar, "Salir de soporte")

        # POST en /panel/ bloqueado con 403 en modo solo lectura
        resp_post_panel = self.client.post(
            reverse("negocio_datos"),
            {"nombre": "Cambio Prohibido"},
        )
        self.assertEqual(resp_post_panel.status_code, 403)

        # Auditoría de entrada registrada
        reg_entrada = AuditoriaPlataforma.objects.get(accion="entrar_modo_soporte")
        self.assertEqual(reg_entrada.actor, self.soporte)
        self.assertEqual(reg_entrada.objeto_id, str(self.empresa.pk))
        self.assertEqual(reg_entrada.detalle["modo"], "lectura")

        # Salir de soporte limpia sesión y registra auditoría
        resp_salir = self.client.post(reverse("plataforma_salir_soporte"), follow=True)
        self.assertEqual(resp_salir.status_code, 200)
        self.assertNotIn("plataforma_soporte", self.client.session)
        reg_salida = AuditoriaPlataforma.objects.get(accion="salir_modo_soporte")
        self.assertEqual(reg_salida.detalle["modo"], "lectura")

    def test_entrar_como_escritura_y_aislamiento_sesion(self):
        # Usuario no-staff con sesión manipulada no puede activar modo soporte
        self.client.force_login(self.cliente_normal)
        session = self.client.session
        session["plataforma_soporte"] = {"empresa_id": str(self.empresa.pk), "solo_lectura": False}
        session.save()
        resp_panel = self.client.get(reverse("dashboard"))
        self.assertEqual(resp_panel.status_code, 302)  # Redirige a negocio_registrar al no tener membresía

        # Soporte con modo escritura sí puede publicar en /panel/
        self.client.force_login(self.soporte)
        self.client.post(
            reverse("plataforma_negocios"),
            {"accion": "entrar_como", "empresa_id": str(self.empresa.pk), "modo": "escritura"},
        )
        reg = AuditoriaPlataforma.objects.filter(accion="entrar_modo_soporte").first()
        self.assertEqual(reg.detalle["modo"], "escritura")

    def test_anuncios_globales_visibles_en_panel_segun_vigencia(self):
        self.client.force_login(self.soporte)
        # Publicar anuncio vigente
        resp = self.client.post(
            reverse("plataforma_negocios"),
            {
                "accion": "crear_anuncio",
                "titulo": "Mantenimiento nocturno",
                "mensaje": "Ventana de mantenimiento el domingo a las 2 a.m.",
                "tipo": "mantenimiento",
                "activo": "on",
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="crear_anuncio_global").exists())

        # Entrar al panel del negocio y verificar que el anuncio se muestra
        self.client.post(
            reverse("plataforma_negocios"),
            {"accion": "entrar_como", "empresa_id": str(self.empresa.pk), "modo": "lectura"},
        )
        resp_panel = self.client.get(reverse("dashboard"))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertContains(resp_panel, "Mantenimiento nocturno")


class PlataformaCuponesPreciosRecordatoriosFlagsYTotpTests(TestCase):
    """Pruebas de CuponPlan, /precios/, recordatorios 7/3/1d, FeatureFlag y 2FA/TOTP obligatorio."""

    def setUp(self):
        self.dueno = Usuario.objects.create_user(
            username="dueno-2fa@intersoft.co", email="dueno-2fa@intersoft.co", password="x", is_staff=True, first_name="Ana", last_name="Prueba"
        )
        self.rol_dueno = RolPlataforma.objects.create(
            usuario=self.dueno, rol=RolPlataforma.Rol.DUENO, activo=True
        )
        self.empresa = Empresa.objects.create(
            nombre="Negocio Cupon", nit="960001", slug="negocio-cupon", email="cupon@neg.co", activa=True
        )
        self.admin_neg = Usuario.objects.create_user(
            username="admin-cup@neg.co", email="admin-cup@neg.co", password="x", first_name="Ana", last_name="Prueba"
        )
        rol_neg = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.admin_neg, empresa=self.empresa, rol=rol_neg, activa=True)

    def test_totp_obligatorio_enrolamiento_y_verificacion(self):
        self.client.force_login(self.dueno)

        # Sin TOTP verificado en sesión -> redirige 302 a /plataforma/2fa/
        resp_redir = self.client.get(reverse("plataforma_inicio"))
        self.assertEqual(resp_redir.status_code, 302)
        self.assertIn(reverse("plataforma_totp"), resp_redir.url)

        # GET /plataforma/2fa/ genera secreto de enrolamiento en sesión
        resp_get = self.client.get(reverse("plataforma_totp"))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "data:image/svg+xml;base64,")
        secreto = self.client.session["plataforma_totp_setup"]

        # Código inválido es rechazado
        resp_bad = self.client.post(reverse("plataforma_totp"), {"codigo": "000000"})
        self.assertEqual(resp_bad.status_code, 200)
        self.rol_dueno.refresh_from_db()
        self.assertFalse(self.rol_dueno.totp_activo)

        # Código TOTP válido activa 2FA y permite entrar a /plataforma/
        codigo_ok = codigo_totp_actual(secreto)
        resp_ok = self.client.post(reverse("plataforma_totp"), {"codigo": codigo_ok}, follow=True)
        self.assertEqual(resp_ok.status_code, 200)
        self.rol_dueno.refresh_from_db()
        self.assertTrue(self.rol_dueno.totp_activo)
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="activar_totp").exists())
        self.assertEqual(self.client.get(reverse("plataforma_inicio")).status_code, 200)

    def test_cupon_plan_cotizar_iniciar_cobro_y_gestion_plataforma(self):
        # Enrolar rápido en sesión para usar /plataforma/planes-cobros/
        self.client.force_login(self.dueno)
        s = self.client.session
        s["plataforma_totp_verificado"] = str(self.dueno.pk)
        s.save()

        # Crear cupón desde /plataforma/planes-cobros/
        resp_cup = self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "crear_cupon",
                "codigo": "promo20",
                "tipo": CuponPlan.Tipo.PORCENTAJE,
                "valor": "20.00",
                "usos_maximos": "1",
                "activo": "on",
            },
            follow=True,
        )
        self.assertEqual(resp_cup.status_code, 200)
        cupon = CuponPlan.objects.get(codigo="PROMO20")
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="crear_cupon_plan").exists())

        # Ocupar cupos fundador para probar cupón puro
        cfg = ConfiguracionSuscripciones.obtener()
        cfg.cupos_fundador = 0
        cfg.save(update_fields=["cupos_fundador"])

        sub = crear_suscripcion_inicial(self.empresa)
        plan_emp = Plan.objects.get(codigo="emprendedor")  # 29900.00
        precio, desc, monto = cobros_suscripcion.cotizar(sub, plan_emp, Suscripcion.Ciclo.MENSUAL, cupon=cupon)
        self.assertEqual(precio, Decimal("29900.00"))
        self.assertEqual(monto, Decimal("23920"))
        self.assertEqual(desc, Decimal("20.00"))

        # Aplicar cobro y aprobar transacción -> incrementa usos_actuales y agota cupón (usos_maximos=1)
        with override_settings(
            SUSCRIPCIONES_WOMPI_PUBLIC_KEY="pub_test_123456",
            SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET="test_integrity_123456",
        ):
            cobro = cobros_suscripcion.iniciar_cobro(
                empresa=self.empresa,
                plan=plan_emp,
                ciclo=Suscripcion.Ciclo.MENSUAL,
                usuario=self.admin_neg,
                cupon_codigo="PROMO20",
            )
            self.assertEqual(cobro.monto, Decimal("23920"))
            cobros_suscripcion.aplicar_transaccion(
                {
                    "id": "tx-cup-1",
                    "reference": cobro.referencia,
                    "status": "APPROVED",
                    "amount_in_cents": cobro.monto_centavos,
                    "currency": "COP",
                    "payment_method_type": "CARD",
                }
            )
        cupon.refresh_from_db()
        self.assertEqual(cupon.usos_actuales, 1)
        self.assertFalse(cupon.esta_vigente())

        with self.assertRaises(ValidationError):
            cobros_suscripcion.cotizar(sub, plan_emp, Suscripcion.Ciclo.MENSUAL, cupon=cupon)

    def test_pagina_publica_precios_y_feature_flag_por_negocio(self):
        # /precios/ es pública y muestra los planes activos
        resp_precios = self.client.get(reverse("precios_publicos"))
        self.assertEqual(resp_precios.status_code, 200)
        self.assertContains(resp_precios, "Emprendedor")
        self.assertContains(resp_precios, "Pro")

        # Empresa en plan gratis no tiene 'multisede'
        sub = crear_suscripcion_inicial(self.empresa)
        cambiar_plan(self.empresa, "gratis")
        sub.refresh_from_db()
        self.assertFalse(sub.puede("multisede"))

        # Desde /plataforma/planes-cobros/ se activa FeatureFlag('multisede') para esta empresa
        self.client.force_login(self.dueno)
        s = self.client.session
        s["plataforma_totp_verificado"] = str(self.dueno.pk)
        s.save()
        self.client.post(
            reverse("plataforma_planes_cobros"),
            {
                "accion": "guardar_feature_flag",
                "empresa": str(self.empresa.pk),
                "codigo": "multisede",
                "habilitado": "on",
            },
        )
        self.assertTrue(sub.puede("multisede"))
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="actualizar_feature_flag").exists())

    def test_recordatorios_vencimiento_7_3_1_dias_idempotentes(self):
        sub = crear_suscripcion_inicial(self.empresa)
        ahora = timezone.now()
        sub.vence_en = ahora + timedelta(days=3)
        sub.save(update_fields=["vence_en"])

        mail.outbox.clear()
        res1 = ejecutar_pendientes(forzar=True, solo=["recordatorios_vencimiento_plan"])
        self.assertEqual(res1["recordatorios_vencimiento_plan"], "ok")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/panel/suscripcion/", mail.outbox[0].body)
        self.assertEqual(RecordatorioVencimiento.objects.filter(suscripcion=sub, dias_antes=3).count(), 1)

        # Segunda ejecución el mismo día -> NO vuelve a enviar el mismo recordatorio
        mail.outbox.clear()
        res2 = ejecutar_pendientes(forzar=True, solo=["recordatorios_vencimiento_plan"])
        self.assertEqual(res2["recordatorios_vencimiento_plan"], "ok")
        self.assertEqual(len(mail.outbox), 0)




