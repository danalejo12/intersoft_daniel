"""Pruebas automatizadas del módulo PQRS."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Empresa, Membresia, Pedido, Permiso, Rol, Usuario
from core.permisos import sincronizar_catalogo_permisos
from core.tareas import ejecutar_pendientes
from plataforma.models import RolPlataforma

from .dias_habiles import FESTIVOS_COLOMBIA, semaforo_pqrs, sumar_dias_habiles
from .models import PQRS, generar_radicado, validar_archivo_pqrs
from .services import (
    agregar_mensaje_pqrs,
    radicar_pqrs,
)


class PqrsRadicadoConcurrenciaTests(TransactionTestCase):
    """Verifica que generar_radicado sea seguro bajo concurrencia."""

    def test_radicado_unico_con_concurrencia(self):
        def _crear_en_hilo(_idx):
            try:
                return generar_radicado(anio=2026)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=6) as pool:
            radicados = list(pool.map(_crear_en_hilo, range(12)))

        self.assertEqual(len(radicados), 12)
        self.assertEqual(len(set(radicados)), 12)
        for r in radicados:
            self.assertTrue(r.startswith("PQRS-2026-"))


class PqrsDiasHabilesYAdjuntosTests(TestCase):
    """Pruebas de cálculo de días hábiles en Colombia, semáforo y validación de adjuntos."""

    def test_sumar_dias_habiles_salta_fines_de_semana_y_festivos(self):
        # Viernes 2026-01-09 -> lunes 2026-01-12 es festivo (Reyes Magos) -> 1 día hábil = martes 2026-01-13
        viernes = timezone.make_aware(datetime(2026, 1, 9, 10, 0), timezone.get_current_timezone())
        resultado = sumar_dias_habiles(viernes, 1, festivos=FESTIVOS_COLOMBIA)
        self.assertEqual(resultado.date().isoformat(), "2026-01-13")

    def test_semaforo_verde_amarillo_y_rojo(self):
        autor = Usuario.objects.create_user(username="u@test.co", email="u@test.co", password="x")
        emp = Empresa.objects.create(nombre="Neg Sem", nit="910001", slug="neg-sem", activa=True)
        ahora = timezone.make_aware(datetime(2026, 2, 2, 10, 0), timezone.get_current_timezone())

        p_verde = PQRS.objects.create(
            autor=autor,
            empresa=emp,
            tipo=PQRS.Tipo.PETICION,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Verde",
            descripcion="Desc",
            fecha_limite=sumar_dias_habiles(ahora, 5),
        )
        p_amarillo = PQRS.objects.create(
            autor=autor,
            empresa=emp,
            tipo=PQRS.Tipo.PETICION,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Amarillo",
            descripcion="Desc",
            fecha_limite=sumar_dias_habiles(ahora, 2),
        )
        p_rojo = PQRS.objects.create(
            autor=autor,
            empresa=emp,
            tipo=PQRS.Tipo.PETICION,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Rojo",
            descripcion="Desc",
            fecha_limite=ahora - timedelta(hours=1),
        )
        self.assertEqual(semaforo_pqrs(p_verde, ahora=ahora), "verde")
        self.assertEqual(semaforo_pqrs(p_amarillo, ahora=ahora), "amarillo")
        self.assertEqual(semaforo_pqrs(p_rojo, ahora=ahora), "rojo")

    def test_validacion_adjuntos_extension_y_tamano(self):
        ejecutable = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            validar_archivo_pqrs(ejecutable)

        muy_grande = SimpleUploadedFile("grande.pdf", b"0" * (5 * 1024 * 1024 + 1), content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validar_archivo_pqrs(muy_grande)

        valido = SimpleUploadedFile("soporte.pdf", b"%PDF-1.4", content_type="application/pdf")
        validar_archivo_pqrs(valido)


class PqrsFlujosPermisosAislamientoYEscalamientoTests(TestCase):
    """Pruebas de vistas, permisos, aislamiento multi-tenant, notas internas, correos y escalamiento."""

    def setUp(self):
        sincronizar_catalogo_permisos()
        self.emp_a = Empresa.objects.create(
            nombre="Negocio A", nit="911001", slug="negocio-a", email="a@negocio.co", activa=True
        )
        self.emp_b = Empresa.objects.create(
            nombre="Negocio B", nit="911002", slug="negocio-b", email="b@negocio.co", activa=True
        )

        self.dueno_a = Usuario.objects.create_user(username="dueno_a@test.co", email="dueno_a@test.co", password="x")
        rol_admin_a = Rol.objects.create(empresa=self.emp_a, nombre="Admin A", es_admin=True)
        Membresia.objects.create(usuario=self.dueno_a, empresa=self.emp_a, rol=rol_admin_a, activa=True)

        self.sin_permiso_a = Usuario.objects.create_user(
            username="bodega_a@test.co", email="bodega_a@test.co", password="x"
        )
        rol_sin_pqrs = Rol.objects.create(empresa=self.emp_a, nombre="Sin PQRS", es_admin=False)
        rol_sin_pqrs.permisos.add(Permiso.objects.get(codigo="inventario.ver"))
        Membresia.objects.create(usuario=self.sin_permiso_a, empresa=self.emp_a, rol=rol_sin_pqrs, activa=True)

        self.dueno_b = Usuario.objects.create_user(username="dueno_b@test.co", email="dueno_b@test.co", password="x")
        rol_admin_b = Rol.objects.create(empresa=self.emp_b, nombre="Admin B", es_admin=True)
        Membresia.objects.create(usuario=self.dueno_b, empresa=self.emp_b, rol=rol_admin_b, activa=True)

        self.comprador_1 = Usuario.objects.create_user(username="comp1@test.co", email="comp1@test.co", password="x")
        self.comprador_2 = Usuario.objects.create_user(username="comp2@test.co", email="comp2@test.co", password="x")

        self.soporte_plataforma = Usuario.objects.create_user(
            username="soporte@intersoft.co", email="soporte@intersoft.co", password="x", is_staff=True
        )
        RolPlataforma.objects.create(usuario=self.soporte_plataforma, rol=RolPlataforma.Rol.SOPORTE, activo=True)

        self.pedido_c1 = Pedido.objects.create(
            empresa=self.emp_a,
            comprador=self.comprador_1,
            numero=101,
            expira_en=timezone.now() + timedelta(minutes=30),
        )

    def test_aislamiento_comprador_y_negocio_y_permiso_panel(self):
        pqrs_c1 = radicar_pqrs(
            autor=self.comprador_1,
            tipo=PQRS.Tipo.RECLAMO,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Producto incompleto",
            descripcion="Faltó un artículo",
            pedido=self.pedido_c1,
        )
        self.assertGreaterEqual(len(mail.outbox), 1)

        # Nota interna no la ve el comprador
        agregar_mensaje_pqrs(pqrs_c1, autor=self.dueno_a, texto="Nota secreta interna", interno=True)
        agregar_mensaje_pqrs(pqrs_c1, autor=self.dueno_a, texto="Respuesta pública", interno=False, nuevo_estado=PQRS.Estado.RESPONDIDA)

        self.client.force_login(self.comprador_1)
        resp_c1 = self.client.get(reverse("pqrs_detalle", args=[pqrs_c1.pk]))
        self.assertEqual(resp_c1.status_code, 200)
        self.assertContains(resp_c1, "Respuesta pública")
        self.assertNotContains(resp_c1, "Nota secreta interna")

        # Otro comprador recibe 404
        self.client.force_login(self.comprador_2)
        self.assertEqual(self.client.get(reverse("pqrs_detalle", args=[pqrs_c1.pk])).status_code, 404)

        # Otro negocio recibe 404 en /panel/pqrs/<pk>/
        self.client.force_login(self.dueno_b)
        self.assertEqual(self.client.get(reverse("panel_pqrs_detalle", args=[pqrs_c1.pk])).status_code, 404)

        # Miembro de Negocio A sin permiso pqrs.gestionar recibe 403
        self.client.force_login(self.sin_permiso_a)
        self.assertEqual(self.client.get(reverse("panel_pqrs_lista")).status_code, 403)

        # Comprador cierra con encuesta 1..5
        self.client.force_login(self.comprador_1)
        resp_enc = self.client.post(
            reverse("pqrs_detalle", args=[pqrs_c1.pk]),
            {"accion": "encuesta", "calificacion": "5", "comentario_satisfaccion": "Excelente"},
            follow=True,
        )
        self.assertEqual(resp_enc.status_code, 200)
        pqrs_c1.refresh_from_db()
        self.assertEqual(pqrs_c1.estado, PQRS.Estado.CERRADA)
        self.assertEqual(pqrs_c1.calificacion, 5)

    def test_escalamiento_flujo_b_y_bandeja_plataforma_escaladas_primero(self):
        # Flujo B vencida -> debe escalarse
        p_vencida = PQRS.objects.create(
            autor=self.comprador_1,
            empresa=self.emp_a,
            tipo=PQRS.Tipo.QUEJA,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Sin respuesta",
            descripcion="Llevo días esperando",
            fecha_limite=timezone.now() - timedelta(days=1),
        )
        # Flujo A vencida -> NO se escala (ya va dirigida a Intersoft)
        p_flujo_a = PQRS.objects.create(
            autor=self.dueno_a,
            empresa=self.emp_a,
            tipo=PQRS.Tipo.PETICION,
            flujo=PQRS.Flujo.NEGOCIO_INTERSOFT,
            asunto="Soporte factura",
            descripcion="Consulta plataforma",
            fecha_limite=timezone.now() - timedelta(days=1),
        )
        # Flujo B vigente -> NO se escala
        p_vigente = PQRS.objects.create(
            autor=self.comprador_2,
            empresa=self.emp_b,
            tipo=PQRS.Tipo.SUGERENCIA,
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            asunto="Vigente",
            descripcion="A tiempo",
            fecha_limite=timezone.now() + timedelta(days=5),
        )

        mail.outbox.clear()
        resultados = ejecutar_pendientes(forzar=True, solo=["escalar_pqrs_vencidas"])
        self.assertEqual(resultados["escalar_pqrs_vencidas"], "ok")

        p_vencida.refresh_from_db()
        p_flujo_a.refresh_from_db()
        p_vigente.refresh_from_db()
        self.assertEqual(p_vencida.estado, PQRS.Estado.ESCALADA)
        self.assertIsNotNone(p_vencida.escalada_en)
        self.assertEqual(p_flujo_a.estado, PQRS.Estado.RADICADA)
        self.assertEqual(p_vigente.estado, PQRS.Estado.RADICADA)
        self.assertGreaterEqual(len(mail.outbox), 1)

        # /plataforma/pqrs/ denegado a comprador (403) y permitido a soporte_plataforma
        self.client.force_login(self.comprador_1)
        self.assertEqual(self.client.get(reverse("plataforma_pqrs")).status_code, 403)

        self.client.force_login(self.soporte_plataforma)
        s = self.client.session
        s["plataforma_totp_verificado"] = str(self.soporte_plataforma.pk)
        s.save()
        resp = self.client.get(reverse("plataforma_pqrs"))
        self.assertEqual(resp.status_code, 200)
        lista = list(resp.context["pqrs_lista"])
        self.assertEqual(lista[0].pk, p_vencida.pk)

    def test_vistas_comprador_panel_y_plataforma_pqrs(self):
        from core.models import Pedido

        pedido = Pedido.objects.create(
            empresa=self.emp_a,
            comprador=self.comprador_1,
            numero=7001,
            nombre="Comprador Uno",
            email=self.comprador_1.email,
            estado=Pedido.Estado.PAGADO,
            expira_en=timezone.now() + timedelta(days=1),
            total=20000,
        )

        # 1. Comprador radica y lista en /pqrs/
        self.client.force_login(self.comprador_1)
        self.assertEqual(self.client.get(reverse("pqrs_mis_list")).status_code, 200)
        self.assertEqual(
            self.client.get(f"{reverse('pqrs_radicar')}?pedido={pedido.pk}").status_code,
            200,
        )
        # Radicación sin empresa ni pedido -> muestra error en formulario
        resp_err = self.client.post(
            reverse("pqrs_radicar"),
            {"tipo": PQRS.Tipo.QUEJA, "asunto": "Sin destino", "descripcion": "Falta negocio"},
        )
        self.assertEqual(resp_err.status_code, 200)
        self.assertContains(resp_err, "Selecciona un negocio")

        resp_rad = self.client.post(
            reverse("pqrs_radicar"),
            {
                "tipo": PQRS.Tipo.RECLAMO,
                "pedido": str(pedido.pk),
                "asunto": "Producto incompleto",
                "descripcion": "Faltó un accesorio en el paquete.",
            },
            follow=True,
        )
        self.assertEqual(resp_rad.status_code, 200)
        pqrs_b = PQRS.objects.get(asunto="Producto incompleto")
        self.assertEqual(pqrs_b.empresa_id, self.emp_a.pk)

        # Comprador envía mensaje en su PQRS
        resp_msg = self.client.post(
            reverse("pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "mensaje", "texto": "Adjunto más detalles del caso."},
            follow=True,
        )
        self.assertEqual(resp_msg.status_code, 200)
        self.assertContains(resp_msg, "Adjunto más detalles")

        # 2. Negocio gestiona en /panel/pqrs/: nota interna + respuesta + cambio de estado
        self.client.force_login(self.dueno_a)
        self.assertEqual(self.client.get(reverse("panel_pqrs_lista")).status_code, 200)
        self.assertEqual(self.client.get(reverse("panel_pqrs_detalle", args=[pqrs_b.pk])).status_code, 200)

        self.client.post(
            reverse("panel_pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "cambiar_estado", "estado": PQRS.Estado.EN_TRAMITE},
        )
        pqrs_b.refresh_from_db()
        self.assertEqual(pqrs_b.estado, PQRS.Estado.EN_TRAMITE)

        # Nota interna (oculta al comprador) + respuesta pública (cambia a RESPONDIDA)
        self.client.post(
            reverse("panel_pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "mensaje", "texto": "Revisando con bodega", "interno": "on"},
        )
        self.client.post(
            reverse("panel_pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "mensaje", "texto": "Ya enviamos el accesorio faltante."},
        )
        pqrs_b.refresh_from_db()
        self.assertEqual(pqrs_b.estado, PQRS.Estado.RESPONDIDA)

        # Negocio radica flujo A hacia Intersoft y responde encuesta al cerrar
        self.assertEqual(self.client.get(reverse("panel_pqrs_nueva")).status_code, 200)
        self.client.post(
            reverse("panel_pqrs_nueva"),
            {
                "tipo": PQRS.Tipo.PETICION,
                "prioridad": PQRS.Prioridad.ALTA,
                "asunto": "Duda con facturación",
                "descripcion": "Necesito apoyo en configuración.",
            },
            follow=True,
        )
        pqrs_a = PQRS.objects.get(asunto="Duda con facturación")
        self.client.post(
            reverse("panel_pqrs_detalle", args=[pqrs_a.pk]),
            {"accion": "encuesta", "calificacion": 5, "comentario_satisfaccion": "Excelente"},
        )
        pqrs_a.refresh_from_db()
        self.assertEqual(pqrs_a.estado, PQRS.Estado.CERRADA)

        # 3. Comprador no ve nota interna, responde encuesta (cierra) y no puede comentar cerrada
        self.client.force_login(self.comprador_1)
        det_comp = self.client.get(reverse("pqrs_detalle", args=[pqrs_b.pk]))
        self.assertNotContains(det_comp, "Revisando con bodega")
        self.assertContains(det_comp, "Ya enviamos el accesorio faltante.")
        self.client.post(
            reverse("pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "encuesta", "calificacion": 4, "comentario_satisfaccion": "Buena solución"},
        )
        pqrs_b.refresh_from_db()
        self.assertEqual(pqrs_b.estado, PQRS.Estado.CERRADA)
        resp_cerrada = self.client.post(
            reverse("pqrs_detalle", args=[pqrs_b.pk]),
            {"accion": "mensaje", "texto": "Intento tras cierre"},
            follow=True,
        )
        self.assertContains(resp_cerrada, "ya está cerrada")

        # 4. Plataforma filtra y gestiona en /plataforma/pqrs/
        self.client.force_login(self.soporte_plataforma)
        s = self.client.session
        s["plataforma_totp_verificado"] = str(self.soporte_plataforma.pk)
        s.save()
        self.assertEqual(
            self.client.get(
                f"{reverse('plataforma_pqrs')}?estado={PQRS.Estado.CERRADA}&flujo={PQRS.Flujo.NEGOCIO_INTERSOFT}"
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse("plataforma_pqrs_detalle", args=[pqrs_a.pk])).status_code, 200)
        self.client.post(
            reverse("plataforma_pqrs_detalle", args=[pqrs_a.pk]),
            {
                "accion": "gestionar",
                "estado": PQRS.Estado.EN_TRAMITE,
                "prioridad": PQRS.Prioridad.URGENTE,
                "asignado_a": str(self.soporte_plataforma.pk),
            },
        )
        self.client.post(
            reverse("plataforma_pqrs_detalle", args=[pqrs_a.pk]),
            {"accion": "mensaje", "texto": "Seguimiento desde consola plataforma."},
        )
        pqrs_a.refresh_from_db()
        self.assertEqual(pqrs_a.estado, PQRS.Estado.RESPONDIDA)
        self.assertEqual(pqrs_a.prioridad, PQRS.Prioridad.URGENTE)

        from .services import agregar_mensaje_pqrs

        agregar_mensaje_pqrs(
            pqrs_a,
            autor=self.soporte_plataforma,
            texto="Cierre definitivo desde soporte.",
            nuevo_estado=PQRS.Estado.CERRADA,
        )
        pqrs_a.refresh_from_db()
        self.assertEqual(pqrs_a.estado, PQRS.Estado.CERRADA)
        self.assertIsNotNone(pqrs_a.cerrada_en)
