"""Pruebas automatizadas del módulo soporte (errores, reportes, comentarios, NPS e ideas)."""
from datetime import timedelta
from unittest import mock

from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Empresa, Membresia, Rol, Usuario
from plataforma.models import RolPlataforma

from .context_processors import usuario_puede_responder_nps
from .errores import registrar_excepcion
from .models import ComentarioWidget, EncuestaNPS, ErrorRegistrado, Idea, ReporteProblema, VotoIdea


class SoporteErroresTests(TestCase):
    """Pruebas de captura de errores 500 por huella, reapertura, sin secretos y sin fallo secundario."""

    def setUp(self):
        self.factory = RequestFactory()
        self.usuario = Usuario.objects.create_user(username="err@test.co", email="err@test.co", password="x")

    def _lanzar_en_misma_linea(self, request):
        api_secret = "SECRETO_SUPER_PRIVADO_1234"  # noqa: F841 - verificado por FiltroSecretosPago
        llave_cifrada = "CLAVE_CIFRADA_NO_FILTRAR_999"  # noqa: F841
        try:
            raise RuntimeError("Fallo controlado en prueba")
        except RuntimeError as exc:
            return registrar_excepcion(request, type(exc), exc, exc.__traceback__)

    @override_settings(ADMINS=[("Equipo", "admins@intersoft.co")])
    def test_agrupacion_por_huella_reapertura_correo_unico_y_traza_sin_secretos(self):
        mail.outbox.clear()
        req1 = self.factory.post("/panel/algo/", data={"password": "NO_GUARDAR_POST_BODY"})
        req1.user = self.usuario

        err1 = self._lanzar_en_misma_linea(req1)
        self.assertIsNotNone(err1)
        self.assertEqual(err1.contador, 1)
        self.assertEqual(err1.estado, ErrorRegistrado.Estado.NUEVO)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("admins@intersoft.co", mail.outbox[0].to)

        # La traza NO contiene secretos ni el cuerpo del POST
        self.assertNotIn("SECRETO_SUPER_PRIVADO_1234", err1.traza)
        self.assertNotIn("CLAVE_CIFRADA_NO_FILTRAR_999", err1.traza)
        self.assertNotIn("NO_GUARDAR_POST_BODY", err1.traza)

        # Segunda ocurrencia de la misma huella -> contador=2, NO envía otro correo a ADMINS
        err2 = self._lanzar_en_misma_linea(req1)
        self.assertEqual(err1.pk, err2.pk)
        self.assertEqual(err2.contador, 2)
        self.assertEqual(len(mail.outbox), 1)

        # Si se marca resuelto y vuelve a ocurrir -> se reabre a 'nuevo'
        err2.estado = ErrorRegistrado.Estado.RESUELTO
        err2.save(update_fields=["estado"])
        err3 = self._lanzar_en_misma_linea(req1)
        self.assertEqual(err3.contador, 3)
        self.assertEqual(err3.estado, ErrorRegistrado.Estado.NUEVO)

    def test_registro_errores_no_lanza_excepcion_si_falla_bd(self):
        req = self.factory.get("/ruta/")
        with mock.patch("soporte.errores.ErrorRegistrado.objects.select_for_update", side_effect=RuntimeError("DB down")):
            resultado = registrar_excepcion(req, ValueError, ValueError("x"), None)
        self.assertIsNone(resultado)


