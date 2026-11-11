"""Pruebas del Sprint 1 "Cimientos": registros, datos del vendedor, IVA, Wompi, Inicio y límite de intentos."""
import logging
from logging.handlers import RotatingFileHandler
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.log import AdminEmailHandler

from . import reservas
from .models import Empresa, Pedido
from .tests_pedidos import PedidoBase


class RegistrosTests(TestCase):
    def test_pagos_y_reservas_escriben_en_archivo_y_avisan_a_admins(self):
        for nombre in ("core.pagos", "core.reservas"):
            with self.subTest(logger=nombre):
                tipos = {type(h) for h in logging.getLogger(nombre).handlers}
                self.assertIn(RotatingFileHandler, tipos)
                self.assertIn(AdminEmailHandler, tipos)

    @override_settings(ADMINS=["finanzas@intersoft.example"])
    def test_critical_queda_en_el_archivo(self):
        logger = logging.getLogger("core.reservas")
        logger.critical("Prueba de registro: aviso crítico de reembolso")
        archivo = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
        archivo.flush()
        with open(archivo.baseFilename, encoding="utf-8") as registro:
            self.assertIn("Prueba de registro: aviso crítico de reembolso", registro.read())

    def test_sin_admins_no_se_envia_correo(self):
        with override_settings(ADMINS=[]):
            logging.getLogger("core.pagos").critical("Sin destinatarios")
        self.assertEqual(len(mail.outbox), 0)

    def test_construir_mailers_usa_consola_como_respaldo_y_smtp_en_produccion(self):
        from django.core.checks.mail import check_mailers_production_backend
        from intersoft.settings import _construir_mailers

        respaldo = _construir_mailers(host="")
        self.assertEqual(
            respaldo["default"]["BACKEND"],
            "django.core.mail.backends.console.EmailBackend",
        )

        smtp = _construir_mailers(
            host="smtp.intersoft.co",
            port=587,
            username="alertas@intersoft.co",
            password="secreto",
            use_tls=True,
            use_ssl=False,
        )
        self.assertEqual(
            smtp["default"]["BACKEND"],
            "django.core.mail.backends.smtp.EmailBackend",
        )
        self.assertEqual(smtp["default"]["OPTIONS"]["host"], "smtp.intersoft.co")
        self.assertEqual(smtp["default"]["OPTIONS"]["port"], 587)
        with override_settings(MAILERS=smtp):
            self.assertEqual(check_mailers_production_backend(None), [])

    def test_check_deploy_en_configuracion_de_produccion_sin_errores_bloqueantes(self):
        from django.core import checks
        from intersoft.settings import _construir_mailers

        smtp = _construir_mailers(
            host="smtp.intersoft.co",
            port=587,
            username="alertas@intersoft.co",
            password="secreto-smtp-produccion",
            use_tls=True,
        )
        with override_settings(
            DEBUG=False,
            SECRET_KEY="clave-produccion-aleatoria-muy-larga-y-con-alta-entropia-2026-!@#$%^&*()_+",
            ALLOWED_HOSTS=["tienda.intersoft.co"],
            SECURE_SSL_REDIRECT=True,
            SESSION_COOKIE_SECURE=True,
            CSRF_COOKIE_SECURE=True,
            SECURE_HSTS_SECONDS=31536000,
            SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
            SECURE_HSTS_PRELOAD=True,
            MAILERS=smtp,
        ):
            problemas = checks.run_checks(include_deployment_checks=True)
            errores = [p for p in problemas if p.is_serious()]
            self.assertEqual(errores, [])
            self.assertEqual([p.id for p in problemas], [])

    def test_inicializar_monitoreo_es_opcional_y_seguro_sin_sentry_sdk(self):
        import sys
        from intersoft.settings import _inicializar_monitoreo

        # Sin DSN no hace nada
        self.assertFalse(_inicializar_monitoreo(dsn=""))

        # Con DSN pero sin el paquete instalado registra advertencia sin fallar
        with mock.patch.dict(sys.modules, {"sentry_sdk": None}):
            self.assertFalse(_inicializar_monitoreo(dsn="https://key@sentry.example/1"))

        # Con DSN y paquete simulado llama a sentry_sdk.init con send_default_pii=False
        falso_sentry = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"sentry_sdk": falso_sentry}):
            self.assertTrue(
                _inicializar_monitoreo(
                    dsn="https://key@sentry.example/1",
                    environment="staging",
                    traces_sample_rate=0.25,
                )
            )
        falso_sentry.init.assert_called_once_with(
            dsn="https://key@sentry.example/1",
            environment="staging",
            traces_sample_rate=0.25,
            send_default_pii=False,
        )


