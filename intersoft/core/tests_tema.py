"""Modo día / noche en el panel de negocios y en la consola de plataforma."""
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from core.models import Usuario
from plataforma.models import RolPlataforma

from .tests_compra import crear_negocio, crear_usuario


class TemaPanelYPlataformaTests(TestCase):
    def assertTieneInterruptor(self, respuesta):
        self.assertEqual(respuesta.status_code, 200)
        html = respuesta.content.decode()
        self.assertIn("data-tema-boton", html)
        self.assertIn('role="switch"', html)
        # El tema se aplica en <head>, antes de pintar (sin parpadeo), y el cambio lo maneja tema.js
        self.assertLess(html.index("core/js/tema-init.js"), html.index("core/css/app.css"))
        self.assertIn("core/js/tema.js", html)

    def test_panel_del_negocio_tiene_modo_dia_y_noche(self):
        dueno = crear_usuario("dueno@correo.co")
        crear_negocio("Dulce Hogar", "900", dueno)
        self.client.force_login(dueno)
        self.assertTieneInterruptor(self.client.get(reverse("dashboard")))

    def test_consola_de_plataforma_tiene_modo_dia_y_noche(self):
        dev = Usuario.objects.create_user(username="dev@intersoft.co", email="dev@intersoft.co",
                                          password="x", is_staff=True)
        RolPlataforma.objects.create(usuario=dev, rol=RolPlataforma.Rol.DESARROLLADOR, activo=True)
        self.client.force_login(dev)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(dev.pk)
        sesion.save()
        self.assertTieneInterruptor(self.client.get(reverse("plataforma_inicio")))

    def test_la_hoja_de_estilos_define_la_paleta_de_dia(self):
        with open(finders.find("core/css/app.css"), encoding="utf-8") as archivo:
            css = archivo.read()
        self.assertIn(':root[data-tema="claro"]', css)
        self.assertIn("--capa: 15, 23, 42;", css)
        # Las capas translúcidas ya no son blanco fijo: siguen el tema
        self.assertGreater(css.count("rgba(var(--capa)"), 40)