class SoporteFeedbackNPSIdeasYPermisosTests(TestCase):
    """Pruebas de reportes manuales, widget, límite 90 días NPS, voto único y bandejas de plataforma."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Neg Feedback", nit="930001", slug="neg-feed", activa=True)
        self.usuario = Usuario.objects.create_user(username="neg@test.co", email="neg@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol, activa=True)

        self.otro = Usuario.objects.create_user(username="otro@test.co", email="otro@test.co", password="x")
        self.dev = Usuario.objects.create_user(
            username="dev-soporte@intersoft.co", email="dev-soporte@intersoft.co", password="x", is_staff=True
        )
        RolPlataforma.objects.create(usuario=self.dev, rol=RolPlataforma.Rol.DESARROLLADOR, activo=True)
        self.soporte = Usuario.objects.create_user(
            username="sop-soporte@intersoft.co", email="sop-soporte@intersoft.co", password="x", is_staff=True
        )
        RolPlataforma.objects.create(usuario=self.soporte, rol=RolPlataforma.Rol.SOPORTE, activo=True)

    def test_reporte_problema_y_comentario_widget(self):
        self.client.force_login(self.usuario)
        resp_rep = self.client.post(
            reverse("soporte_reportar_problema"),
            {"url": "/panel/", "descripcion": "No carga el total"},
            HTTP_USER_AGENT="IntersoftTestBrowser/1.0",
        )
        self.assertEqual(resp_rep.status_code, 302)
        reporte = ReporteProblema.objects.get(usuario=self.usuario)
        self.assertEqual(reporte.empresa, self.empresa)
        self.assertEqual(reporte.url, "/panel/")
        self.assertIn("IntersoftTestBrowser", reporte.navegador)

        resp_com = self.client.post(
            reverse("soporte_comentario"),
            {"util": "1", "comentario": "Muy rápido", "pantalla": "/panel/pos/"},
        )
        self.assertEqual(resp_com.status_code, 302)
        com = ComentarioWidget.objects.get(usuario=self.usuario)
        self.assertTrue(com.util)
        self.assertEqual(com.pantalla, "/panel/pos/")

    def test_limite_nps_una_vez_cada_90_dias(self):
        self.client.force_login(self.usuario)
        self.assertTrue(usuario_puede_responder_nps(self.usuario))

        resp1 = self.client.post(
            reverse("soporte_nps"),
            {"puntaje": "10", "comentario": "Excelente", "pantalla": "/panel/"},
        )
        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(EncuestaNPS.objects.filter(usuario=self.usuario).count(), 1)
        self.assertFalse(usuario_puede_responder_nps(self.usuario))

        # Segundo intento inmediato debe ser rechazado (400) sin crear otro registro
        resp2 = self.client.post(
            reverse("soporte_nps"),
            {"puntaje": "2", "pantalla": "/panel/"},
        )
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(EncuestaNPS.objects.filter(usuario=self.usuario).count(), 1)

        # Si han pasado 91 días, vuelve a habilitarse
        EncuestaNPS.objects.filter(usuario=self.usuario).update(
            creado_en=timezone.now() - timedelta(days=91)
        )
        self.assertTrue(usuario_puede_responder_nps(self.usuario))

    def test_ideas_voto_unico_y_bandejas_plataforma_con_permisos(self):
        self.client.force_login(self.usuario)
        self.client.post(
            reverse("soporte_ideas"),
            {"titulo": "Facturación rápida", "descripcion": "Atajo de teclado"},
        )
        idea = Idea.objects.get(titulo="Facturación rápida")
        self.assertEqual(VotoIdea.objects.filter(idea=idea).count(), 1)

        # Otro usuario vota dos veces -> sigue contando 1 voto suyo (total 2)
        self.client.force_login(self.otro)
        self.client.post(reverse("soporte_votar_idea", args=[idea.pk]))
        self.client.post(reverse("soporte_votar_idea", args=[idea.pk]))
        self.assertEqual(VotoIdea.objects.filter(idea=idea, usuario=self.otro).count(), 1)
        self.assertEqual(VotoIdea.objects.filter(idea=idea).count(), 2)

        # Usuario normal recibe 403 en bandejas de plataforma
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("plataforma_errores")).status_code, 403)
        self.assertEqual(self.client.get(reverse("plataforma_comentarios")).status_code, 403)
        self.assertEqual(self.client.get(reverse("plataforma_ideas")).status_code, 403)

        # Desarrollador accede a errores e ideas, pero 403 en comentarios
        self.client.force_login(self.dev)
        s = self.client.session
        s["plataforma_totp_verificado"] = str(self.dev.pk)
        s.save()
        self.assertEqual(self.client.get(reverse("plataforma_errores")).status_code, 200)
        self.assertEqual(self.client.get(reverse("plataforma_comentarios")).status_code, 403)
        resp_ideas = self.client.post(
            reverse("plataforma_ideas"),
            {"idea_id": str(idea.pk), "estado": Idea.Estado.PLANEADA},
            follow=True,
        )
        self.assertEqual(resp_ideas.status_code, 200)
        idea.refresh_from_db()
        self.assertEqual(idea.estado, Idea.Estado.PLANEADA)

        # Soporte accede a comentarios y ve el NPS calculado
        EncuestaNPS.objects.create(usuario=self.usuario, puntaje=10)
        EncuestaNPS.objects.create(usuario=self.otro, puntaje=5)
        self.client.force_login(self.soporte)
        s2 = self.client.session
        s2["plataforma_totp_verificado"] = str(self.soporte.pk)
        s2.save()
        resp_com = self.client.get(reverse("plataforma_comentarios"))
        self.assertEqual(resp_com.status_code, 200)
        self.assertEqual(resp_com.context["nps_actual"], 0.0)  # 50% promotores - 50% detractores = 0.0

        # Filtros de comentarios
        self.assertEqual(self.client.get(f"{reverse('plataforma_comentarios')}?util=1").status_code, 200)
        self.assertEqual(self.client.get(f"{reverse('plataforma_comentarios')}?util=0&pantalla=/panel/").status_code, 200)

        # Detalle y cambio de estado de un error registrado (dev)
        from .models import ErrorRegistrado

        err = ErrorRegistrado.objects.create(
            huella="h-test-views",
            tipo_excepcion="ValueError",
            mensaje="Fallo controlado",
            archivo="core/views.py",
            linea=10,
            url="/panel/",
            metodo="GET",
        )
        self.client.force_login(self.dev)
        s3 = self.client.session
        s3["plataforma_totp_verificado"] = str(self.dev.pk)
        s3.save()
        self.assertEqual(self.client.get(reverse("plataforma_error_detalle", args=[err.pk])).status_code, 200)
        resp_err_upd = self.client.post(
            reverse("plataforma_error_detalle", args=[err.pk]),
            {"estado": ErrorRegistrado.Estado.RESUELTO, "notas_internas": "Corregido en vista."},
            follow=True,
        )
        self.assertEqual(resp_err_upd.status_code, 200)
        err.refresh_from_db()
        self.assertEqual(err.estado, ErrorRegistrado.Estado.RESUELTO)

        # Reportar problema desde el panel (GET y POST)
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get(reverse("soporte_reportar_problema")).status_code, 200)
        resp_rep = self.client.post(
            reverse("soporte_reportar_problema"),
            {"descripcion": "No cargó el filtro rápido.", "url_origen": "/panel/productos/"},
            follow=True,
        )
        self.assertEqual(resp_rep.status_code, 200)
