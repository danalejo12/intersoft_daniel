"""Suite de pruebas automatizadas para la aplicación `suscripciones`."""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.views import APIView

from core.models import Empresa, Membresia, Producto, Rol, Usuario

from .exceptions import LimitePlanExcedido, verificar_limite
from .cobros import aplicar_transaccion
from .models import CobroSuscripcion, HistorialSuscripcion, Plan, Suscripcion
from .permissions import RequiereFeature
from .services import (
    CUPOS_FUNDADOR,
    CanalVenta,
    DowngradeNoPermitido,
     calcular_comision,
    cambiar_plan,
    crear_suscripcion_inicial,
    uso_actual,
    verificar_vencimientos,
)


LLAVES_PRUEBA = {
    "SUSCRIPCIONES_WOMPI_PUBLIC_KEY": "pub_test_intersoft",
    "SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET": "test_integrity_intersoft",
    "SUSCRIPCIONES_WOMPI_EVENTS_SECRET": "test_events_intersoft",
    "SUSCRIPCIONES_WOMPI_PRIVATE_KEY": "prv_test_intersoft",
}


def aprobar_cobro(cobro, **cambios):
    """Simula la transacción aprobada que Wompi devolvería al consultar el cobro."""
    return aplicar_transaccion({
        "id": "tx-1", "reference": cobro.referencia, "status": "APPROVED",
        "amount_in_cents": cobro.monto_centavos, "currency": "COP", "payment_method_type": "CARD", **cambios,
    })


def crear_empresa_con_usuario(sufijo: str):
    """Helper de pruebas: crea una empresa, usuario, rol admin y membresía activa."""
    usuario = Usuario.objects.create_user(
        username=f"user-{sufijo}@test.co",
        email=f"user-{sufijo}@test.co",
        password="ClaveSegura#2026",
        first_name=f"Usuario {sufijo}",
    )
    empresa = Empresa.objects.create(
        nombre=f"Empresa {sufijo}",
        nit=f"900100{sufijo}",
        slug=f"empresa-{sufijo}",
        direccion="Calle 10 # 20-30",
        telefono="3001234567",
    )
    rol = Rol.objects.create(empresa=empresa, nombre="Admin", es_admin=True)
    Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol, activa=True)
    return empresa, usuario


class VistaSimuladaConLimiteYFeature(APIView):
    """Vista DRF de apoyo para probar RequiereFeature y el JSON 403 de LimitePlanExcedido."""

    permission_classes = [IsAuthenticated, RequiereFeature("pos")]

    def post(self, request):
        verificar_limite(request.empresa, "productos")
        return Response({"ok": True})


