"""Límite de peticiones: IP real del cliente (QA-01) y reglas que apuntan a rutas reales (QA-02)."""
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from .ratelimit import REGLAS_POR_DEFECTO, obtener_ip_cliente


class IpClienteTests(SimpleTestCase):
    def peticion(self, xff=None, remota="10.0.0.5"):
        extra = {"REMOTE_ADDR": remota}
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        return RequestFactory().get("/", **extra)

    @override_settings(RATELIMIT_PROXIES_DE_CONFIANZA=0)
    def test_sin_proxy_ignora_el_encabezado_que_escribe_el_cliente(self):
        self.assertEqual(obtener_ip_cliente(self.peticion("1.2.3.4")), "10.0.0.5")
        self.assertEqual(obtener_ip_cliente(self.peticion()), "10.0.0.5")

    @override_settings(RATELIMIT_PROXIES_DE_CONFIANZA=1)
    def test_detras_de_nginx_usa_la_ip_que_agrego_el_proxy(self):
        # El cliente inventa "1.2.3.4"; nginx agrega al final la IP real que vio: 190.24.5.6
        self.assertEqual(obtener_ip_cliente(self.peticion("1.2.3.4, 190.24.5.6", "172.18.0.4")), "190.24.5.6")
        self.assertEqual(obtener_ip_cliente(self.peticion("190.24.5.6", "172.18.0.4")), "190.24.5.6")

    @override_settings(RATELIMIT_PROXIES_DE_CONFIANZA=2)
    def test_con_dos_proxies_cuenta_desde_la_derecha(self):
        self.assertEqual(obtener_ip_cliente(self.peticion("1.1.1.1, 190.24.5.6, 10.1.1.1")), "190.24.5.6")

    @override_settings(RATELIMIT_PROXIES_DE_CONFIANZA=2)
    def test_cadena_mas_corta_que_los_proxies_usa_remote_addr(self):
        self.assertEqual(obtener_ip_cliente(self.peticion("190.24.5.6")), "10.0.0.5")


class ReglasTests(SimpleTestCase):
    def test_cada_regla_apunta_a_una_ruta_que_existe(self):
        for prefijo, _, _, _, grupo in REGLAS_POR_DEFECTO:
            with self.subTest(grupo=grupo):
                try:
                    resolve(prefijo)
                except (Resolver404, Http404):
                    # Un prefijo puede cubrir rutas con parámetros (p. ej. /webhooks/wompi/<uuid>/)
                    from django.urls import get_resolver
                    rutas = [str(p.pattern) for p in get_resolver().url_patterns]
                    self.assertTrue(any(prefijo.strip("/").split("/")[0] in r for r in rutas),
                                    f"La regla «{grupo}» apunta a {prefijo}, que no existe")


class IpAuditoriaTests(SimpleTestCase):
    @override_settings(RATELIMIT_PROXIES_DE_CONFIANZA=0)
    def test_la_bitacora_no_guarda_una_ip_inventada(self):
        from plataforma.auditoria import _obtener_ip

        peticion = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="6.6.6.6")
        self.assertEqual(_obtener_ip(peticion), "10.0.0.5")
        self.assertIsNone(_obtener_ip(None))
