"""Saludo de bienvenida después de iniciar sesión."""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .bienvenida import nombre_para_saludo
from .tests_compra import crear_usuario


class NombreParaSaludoTests(SimpleTestCase):
    def usuario(self, first_name="", username="", email=""):
        return SimpleNamespace(first_name=first_name, username=username, email=email)

    def test_usa_el_nombre_de_pila(self):
        self.assertEqual(nombre_para_saludo(self.usuario("ana maría", email="a@b.co")), "Ana")

    def test_sin_nombre_usa_el_usuario(self):
        self.assertEqual(nombre_para_saludo(self.usuario(username="daniel")), "Daniel")

    def test_sin_nombre_ni_usuario_usa_el_correo(self):
        self.assertEqual(nombre_para_saludo(self.usuario(username="x@y.co", email="velascod768@x.com")), "Velascod")


class BienvenidaTrasLoginTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario(nombre="Ana")

    def test_se_muestra_una_sola_vez_despues_del_login(self):
        respuesta = self.client.post(
            reverse("login"), {"username": self.usuario.email, "password": "ClaveSegura#2026"}, follow=True
        )
        self.assertContains(respuesta, 'id="bienvenida"')
        self.assertContains(respuesta, 'data-nombre="Ana"')
        siguiente = self.client.get(reverse("marketplace"))
        self.assertNotContains(siguiente, 'id="bienvenida"')

    def test_no_aparece_sin_iniciar_sesion(self):
        self.assertNotContains(self.client.get(reverse("marketplace")), 'id="bienvenida"')

    def test_el_nombre_se_escapa(self):
        self.usuario.first_name = '<script>x</script>'
        self.usuario.save()
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse("marketplace"))
        self.assertNotContains(respuesta, "<script>x</script>")