@override_settings(ADMINS=["finanzas@intersoft.example"])
class AvisoDeReembolsoTests(PedidoBase):
    def test_un_reembolso_real_avisa_por_correo(self):
        reservas.registrar_monto_invalido(self.pedido)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("requiere reembolso", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ["finanzas@intersoft.example"])


class DatosVendedorTests(TestCase):
    """Ley 1480, art. 53: el comprador debe poder identificar y contactar al vendedor."""

    def setUp(self):
        from .tests_compra import crear_negocio, crear_producto, crear_usuario

        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "900123", self.dueno)
        self.producto = crear_producto(self.negocio)

    def quitar_datos(self):
        Empresa.objects.filter(pk=self.negocio.pk).update(direccion="", telefono="")

    def test_registro_exige_direccion_y_telefono(self):
        from .tests_compra import crear_usuario

        self.client.force_login(crear_usuario("nuevo@correo.co"))
        respuesta = self.client.post(reverse("negocio_registrar"), {"nombre": "Nuevo", "nit": "77", "email": "", "telefono": "", "direccion": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("direccion", respuesta.context["form"].errors)
        self.assertIn("telefono", respuesta.context["form"].errors)
        self.assertFalse(Empresa.objects.filter(nit="77").exists())

    def test_registro_rechaza_telefono_invalido(self):
        from .tests_compra import crear_usuario

        self.client.force_login(crear_usuario("nuevo@correo.co"))
        respuesta = self.client.post(reverse("negocio_registrar"), {"nombre": "Nuevo", "nit": "77", "email": "", "telefono": "abc", "direccion": "Calle 2"})
        self.assertIn("telefono", respuesta.context["form"].errors)

    def test_sin_datos_sus_productos_no_se_publican(self):
        self.quitar_datos()
        self.assertNotContains(self.client.get(reverse("marketplace")), "Pan")
        self.assertEqual(self.client.get(reverse("tienda_producto", args=[self.producto.pk])).status_code, 404)

    def test_el_panel_avisa_y_al_completar_vuelven_a_publicarse(self):
        self.quitar_datos()
        self.client.force_login(self.dueno)
        self.assertContains(self.client.get(reverse("dashboard")), "Completar ahora")
        respuesta = self.client.post(reverse("negocio_datos"), {"direccion": "Carrera 7 # 8-9", "telefono": "601 555 1234", "email": "ventas@pan.co"})
        self.assertRedirects(respuesta, reverse("dashboard"))
        self.negocio.refresh_from_db()
        self.assertTrue(self.negocio.datos_completos)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Completar ahora")
        self.assertEqual(self.client.get(reverse("tienda_producto", args=[self.producto.pk])).status_code, 200)

    def test_completar_datos_exige_los_dos(self):
        self.quitar_datos()
        self.client.force_login(self.dueno)
        respuesta = self.client.post(reverse("negocio_datos"), {"direccion": "", "telefono": "", "email": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.negocio.refresh_from_db()
        self.assertFalse(self.negocio.datos_completos)

    def test_no_se_pueden_cambiar_nombre_ni_nit_desde_el_panel(self):
        self.client.force_login(self.dueno)
        self.client.post(reverse("negocio_datos"), {"direccion": "Calle 9", "telefono": "6015551234", "nombre": "Otro", "nit": "1"})
        self.negocio.refresh_from_db()
        self.assertEqual((self.negocio.nombre, self.negocio.nit), ("Panadería", "900123"))

    def test_rol_sin_permiso_no_edita_los_datos(self):
        from .models import Membresia, Rol
        from .tests_compra import crear_usuario

        empleado = crear_usuario("empleado@correo.co")
        rol = Rol.objects.create(empresa=self.negocio, nombre="Vendedor", es_admin=False)
        Membresia.objects.create(usuario=empleado, empresa=self.negocio, rol=rol)
        self.client.force_login(empleado)
        self.assertEqual(self.client.get(reverse("negocio_datos")).status_code, 403)

    def test_el_comprador_ve_los_datos_del_vendedor_en_su_pedido(self):
        from .tests_compra import DATOS_ENVIO, crear_usuario

        Empresa.objects.filter(pk=self.negocio.pk).update(email="ventas@pan.co")
        self.client.force_login(crear_usuario("compra@correo.co"))
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get()
        with mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None):
            respuesta = self.client.get(reverse("pedido_detalle", args=[pedido.pk]))
        for dato in ("Datos del vendedor", "Panadería", "NIT 900123", "Calle 1 # 2-3", "6011234567", "ventas@pan.co"):
            with self.subTest(dato=dato):
                self.assertContains(respuesta, dato)


class RedondeoIvaTests(TestCase):
    """Un caso de empate: 0,50 con IVA del 1 % da 0,005, que debe quedar en 0,01 en todas partes."""

    def setUp(self):
        from .tests_compra import crear_negocio, crear_producto, crear_usuario

        self.dueno = crear_usuario("dueno@correo.co", "Dueño", "Tienda")
        self.negocio = crear_negocio("Panadería", "900123", self.dueno)
        self.producto = crear_producto(self.negocio, nombre="Galleta", precio="0.50", iva="1")

    def test_la_funcion_redondea_la_mitad_hacia_arriba(self):
        from decimal import Decimal

        from .impuestos import calcular_iva

        self.assertEqual(calcular_iva(Decimal("0.50"), Decimal("1")), Decimal("0.01"))
        self.assertEqual(calcular_iva(Decimal("1.50"), Decimal("1")), Decimal("0.02"))  # 0,015: también hacia arriba

    def test_catalogo_carrito_pedido_y_factura_dan_lo_mismo(self):
        from decimal import Decimal

        from .carrito import _linea
        from .models import Cliente
        from .reservas import marcar_pagado
        from .services import crear_factura
        from .tests_compra import DATOS_ENVIO, crear_usuario

        esperado = Decimal("0.51")
        self.assertEqual(self.producto.precio_con_iva, esperado)
        self.assertEqual(_linea(self.producto, 1)["total"], esperado)

        self.client.force_login(crear_usuario("compra@correo.co"))
        self.client.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})
        self.client.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get()
        self.assertEqual(pedido.total, esperado)
        marcar_pagado(pedido)
        self.assertEqual(pedido.factura.total, esperado)
        self.assertEqual(pedido.factura.detalles.get().valor_iva, Decimal("0.01"))

        cliente = Cliente.objects.create(empresa=self.negocio, tipo_documento="CC", numero_documento="5", nombre="C")
        factura = crear_factura(empresa=self.negocio, usuario=self.dueno, cliente=cliente, items=[{"producto": self.producto, "cantidad": 1}])
        self.assertEqual(factura.total, esperado)


class LimpiezaTests(TestCase):
    def test_quien_soy_ya_no_existe(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("quien_soy")
        self.assertEqual(self.client.get("/panel/quien-soy/").status_code, 404)

    def test_eliminar_producto_exige_inventario_eliminar(self):
        from decimal import Decimal

        from .models import Membresia, Permiso, Producto, Rol, Usuario

        empresa = Empresa.objects.create(nombre="Una", nit="1", slug="una")
        for codigo, debe_eliminar in (("inventario.eliminar", True), ("productos.eliminar", False)):
            with self.subTest(permiso=codigo):
                usuario = Usuario.objects.create_user(username=f"{codigo}@c.co", email=f"{codigo}@c.co", password="x")
                rol = Rol.objects.create(empresa=empresa, nombre=codigo, es_admin=False)
                rol.permisos.add(Permiso.objects.get_or_create(codigo=codigo, defaults={"descripcion": codigo})[0])
                Membresia.objects.create(usuario=usuario, empresa=empresa, rol=rol)
                producto = Producto.objects.create(empresa=empresa, codigo=codigo, nombre="P", precio=Decimal("1"))
                self.client.force_login(usuario)
                respuesta = self.client.post(reverse("productos_eliminar", args=[producto.pk]))
                producto.refresh_from_db()
                self.assertEqual(producto.activo, not debe_eliminar)
                if not debe_eliminar:
                    self.assertEqual(respuesta.status_code, 403)

    def test_etiquetas_salen_de_estado(self):
        pedido = Pedido(estado=Pedido.Estado.VENCIDO)
        self.assertEqual(pedido.estado_etiqueta, Pedido.Estado.VENCIDO.label)
        self.assertEqual(Pedido(estado=Pedido.Estado.REQUIERE_REEMBOLSO).estado_etiqueta, "Requiere reembolso")

    def test_destino_seguro_es_una_funcion_publica_compartida(self):
        from django.test import RequestFactory

        from . import views_compra, views_tienda
        from .redirecciones import destino_seguro

        self.assertIs(views_compra.destino_seguro, destino_seguro)
        self.assertIs(views_tienda.destino_seguro, destino_seguro)
        fabrica = RequestFactory()
        self.assertEqual(destino_seguro(fabrica.get("/", {"next": "/carrito/"})), "/carrito/")
        self.assertEqual(destino_seguro(fabrica.get("/", {"next": "https://malo.example/"})), "")


class EsperaEntreConsultasTests(PedidoBase):
    """Las páginas que se recargan no consultan a Wompi más de una vez cada 10 s."""

    def setUp(self):
        super().setUp()
        from .tests_compra import transaccion

        self.transaccion = transaccion
        self.pago = self.intento()
        self.estado = reverse("pedido_estado", args=[self.pedido.pk])

    def pasar_diez_segundos(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import Pago

        Pago.objects.filter(pk=self.pago.pk).update(consultado_en=timezone.now() - timedelta(seconds=11))

    def test_dos_consultas_seguidas_llaman_una_sola_vez_a_wompi(self):
        self.assertEqual(self.client.get(self.estado).json()["estado"], "procesando")
        self.assertEqual(self.client.get(self.estado).json()["estado"], "procesando")
        self.assertEqual(self.buscar.call_count, 1)

    def test_mientras_espera_responde_con_lo_guardado(self):
        self.client.get(self.estado)
        self.buscar.return_value = self.transaccion(self.pago)
        self.assertEqual(self.client.get(self.estado).json()["estado"], "procesando")
        self.assertEqual(self.buscar.call_count, 1)

    def test_pasados_diez_segundos_vuelve_a_consultar(self):
        self.client.get(self.estado)
        self.buscar.return_value = self.transaccion(self.pago)
        self.pasar_diez_segundos()
        self.assertEqual(self.client.get(self.estado).json()["estado"], "pagado")
        self.assertEqual(self.buscar.call_count, 2)

    def test_el_detalle_del_pedido_tambien_espera(self):
        detalle = reverse("pedido_detalle", args=[self.pedido.pk])
        self.client.get(detalle)
        self.client.get(detalle)
        self.assertEqual(self.buscar.call_count, 1)

    def test_pagar_consulta_aunque_no_hayan_pasado_diez_segundos(self):
        from .models import Pago

        self.client.get(self.estado)  # deja la marca de consulta reciente
        self.buscar.return_value = self.transaccion(self.pago)
        self.client.post(reverse("pedido_pagar", args=[self.pedido.pk]))
        self.assertEqual(self.buscar.call_count, 2)
        self.assertEqual(Pago.objects.count(), 1)  # no abrió un segundo cobro
        self.recargar()
        self.assertEqual(self.pedido.estado, Pedido.Estado.PAGADO)


class InicioPanelTests(TestCase):
    def setUp(self):
        from decimal import Decimal

        from .models import Cliente, Membresia, Producto, Rol, Usuario
        from .services import crear_factura

        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000090", slug="mia-inicio", direccion="C 1", telefono="6011234567")
        self.usuario = Usuario.objects.create_user(username="i@test.co", email="i@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(self.usuario)

        cliente = Cliente.objects.create(empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente")
        self.sano = Producto.objects.create(empresa=self.empresa, codigo="S", nombre="Sano", precio=Decimal("1000"), iva_porcentaje=Decimal("0"), stock=50, stock_minimo=5)
        Producto.objects.create(empresa=self.empresa, codigo="B", nombre="Bajo", precio=Decimal("1"), stock=1, stock_minimo=5)

        def vender(cantidad, empresa=self.empresa, cliente=cliente, producto=None):
            return crear_factura(empresa=empresa, usuario=self.usuario, cliente=cliente, items=[{"producto": producto or self.sano, "cantidad": cantidad}])

        self.hoy = vender(2)  # 2.000
        self.anulada = vender(3)
        from .services import anular_factura

        anular_factura(factura=self.anulada, usuario=self.usuario)

        # De otra empresa: nunca debe contarse
        otra = Empresa.objects.create(nombre="Otra", nit="900000091", slug="otra-inicio")
        cliente_otro = Cliente.objects.create(empresa=otra, tipo_documento="CC", numero_documento="2", nombre="C")
        producto_otro = Producto.objects.create(empresa=otra, codigo="O", nombre="O", precio=Decimal("99999"), iva_porcentaje=Decimal("0"), stock=9)
        self.ajena = vender(1, empresa=otra, cliente=cliente_otro, producto=producto_otro)

    def contexto(self):
        return self.client.get(reverse("dashboard")).context

    def test_ventas_del_mes_sin_anuladas_ni_otras_empresas(self):
        from decimal import Decimal

        contexto = self.contexto()
        self.assertEqual(contexto["ventas_mes"], Decimal("2000.00"))
        self.assertEqual(contexto["facturas_mes"], 1)
        self.assertEqual(list(contexto["ultimas_facturas"]), [self.hoy])

    def test_salud_del_inventario(self):
        contexto = self.contexto()
        self.assertEqual((contexto["n_stock_bajo"], contexto["productos_sanos"]), (1, 1))
        self.assertEqual(contexto["salud_inventario"], 50)

    def test_series_de_meses_y_dias(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import Factura

        Factura.objects.filter(pk=self.hoy.pk).update(creado_en=timezone.now() - timedelta(days=3))
        contexto = self.contexto()
        meses, dias = contexto["serie_meses"], contexto["serie_dias"]
        self.assertEqual((len(meses["etiquetas"]), len(meses["valores"])), (6, 6))
        self.assertEqual((len(dias["etiquetas"]), len(dias["valores"])), (7, 7))
        self.assertEqual(dias["valores"][-4], 2000.0)  # hace 3 días
        self.assertEqual(sum(dias["valores"]), 2000.0)
        self.assertEqual(sum(meses["valores"]), 2000.0)  # sin la anulada ni la de otra empresa

    def test_venta_de_hace_dos_meses_va_en_su_mes(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import Factura

        Factura.objects.filter(pk=self.hoy.pk).update(creado_en=timezone.now() - timedelta(days=62))
        contexto = self.contexto()
        self.assertEqual(contexto["ventas_mes"], 0)
        self.assertEqual(sum(contexto["serie_meses"]["valores"]), 2000.0)
        self.assertEqual(contexto["serie_meses"]["valores"][-1], 0.0)

    def test_la_pagina_muestra_los_datos(self):
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "$ 2.000")
        self.assertContains(respuesta, "50%")
        self.assertContains(respuesta, 'id="datos-meses"')

    def test_otra_empresa_ve_solo_lo_suyo(self):
        from .models import Membresia, Rol, Usuario

        otra = Empresa.objects.get(slug="otra-inicio")
        usuario = Usuario.objects.create_user(username="o@test.co", email="o@test.co", password="x")
        Membresia.objects.create(usuario=usuario, empresa=otra, rol=Rol.objects.create(empresa=otra, nombre="A", es_admin=True))
        self.client.force_login(usuario)
        contexto = self.contexto()
        self.assertEqual(contexto["ventas_mes"], 99999)
        self.assertEqual(list(contexto["ultimas_facturas"]), [self.ajena])

    def test_sin_productos_ni_ventas_no_falla(self):
        from .models import Membresia, Rol, Usuario

        vacia = Empresa.objects.create(nombre="Vacía", nit="900000092", slug="vacia")
        usuario = Usuario.objects.create_user(username="v@test.co", email="v@test.co", password="x")
        Membresia.objects.create(usuario=usuario, empresa=vacia, rol=Rol.objects.create(empresa=vacia, nombre="A", es_admin=True))
        self.client.force_login(usuario)
        contexto = self.contexto()
        self.assertEqual((contexto["ventas_mes"], contexto["salud_inventario"]), (0, 100))


class LimiteDeIntentosTests(TestCase):
    CLAVE = "ClaveSegura#2026"

    def setUp(self):
        from .models import Usuario

        self.usuario = Usuario.objects.create_user(username="ana@correo.co", email="ana@correo.co", password=self.CLAVE)

    def ingresar(self, correo="ana@correo.co", clave="equivocada"):
        return self.client.post(reverse("login"), {"username": correo, "password": clave})

    def test_cinco_fallos_bloquean_aunque_luego_la_clave_sea_correcta(self):
        for _ in range(5):
            self.ingresar()
        respuesta = self.ingresar(clave=self.CLAVE)
        self.assertEqual(respuesta.status_code, 429)
        self.assertContains(respuesta, "Tómate un respiro", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cuatro_fallos_aun_dejan_entrar(self):
        for _ in range(4):
            self.ingresar()
        self.assertEqual(self.ingresar(clave=self.CLAVE).status_code, 302)

    def test_cambiar_mayusculas_no_evita_el_bloqueo(self):
        for correo in ("ana@correo.co", "ANA@correo.co", "Ana@Correo.co", "ana@CORREO.CO", "aNa@correo.co"):
            self.ingresar(correo=correo)
        self.assertEqual(self.ingresar(clave=self.CLAVE).status_code, 429)

    def test_el_bloqueo_dura_quince_minutos(self):
        from datetime import timedelta

        from axes.models import AccessAttempt
        from django.utils import timezone

        for _ in range(5):
            self.ingresar()
        AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.ingresar(clave=self.CLAVE).status_code, 302)

    def test_otro_correo_desde_la_misma_ip_no_queda_bloqueado(self):
        from .models import Usuario

        Usuario.objects.create_user(username="luis@correo.co", email="luis@correo.co", password=self.CLAVE)
        for _ in range(5):
            self.ingresar()
        self.assertEqual(self.ingresar(correo="luis@correo.co", clave=self.CLAVE).status_code, 302)
