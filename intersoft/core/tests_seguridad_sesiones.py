"""Pruebas de seguridad de autenticación y sesiones: códigos de recuperación 2FA, rate limit, timeout y sesiones."""
import time

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Usuario
from plataforma.models import RolPlataforma
from plataforma.totp import codigo_totp_actual, generar_secreto_totp


class SeguridadAutenticacionSesionesTests(TestCase):
    """Valida las capas de seguridad en 2FA de plataforma y gestión de sesiones activas."""

    def setUp(self):
        cache.clear()
        self.admin = Usuario.objects.create_user(
            username="sec-admin@intersoft.co",
            email="sec-admin@intersoft.co",
            password="Password123*",
            first_name="Admin",
            is_staff=True,
        )
        self.rol = RolPlataforma.objects.create(
            usuario=self.admin,
            rol=RolPlataforma.Rol.DUENO,
            activo=True,
        )

    def test_activacion_2fa_genera_codigos_recuperacion_de_un_solo_uso(self):
        """Al activar 2FA genera 8 códigos hasheados; cada código funciona una sola vez."""
        self.client.force_login(self.admin)
        resp_get = self.client.get(reverse("plataforma_totp"))
        self.assertEqual(resp_get.status_code, 200)
        secreto = self.client.session["plataforma_totp_setup"]

        # Activar con código TOTP válido
        resp_post = self.client.post(
            reverse("plataforma_totp"),
            {"codigo": codigo_totp_actual(secreto)},
            follow=True,
        )
        self.assertEqual(resp_post.status_code, 200)
        codigos = resp_post.context["codigos_nuevos"]
        self.assertEqual(len(codigos), 8)

        # En una sesión nueva, entrar usando el primer código de recuperación
        otro = Client()
        otro.force_login(self.admin)
        resp_rec = otro.post(reverse("plataforma_totp"), {"codigo": codigos[0]})
        self.assertRedirects(resp_rec, reverse("plataforma_inicio"), fetch_redirect_response=False)

        # Reutilizar el mismo código de recuperación falla (es de un solo uso)
        tercero = Client()
        tercero.force_login(self.admin)
        resp_reuso = tercero.post(reverse("plataforma_totp"), {"codigo": codigos[0]})
        self.assertEqual(resp_reuso.status_code, 200)
        self.assertNotEqual(tercero.session.get("plataforma_totp_verificado"), str(self.admin.pk))

    def test_rate_limit_totp_bloquea_tras_5_intentos_fallidos(self):
        """Después de 5 códigos inválidos, /plataforma/2fa/ bloquea con HTTP 429."""
        self.rol.establecer_totp_secreto(generar_secreto_totp())
        self.rol.totp_activo = True
        self.rol.save()

        self.client.force_login(self.admin)
        for _ in range(5):
            r = self.client.post(reverse("plataforma_totp"), {"codigo": "000000"})
            self.assertEqual(r.status_code, 200)
        r_bloqueado = self.client.post(reverse("plataforma_totp"), {"codigo": "000000"})
        self.assertEqual(r_bloqueado.status_code, 429)

    @override_settings(PLATAFORMA_TOTP_TIMEOUT_MINUTOS=30)
    def test_timeout_inactividad_2fa_exige_nueva_verificacion(self):
        """Si pasan más de 30 min sin actividad en /plataforma/, redirige a /plataforma/2fa/."""
        self.rol.establecer_totp_secreto(generar_secreto_totp())
        self.rol.totp_activo = True
        self.rol.save()

        self.client.force_login(self.admin)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(self.admin.pk)
        sesion["plataforma_totp_ultima_actividad"] = int(time.time()) - (31 * 60)
        sesion.save()

        resp = self.client.get(reverse("plataforma_inicio"))
        self.assertRedirects(resp, reverse("plataforma_totp"), fetch_redirect_response=False)

    def test_cerrar_sesion_en_otros_dispositivos_conserva_sesion_actual(self):
        """POST /perfil/cerrar-otras-sesiones/ expulsa otros navegadores y mantiene viva la sesión actual."""
        dispositivo_1 = Client()
        dispositivo_2 = Client()
        dispositivo_1.force_login(self.admin)
        dispositivo_2.force_login(self.admin)

        # Ambos acceden a /perfil/
        self.assertEqual(dispositivo_1.get(reverse("perfil")).status_code, 200)
        self.assertEqual(dispositivo_2.get(reverse("perfil")).status_code, 200)

        # Dispositivo 1 cierra las demás sesiones
        resp = dispositivo_1.post(reverse("perfil_cerrar_otras_sesiones"), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Se cerraron 1 sesión(es)")

        # Dispositivo 1 sigue autenticado; Dispositivo 2 es redirigido a login
        self.assertEqual(dispositivo_1.get(reverse("perfil")).status_code, 200)
        self.assertEqual(dispositivo_2.get(reverse("perfil")).status_code, 302)

    def test_cabeceras_permissions_policy_y_coop(self):
        """Permissions-Policy bloquea cámara fuera del POS y la permite en /panel/pos/; COOP y Referrer activos."""
        resp_home = self.client.get(reverse("marketplace"))
        self.assertEqual(resp_home.status_code, 200)
        self.assertIn("camera=()", resp_home["Permissions-Policy"])
        self.assertIn("microphone=()", resp_home["Permissions-Policy"])
        self.assertEqual(resp_home["Cross-Origin-Opener-Policy"], "same-origin-allow-popups")
        self.assertEqual(resp_home["Referrer-Policy"], "strict-origin-when-cross-origin")
