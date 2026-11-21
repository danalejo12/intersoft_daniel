"""Sección Idiomas: cambio de idioma de toda la interfaz entre español e inglés."""
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import translation

from .templatetags.idiomas import traducir


class TraducirFiltroTests(SimpleTestCase):
    def test_traduce_textos_del_catalogo(self):
        with translation.override("en"):
            self.assertEqual(traducir("Pagada"), "Paid")

    def test_deja_intactos_textos_sin_traduccion_y_valores_no_texto(self):
        with translation.override("en"):
            self.assertEqual(traducir("Mi rol personalizado"), "Mi rol personalizado")
            self.assertEqual(traducir(42), 42)
            self.assertEqual(traducir(""), "")


class SeccionIdiomasTests(TestCase):
    def test_lista_los_idiomas_disponibles_en_espanol_por_defecto(self):
        respuesta = self.client.get(reverse("idiomas"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Idiomas")
        self.assertContains(respuesta, 'value="en"')
        self.assertContains(respuesta, 'value="es-co"')
        self.assertContains(respuesta, '<html lang="es-co">')

    def test_elegir_ingles_traduce_el_software_y_se_recuerda(self):
        respuesta = self.client.post(
            reverse("set_language"), {"language": "en", "next": reverse("marketplace")}, follow=True
        )
        self.assertEqual(self.client.cookies[settings.LANGUAGE_COOKIE_NAME].value, "en")
        self.assertContains(respuesta, '<html lang="en">')
        self.assertContains(respuesta, "Sell on Intersoft")
        self.assertNotContains(respuesta, "Vende en Intersoft")
        self.assertContains(self.client.get(reverse("login")), "Sign in")

    def test_volver_a_espanol(self):
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        self.client.post(reverse("set_language"), {"language": "es-co", "next": "/"})
        self.assertContains(self.client.get(reverse("marketplace")), "Vende en Intersoft")

    def test_destino_externo_se_ignora(self):
        respuesta = self.client.get(reverse("idiomas"), {"next": "https://malicioso.example/"})
        self.assertNotContains(respuesta, 'value="https://malicioso.example/"')
        self.assertContains(respuesta, f'name="next" value="{reverse("idiomas")}"')

    def test_catalogo_javascript_en_ingles(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "en"
        respuesta = self.client.get(reverse("javascript-catalog"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Confirm sale")