class SuscripcionesDominioTests(TestCase):
    """Pruebas unitarias y de integración de modelos, servicios y comando de gestión."""

    def setUp(self):
        self.empresa, self.usuario = crear_empresa_con_usuario("a")

    def test_migracion_crea_los_cuatro_planes_en_orden(self):
        codigos = list(Plan.objects.filter(activo=True).values_list("codigo", flat=True))
        self.assertEqual(codigos, ["gratis", "emprendedor", "negocio", "pro"])

    def test_empresa_nueva_inicia_en_trial_de_negocio_por_14_dias_con_historial(self):
        sub = self.empresa.suscripcion
        self.assertEqual(sub.plan.codigo, "negocio")
        self.assertEqual(sub.estado, Suscripcion.Estado.TRIAL)
        self.assertIsNotNone(sub.vence_en)
        dias = (sub.vence_en - sub.inicia_en).days
        self.assertEqual(dias, 14)

        historial = list(sub.historial.all())
        self.assertEqual(len(historial), 1)
        self.assertIsNone(historial[0].plan_anterior)
        self.assertEqual(historial[0].plan_nuevo.codigo, "negocio")
        self.assertEqual(historial[0].estado_nuevo, Suscripcion.Estado.TRIAL)

        # Idempotencia de crear_suscripcion_inicial
        sub_2 = crear_suscripcion_inicial(self.empresa)
        self.assertEqual(sub.pk, sub_2.pk)
        self.assertEqual(sub.historial.count(), 1)

    def test_comision_por_plan_y_por_canal_marketplace_vs_pos(self):
        monto = Decimal("100000.00")
        esperados_marketplace = {
            "gratis": Decimal("6000.00"),       # 6.00%
            "emprendedor": Decimal("4000.00"),  # 4.00%
            "negocio": Decimal("2500.00"),      # 2.50%
            "pro": Decimal("1000.00"),          # 1.00%
        }
        for codigo_plan, comision_esperada in esperados_marketplace.items():
            with self.subTest(plan=codigo_plan):
                cambiar_plan(self.empresa, codigo_plan, ciclo=Suscripcion.Ciclo.MENSUAL)
                self.empresa.refresh_from_db()
                self.assertEqual(
                    calcular_comision(self.empresa, monto, CanalVenta.MARKETPLACE),
                    comision_esperada,
                )
                # En canal POS la comisión es siempre 0.00 sin importar el plan
                self.assertEqual(
                    calcular_comision(self.empresa, monto, CanalVenta.POS),
                    Decimal("0.00"),
                )

        # Redondeo ROUND_HALF_UP a 2 decimales y rechazo de float
        cambiar_plan(self.empresa, "negocio")
        self.assertEqual(
            calcular_comision(self.empresa, Decimal("333.33"), CanalVenta.MARKETPLACE),
            Decimal("8.33"),
        )
        with self.assertRaises(TypeError):
            calcular_comision(self.empresa, 100000.0, CanalVenta.MARKETPLACE)

    def test_limites_y_null_ilimitado_y_formato_json_403(self):
        # En plan 'negocio' (TRIAL inicial), productos es None (ilimitado) y usuarios es 5
        sub = self.empresa.suscripcion
        self.assertTrue(sub.dentro_del_limite("productos", 999999))
        self.assertTrue(sub.dentro_del_limite("usuarios", 5))
        self.assertFalse(sub.dentro_del_limite("usuarios", 6))

        # Cambiar a 'gratis' (límite: 20 productos, 1 usuario) y crear 20 productos activos
        cambiar_plan(self.empresa, "gratis")
        for i in range(20):
            Producto.objects.create(
                empresa=self.empresa,
                codigo=f"P-{i}",
                nombre=f"Producto {i}",
                precio=Decimal("1000.00"),
                stock=5,
                activo=True,
            )
        self.assertEqual(uso_actual(self.empresa)["productos"], 20)

        # Intentar verificar límite para 1 producto adicional lanza LimitePlanExcedido sugiriendo 'emprendedor'
        with self.assertRaises(LimitePlanExcedido) as ctx:
            verificar_limite(self.empresa, "productos")
        exc = ctx.exception
        self.assertEqual(exc.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(exc.recurso, "productos")
        self.assertEqual(exc.limite, 20)
        self.assertEqual(exc.plan_actual, "gratis")
        self.assertEqual(exc.plan_sugerido, "emprendedor")

        # Verificar que una vista DRF devuelve HTTP 403 con el JSON estándar exacto
        cambiar_plan(self.empresa, "emprendedor")  # tiene feature 'pos' y límite 200
        Producto.objects.filter(empresa=self.empresa).delete()
        for i in range(200):
            Producto(
                empresa=self.empresa,
                codigo=f"E-{i}",
                nombre=f"Prod {i}",
                precio=Decimal("1000.00"),
                stock=1,
                activo=True,
            )
        Producto.objects.bulk_create(
            [
                Producto(
                    empresa=self.empresa,
                    codigo=f"E-{i}",
                    nombre=f"Prod {i}",
                    precio=Decimal("1000.00"),
                    stock=1,
                    activo=True,
                )
                for i in range(200)
            ]
        )
        factory = APIRequestFactory()
        request = factory.post("/fake-pos/")
        request.user = self.usuario
        request.empresa = self.empresa
        respuesta = VistaSimuladaConLimiteYFeature.as_view()(request)
        self.assertEqual(respuesta.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            respuesta.data,
            {
                "code": "plan_limit_reached",
                "recurso": "productos",
                "limite": 200,
                "plan_actual": "emprendedor",
                "plan_sugerido": "negocio",
            },
        )

    def test_downgrade_se_bloquea_cuando_uso_actual_excede_limite_destino(self):
        # La empresa está en 'negocio' (productos ilimitados) y crea 25 productos
        Producto.objects.bulk_create(
            [
                Producto(
                    empresa=self.empresa,
                    codigo=f"DG-{i}",
                    nombre=f"Prod {i}",
                    precio=Decimal("5000.00"),
                    stock=2,
                    activo=True,
                )
                for i in range(25)
            ]
        )
        historial_antes = self.empresa.suscripcion.historial.count()

        # Intentar bajar a 'gratis' (máximo 20 productos) debe fallar con mensaje claro
        with self.assertRaises(DowngradeNoPermitido) as ctx:
            cambiar_plan(self.empresa, "gratis")
        self.assertIn("productos", str(ctx.exception))
        self.assertEqual(ctx.exception.excesos["productos"]["exceso"], 5)

        # El plan sigue siendo 'negocio' y no se creó historial falso
        self.empresa.suscripcion.refresh_from_db()
        self.assertEqual(self.empresa.suscripcion.plan.codigo, "negocio")
        self.assertEqual(self.empresa.suscripcion.historial.count(), historial_antes)

    def test_beneficio_fundador_para_primeras_50_empresas_con_plan_pago(self):
        sub = cambiar_plan(self.empresa, "emprendedor", ciclo=Suscripcion.Ciclo.ANUAL)
        self.assertTrue(sub.es_fundador)
        self.assertEqual(sub.descuento_porcentaje, Decimal("50.00"))
        self.assertEqual((sub.vence_en - sub.inicia_en).days, 365)

        # Aunque luego baje a gratis, conserva su condición de fundador de por vida
        sub = cambiar_plan(self.empresa, "gratis")
        self.assertTrue(sub.es_fundador)
        self.assertEqual(sub.descuento_porcentaje, Decimal("50.00"))

        # Si ya existen 50 fundadores, la empresa 51 no recibe el descuento fundador
        for idx in range(2, CUPOS_FUNDADOR + 1):
            emp_i, _ = crear_empresa_con_usuario(f"fund-{idx}")
            Suscripcion.objects.filter(empresa=emp_i).update(
                es_fundador=True, descuento_porcentaje=Decimal("50.00")
            )
        self.assertEqual(Suscripcion.objects.filter(es_fundador=True).count(), CUPOS_FUNDADOR)

        emp_51, _ = crear_empresa_con_usuario("fund-51")
        sub_51 = cambiar_plan(emp_51, "pro", ciclo=Suscripcion.Ciclo.MENSUAL)
        self.assertFalse(sub_51.es_fundador)
        self.assertEqual(sub_51.descuento_porcentaje, Decimal("0.00"))

    def test_trial_vencido_pasa_a_gratis_y_comando_es_idempotente(self):
        sub = self.empresa.suscripcion
        Suscripcion.objects.filter(pk=sub.pk).update(
            vence_en=timezone.now() - timedelta(minutes=10)
        )

        salida_1 = StringIO()
        call_command("verificar_suscripciones", stdout=salida_1)
        self.assertIn("Suscripciones procesadas: 1", salida_1.getvalue())
        self.assertIn("Trials vencidos: 1", salida_1.getvalue())

        sub.refresh_from_db()
        self.assertEqual(sub.plan.codigo, "gratis")
        self.assertEqual(sub.estado, Suscripcion.Estado.ACTIVA)
        self.assertIsNone(sub.vence_en)
        self.assertEqual(sub.historial.count(), 2)

        # Segunda ejecución del comando es idempotente: no vuelve a procesar ni agrega historial
        salida_2 = StringIO()
        call_command("verificar_suscripciones", stdout=salida_2)
        self.assertIn("Suscripciones procesadas: 0", salida_2.getvalue())
        self.assertEqual(sub.historial.count(), 2)


@override_settings(**LLAVES_PRUEBA)
class SuscripcionesAPITests(TestCase):
    """Pruebas de endpoints DRF y aislamiento multi-tenant entre Empresa A y Empresa B."""

    def setUp(self):
        self.client_api = APIClient()
        self.empresa_a, self.usuario_a = crear_empresa_con_usuario("api-a")
        self.empresa_b, self.usuario_b = crear_empresa_con_usuario("api-b")

    def test_endpoint_planes_es_publico_y_ordenado(self):
        respuesta = self.client_api.get(reverse("api_planes_lista"))
        self.assertEqual(respuesta.status_code, status.HTTP_200_OK)
        codigos = [p["codigo"] for p in respuesta.json()]
        self.assertEqual(codigos, ["gratis", "emprendedor", "negocio", "pro"])

    def test_endpoints_suscripcion_exigen_autenticacion(self):
        self.assertIn(
            self.client_api.get(reverse("api_suscripcion_detalle")).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        self.assertIn(
            self.client_api.post(
                reverse("api_suscripcion_cambiar_plan"),
                {"plan": "pro", "ciclo": "MENSUAL"},
                format="json",
            ).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_aislamiento_multitenant_empresa_a_no_ve_ni_modifica_empresa_b(self):
        # Autenticar como Usuario A
        self.client_api.force_authenticate(user=self.usuario_a)

        # 1. GET /api/suscripcion/ devuelve únicamente la suscripción de Empresa A
        resp_get = self.client_api.get(
            reverse("api_suscripcion_detalle"),
            {"empresa_id": str(self.empresa_b.id)},  # Intento malicioso de pasar empresa_id ajeno
        )
        self.assertEqual(resp_get.status_code, status.HTTP_200_OK)
        datos = resp_get.json()
        self.assertEqual(datos["empresa_id"], str(self.empresa_a.id))
        self.assertNotEqual(datos["empresa_id"], str(self.empresa_b.id))
        self.assertEqual(datos["dias_restantes"], 14)

        # 2. POST /api/suscripcion/cambiar-plan/ intentando inyectar empresa_id de Empresa B
        resp_post = self.client_api.post(
            reverse("api_suscripcion_cambiar_plan"),
            {
                "empresa_id": str(self.empresa_b.id),
                "plan": "pro",
                "ciclo": "ANUAL",
            },
            format="json",
        )
        # Plan pago: responde con el enlace de pago y no cambia nada hasta que Wompi confirme
        self.assertEqual(resp_post.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp_post.json()["code"], "pago_requerido")
        cobro = CobroSuscripcion.objects.get()
        self.assertEqual(cobro.empresa, self.empresa_a)  # el empresa_id inyectado se ignora
        self.empresa_a.suscripcion.refresh_from_db()
        self.assertEqual(self.empresa_a.suscripcion.estado, Suscripcion.Estado.TRIAL)
        aprobar_cobro(cobro)

        # Empresa A cambió a 'pro', mientras que Empresa B sigue intacta en su TRIAL de 'negocio'
        self.empresa_a.suscripcion.refresh_from_db()
        self.empresa_b.suscripcion.refresh_from_db()
        self.assertEqual(self.empresa_a.suscripcion.plan.codigo, "pro")
        self.assertEqual(self.empresa_a.suscripcion.ciclo, Suscripcion.Ciclo.ANUAL)
        self.assertEqual(self.empresa_b.suscripcion.plan.codigo, "negocio")
        self.assertEqual(self.empresa_b.suscripcion.estado, Suscripcion.Estado.TRIAL)
        self.assertEqual(self.empresa_b.suscripcion.historial.count(), 1)


    def test_vista_panel_web_suscripcion_muestra_y_cambia_plan(self):
        self.client.force_login(self.usuario_a)
        resp_get = self.client.get(reverse("suscripcion_panel"))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Plan y suscripción")
        self.assertContains(resp_get, "Emprendedor")
        self.assertContains(resp_get, "Pro")

        resp_post = self.client.post(reverse("suscripcion_panel"), {"plan": "pro", "ciclo": "ANUAL"})
        self.assertTrue(resp_post.url.startswith("https://checkout.wompi.co/p/"))
        aprobar_cobro(CobroSuscripcion.objects.get())
        self.empresa_a.suscripcion.refresh_from_db()
        self.assertEqual(self.empresa_a.suscripcion.plan.codigo, "pro")
        self.assertEqual(self.empresa_a.suscripcion.ciclo, Suscripcion.Ciclo.ANUAL)
        self.assertTrue(self.empresa_a.suscripcion.es_fundador)


    @override_settings(DEBUG=True)
    def test_documentacion_openapi_y_swagger_disponibles(self):
        resp_schema = self.client_api.get(reverse("api_schema"))
        self.assertEqual(resp_schema.status_code, status.HTTP_200_OK)
        self.assertIn("/api/planes/", resp_schema.content.decode("utf-8"))

        resp_docs = self.client_api.get(reverse("api_docs"))
        self.assertEqual(resp_docs.status_code, status.HTTP_200_OK)
        self.assertContains(resp_docs, "SwaggerUIBundle")

    def test_cambiar_plan_api_downgrade_a_gratis_y_plan_invalido(self):
        from core.models import Categoria, Producto

        self.client_api.force_authenticate(user=self.usuario_a)
        cambiar_plan(self.empresa_a, "emprendedor")
        cat = Categoria.objects.create(empresa=self.empresa_a, nombre="General")
        for i in range(21):
            Producto.objects.create(empresa=self.empresa_a, categoria=cat, codigo=f"P{i}", nombre=f"P{i}", precio=1000)

        # Downgrade a gratis con 21 productos (>20) -> 400 downgrade_not_allowed
        resp_down = self.client_api.post(
            reverse("api_suscripcion_cambiar_plan"),
            {"plan": "gratis", "ciclo": "MENSUAL"},
            format="json",
        )
        self.assertEqual(resp_down.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_down.data["code"], "downgrade_not_allowed")

        # Plan inexistente -> 400 invalid_plan_change
        resp_inv = self.client_api.post(
            reverse("api_suscripcion_cambiar_plan"),
            {"plan": "no_existe", "ciclo": "MENSUAL"},
            format="json",
        )
        self.assertEqual(resp_inv.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp_inv.data["code"], "invalid_plan_change")


    def test_limites_y_features_de_suscripcion_aplicados_en_panel_core(self):
        from core.models import Cliente, Factura
        from core.services import crear_factura

        self.client.force_login(self.usuario_a)

        # 1. En plan 'gratis' (1 usuario, 20 productos, sin POS), POS y MiembroCreateView bloquean y llevan a /panel/suscripcion/
        cambiar_plan(self.empresa_a, "gratis")
        resp_pos = self.client.get(reverse("pos"))
        self.assertRedirects(resp_pos, reverse("suscripcion_panel"))

        resp_miembro = self.client.get(reverse("equipo_miembro_crear"))
        self.assertRedirects(resp_miembro, reverse("suscripcion_panel"))

        # Crear 20 productos para alcanzar el límite de 'gratis' -> el producto #21 redirige a suscripcion_panel
        Producto.objects.bulk_create(
            [
                Producto(
                    empresa=self.empresa_a,
                    codigo=f"LIM-{i}",
                    nombre=f"Prod {i}",
                    precio=Decimal("1000.00"),
                    stock=5,
                    activo=True,
                )
                for i in range(20)
            ]
        )
        resp_prod = self.client.get(reverse("productos_crear"))
        self.assertRedirects(resp_prod, reverse("suscripcion_panel"))

        # 2. Exportación a Excel (.xlsx) exige feature 'exportacion' (solo plan Pro)
        resp_excel_bloqueado = self.client.get(reverse("erp_reportes_excel"))
        self.assertRedirects(resp_excel_bloqueado, reverse("suscripcion_panel"))

        cambiar_plan(self.empresa_a, "pro")
        resp_excel_ok = self.client.get(reverse("erp_reportes_excel"))
        self.assertEqual(resp_excel_ok.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resp_excel_ok["Content-Type"],
        )
        self.assertTrue(resp_excel_ok.content.startswith(b"PK"))

        # 3. Descarga de Factura en PDF funciona correctamente
        cliente = Cliente.objects.create(
            empresa=self.empresa_a, tipo_documento="CC", numero_documento="123456", nombre="Cliente PDF"
        )
        prod = Producto.objects.filter(empresa=self.empresa_a).first()
        factura = crear_factura(
            empresa=self.empresa_a,
            usuario=self.usuario_a,
            cliente=cliente,
            items=[{"producto": prod, "cantidad": 2}],
        )
        resp_pdf = self.client.get(reverse("facturas_pdf", args=[factura.pk]))
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf["Content-Type"], "application/pdf")
        self.assertTrue(resp_pdf.content.startswith(b"%PDF-"))
