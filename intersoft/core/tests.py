"""
Pruebas automáticas de Intersoft.
Ejecutar:  python manage.py test core
"""
import json
from decimal import Decimal
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ProductoForm
from .models import Cliente, Empresa, Factura, Membresia, MovimientoInventario, Pago, Producto, Rol, Usuario
from .pagos import (
    PagoNoPermitido,
    calcular_checksum,
    calcular_firma_integridad,
    crear_evento_simulado,
    crear_pago,
    monto_en_centavos,
)
from .services import StockInsuficiente, anular_factura, crear_factura, registrar_movimiento

class FacturacionTests(TestCase):
    def setUp(self):
        # setUp se ejecuta ANTES de cada prueba, con una base de datos limpia
        self.empresa = Empresa.objects.create(nombre="Empresa Test", nit="900000001", slug="empresa-test")
        self.usuario = Usuario.objects.create_user(username="v@test.co", email="v@test.co", password="x")
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente Test"
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="P1", nombre="Producto Test",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )

    def vender(self, cantidad):
        return crear_factura(
            empresa=self.empresa, usuario=self.usuario, cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": cantidad}],
        )

    def test_calcula_totales_y_descuenta_stock(self):
        factura = self.vender(3)
        self.producto.refresh_from_db()   # vuelve a leer el producto desde la base
        self.assertEqual(factura.subtotal, Decimal("3000.00"))
        self.assertEqual(factura.iva, Decimal("570.00"))
        self.assertEqual(factura.total, Decimal("3570.00"))
        self.assertEqual(self.producto.stock, 7)
        self.assertEqual(MovimientoInventario.objects.count(), 1)

    def test_stock_insuficiente_no_deja_nada_a_medias(self):
        with self.assertRaises(StockInsuficiente):
            self.vender(11)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(Factura.objects.count(), 0)

    def test_consecutivo(self):
        self.assertEqual(self.vender(1).numero, 1)
        self.assertEqual(self.vender(1).numero, 2)

    def test_anular_devuelve_el_stock(self):
        factura = self.vender(4)
        anular_factura(factura=factura, usuario=self.usuario)
        self.producto.refresh_from_db()
        factura.refresh_from_db()
        self.assertEqual(self.producto.stock, 10)
        self.assertEqual(factura.estado, Factura.Estado.ANULADA)

    def test_no_vende_producto_de_otra_empresa(self):
        otra = Empresa.objects.create(nombre="Otra", nit="900000002", slug="otra")
        ajeno = Producto.objects.create(empresa=otra, codigo="X", nombre="Ajeno", precio=Decimal("5"), stock=5)
        with self.assertRaises(ValueError):
            crear_factura(
                empresa=self.empresa, usuario=self.usuario, cliente=self.cliente,
                items=[{"producto": ajeno, "cantidad": 1}],
            )
        ajeno.refresh_from_db()
        self.assertEqual(ajeno.stock, 5)


class InventarioTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Empresa Inv", nit="900000010", slug="empresa-inv")
        self.usuario = Usuario.objects.create_user(username="i@test.co", email="i@test.co", password="x")
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="A1", nombre="Arroz", precio=Decimal("3000"), stock=0
        )

    def mover(self, tipo, cantidad):
        return registrar_movimiento(
            empresa=self.empresa, producto=self.producto, tipo=tipo, cantidad=cantidad, usuario=self.usuario
        )

    def test_entrada_y_ajuste_cambian_el_stock(self):
        self.mover(MovimientoInventario.Tipo.ENTRADA, 20)
        self.mover(MovimientoInventario.Tipo.AJUSTE, -3)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 17)
        self.assertEqual(MovimientoInventario.objects.filter(producto=self.producto).count(), 2)

    def test_ajuste_que_deja_negativo_no_registra_nada(self):
        self.mover(MovimientoInventario.Tipo.ENTRADA, 5)
        with self.assertRaises(StockInsuficiente):
            self.mover(MovimientoInventario.Tipo.AJUSTE, -6)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(MovimientoInventario.objects.filter(producto=self.producto).count(), 1)

    def test_codigo_repetido_en_la_misma_empresa_es_invalido(self):
        form = ProductoForm(
            data={"codigo": "a1", "nombre": "Otro", "precio": "100", "iva_porcentaje": "19", "stock_minimo": "0"},
            empresa=self.empresa,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("codigo", form.errors)


class EliminacionTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000020", slug="mia")
        self.ajena = Empresa.objects.create(nombre="Ajena", nit="900000021", slug="ajena")
        usuario = Usuario.objects.create_user(username="a@test.co", email="a@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(usuario)
        self.cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Mío"
        )
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo="E1", nombre="Producto", precio=Decimal("1000"), stock=5
        )

    def test_post_desactiva_cliente_sin_borrarlo(self):
        self.client.post(reverse("clientes_eliminar", args=[self.cliente.pk]))
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.activo)

    def test_post_desactiva_producto_sin_borrarlo(self):
        self.client.post(reverse("productos_eliminar", args=[self.producto.pk]))
        self.producto.refresh_from_db()
        self.assertFalse(self.producto.activo)

    def test_get_no_elimina(self):
        respuesta = self.client.get(reverse("clientes_eliminar", args=[self.cliente.pk]))
        self.assertEqual(respuesta.status_code, 405)
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.activo)

    def test_no_elimina_datos_de_otra_empresa(self):
        ajeno = Cliente.objects.create(
            empresa=self.ajena, tipo_documento="CC", numero_documento="2", nombre="Ajeno"
        )
        respuesta = self.client.post(reverse("clientes_eliminar", args=[ajeno.pk]))
        self.assertEqual(respuesta.status_code, 404)
        ajeno.refresh_from_db()
        self.assertTrue(ajeno.activo)
# pago -- pago 
class PagoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Empresa Pago", nit="900000030", slug="empresa-pago")
        self.usuario = Usuario.objects.create_user(username="p@test.co", email="p@test.co", password="x")
        cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente"
        )
        producto = Producto.objects.create(
            empresa=self.empresa, codigo="P1", nombre="Producto",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )
        self.factura = crear_factura(
            empresa=self.empresa, usuario=self.usuario, cliente=cliente,
            items=[{"producto": producto, "cantidad": 3}],
        )

    def test_firma_coincide_con_ejemplo_oficial_de_wompi(self):
        firma = calcular_firma_integridad(
            referencia="sk8-438k4-xmxm392-sn2m",
            monto_centavos=2490000,
            moneda="COP",
            secreto="prod_integrity_Z5mMke9x0k8gpErbDqwrJXMqsI6SFli6",
        )
        self.assertEqual(firma, "37c8407747e595535433ef8f6a811d853cd943046624a0ec04662b17bbf33bf5")

    def test_convierte_a_centavos(self):
        self.assertEqual(monto_en_centavos(Decimal("3570.00")), 357000)

    def test_el_monto_sale_de_la_factura(self):
        pago = crear_pago(factura=self.factura)
        self.assertEqual(pago.monto_centavos, 357000)
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)
        self.assertEqual(pago.empresa_id, self.empresa.id)

    def test_no_cobra_factura_anulada(self):
        anular_factura(factura=self.factura, usuario=self.usuario)
        with self.assertRaises(PagoNoPermitido):
            crear_pago(factura=self.factura)

    def test_no_cobra_factura_ya_pagada(self):
        pago = crear_pago(factura=self.factura)
        pago.estado = Pago.Estado.APROBADO
        pago.save()
        with self.assertRaises(PagoNoPermitido):
            crear_pago(factura=self.factura)

    def test_la_base_impide_dos_pagos_aprobados(self):
        primero = crear_pago(factura=self.factura)
        segundo = crear_pago(factura=self.factura)
        primero.estado = Pago.Estado.APROBADO
        primero.save()
        segundo.estado = Pago.Estado.APROBADO
        with self.assertRaises(IntegrityError), transaction.atomic():
            segundo.save()

    def test_no_anula_factura_pagada(self):
        pago = crear_pago(factura=self.factura)
        pago.estado = Pago.Estado.APROBADO
        pago.save()
        with self.assertRaises(ValueError):
            anular_factura(factura=self.factura, usuario=self.usuario)
@override_settings(
    WOMPI_PUBLIC_KEY="pub_test_x",
    WOMPI_INTEGRITY_SECRET="secreto_de_prueba",
    WOMPI_CHECKOUT_URL="https://checkout.wompi.co/p/",
)
class CobroVistaTests(TestCase):
    def crear_factura_de(self, empresa, usuario):
        cliente = Cliente.objects.create(
            empresa=empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente"
        )
        producto = Producto.objects.create(
            empresa=empresa, codigo="P1", nombre="Producto",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )
        return crear_factura(
            empresa=empresa, usuario=usuario, cliente=cliente,
            items=[{"producto": producto, "cantidad": 3}],
        )

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000040", slug="mia-pago")
        self.ajena = Empresa.objects.create(nombre="Ajena", nit="900000041", slug="ajena-pago")
        self.usuario = Usuario.objects.create_user(username="c@test.co", email="c@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(self.usuario)
        self.factura = self.crear_factura_de(self.empresa, self.usuario)

    def test_cobrar_redirige_al_checkout_sin_exponer_el_secreto(self):
        respuesta = self.client.post(reverse("facturas_cobrar", args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta.url.startswith("https://checkout.wompi.co/p/?"))
        self.assertIn("amount-in-cents=357000", respuesta.url)
        self.assertNotIn("secreto_de_prueba", respuesta.url)
        self.assertEqual(Pago.objects.count(), 1)

    def test_get_no_crea_pago(self):
        respuesta = self.client.get(reverse("facturas_cobrar", args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 405)
        self.assertEqual(Pago.objects.count(), 0)


@override_settings(DEBUG=True, PASARELA_SIMULADA=True, WOMPI_EVENTS_SECRET="secreto_eventos")
class FlujoPagoTests(TestCase):
    def crear_factura_de(self, empresa):
        cliente = Cliente.objects.create(
            empresa=empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente"
        )
        producto = Producto.objects.create(
            empresa=empresa, codigo="P1", nombre="Producto",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )
        return crear_factura(
            empresa=empresa, usuario=self.usuario, cliente=cliente,
            items=[{"producto": producto, "cantidad": 3}],
        )

    def enviar(self, evento):
        return self.client.post(
            reverse("wompi_webhook"), data=json.dumps(evento), content_type="application/json"
        )

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000050", slug="mia-flujo")
        self.ajena = Empresa.objects.create(nombre="Ajena", nit="900000051", slug="ajena-flujo")
        self.usuario = Usuario.objects.create_user(username="f@test.co", email="f@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(self.usuario)
        self.factura = self.crear_factura_de(self.empresa)

    def test_cobrar_redirige_al_simulador(self):
        respuesta = self.client.post(reverse("facturas_cobrar", args=[self.factura.pk]))
        pago = Pago.objects.get()
        self.assertEqual(respuesta.url, reverse("pagos_simulador", args=[pago.pk]))

    def test_simulador_aprueba_el_pago(self):
        pago = crear_pago(factura=self.factura)
        self.client.post(reverse("pagos_simulador", args=[pago.pk]), {"resultado": "APPROVED"})
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.APROBADO)
        self.assertTrue(self.factura.esta_pagada)

    def test_simulador_no_existe_con_debug_false(self):
        pago = crear_pago(factura=self.factura)
        with self.settings(DEBUG=False):
            respuesta = self.client.get(reverse("pagos_simulador", args=[pago.pk]))
        self.assertEqual(respuesta.status_code, 404)

    @override_settings(
        PASARELA_SIMULADA=False,
        WOMPI_PUBLIC_KEY="pub_test_x",
        WOMPI_INTEGRITY_SECRET="secreto_integridad",
        WOMPI_CHECKOUT_URL="https://checkout.wompi.co/p/",
    )
    def test_modo_real_va_a_wompi_sin_exponer_el_secreto(self):
        respuesta = self.client.post(reverse("facturas_cobrar", args=[self.factura.pk]))
        self.assertTrue(respuesta.url.startswith("https://checkout.wompi.co/p/?"))
        self.assertIn("amount-in-cents=357000", respuesta.url)
        self.assertNotIn("secreto_integridad", respuesta.url)

    def test_webhook_repetido_no_cambia_el_pago(self):
        pago = crear_pago(factura=self.factura)
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto="secreto_eventos")
        self.assertEqual(self.enviar(evento).status_code, 200)
        pago.refresh_from_db()
        primera_aprobacion = pago.aprobado_en
        self.assertEqual(self.enviar(evento).status_code, 200)
        pago.refresh_from_db()
        self.assertEqual(pago.aprobado_en, primera_aprobacion)

    def test_webhook_rechaza_firma_falsa(self):
        pago = crear_pago(factura=self.factura)
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto="secreto_falso")
        self.assertEqual(self.enviar(evento).status_code, 400)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.PENDIENTE)

    def test_monto_alterado_no_aprueba(self):
        pago = crear_pago(factura=self.factura)
        evento = crear_evento_simulado(pago=pago, status="APPROVED", secreto="secreto_eventos")
        evento["data"]["transaction"]["amount_in_cents"] = 100
        evento["signature"]["checksum"] = calcular_checksum(evento, "secreto_eventos")
        self.enviar(evento)
        pago.refresh_from_db()
        self.assertEqual(pago.estado, Pago.Estado.ERROR)

    # Antes tenía el mismo nombre que la siguiente y Python la reemplazaba: nunca se ejecutaba
    def test_cobrar_factura_de_otra_empresa_responde_404(self):
        ajena = self.crear_factura_de(self.ajena)
        respuesta = self.client.post(reverse("facturas_cobrar", args=[ajena.pk]))
        self.assertEqual(respuesta.status_code, 404)

    def test_no_cobra_factura_de_otra_empresa(self):
        ajena = self.crear_factura_de(self.ajena)
        respuesta = self.client.post(reverse("facturas_cobrar", args=[ajena.pk]))
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(Pago.objects.count(), 0)


@override_settings(DEBUG=True, PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_test_x")
class ConsultaWompiTests(TestCase):
    """Respaldo del webhook: al volver del checkout se consulta la API de Wompi."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Mía", nit="900000060", slug="mia-consulta")
        self.usuario = Usuario.objects.create_user(username="c@test.co", email="c@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol)
        self.client.force_login(self.usuario)
        cliente = Cliente.objects.create(
            empresa=self.empresa, tipo_documento="CC", numero_documento="1", nombre="Cliente"
        )
        producto = Producto.objects.create(
            empresa=self.empresa, codigo="P1", nombre="Producto",
            precio=Decimal("1000.00"), iva_porcentaje=Decimal("19.00"), stock=10,
        )
        factura = crear_factura(
            empresa=self.empresa, usuario=self.usuario, cliente=cliente,
            items=[{"producto": producto, "cantidad": 3}],
        )
        self.pago = crear_pago(factura=factura)

    def transaccion(self, **cambios):
        datos = {
            "id": "1234-5678-90", "status": "APPROVED", "reference": self.pago.referencia,
            "amount_in_cents": self.pago.monto_centavos, "currency": "COP",
            "payment_method_type": "CARD",
        }
        return {**datos, **cambios}

    def volver_de_wompi(self, transaccion):
        with mock.patch("core.pagos.consultar_transaccion", return_value=transaccion) as consulta:
            respuesta = self.client.get(
                reverse("pagos_resultado", args=[self.pago.pk]), {"id": "1234-5678-90"}
            )
        self.pago.refresh_from_db()
        return respuesta, consulta

    def test_aprobado_en_wompi_aprueba_el_pago(self):
        respuesta, consulta = self.volver_de_wompi(self.transaccion())
        consulta.assert_called_once_with("1234-5678-90")
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.pago.estado, Pago.Estado.APROBADO)

    def test_rechazado_en_wompi_rechaza_el_pago(self):
        self.volver_de_wompi(self.transaccion(status="DECLINED"))
        self.assertEqual(self.pago.estado, Pago.Estado.RECHAZADO)

    def test_transaccion_de_otra_referencia_no_cambia_el_pago(self):
        self.volver_de_wompi(self.transaccion(reference="INT-otra"))
        self.assertEqual(self.pago.estado, Pago.Estado.PENDIENTE)

    def test_wompi_no_responde_deja_pendiente(self):
        self.volver_de_wompi(None)
        self.assertEqual(self.pago.estado, Pago.Estado.PENDIENTE)

    def test_consulta_va_a_sandbox_con_llave_de_prueba(self):
        respuesta_api = mock.MagicMock()
        respuesta_api.__enter__.return_value.read.return_value = b'{"data": {"id": "1"}}'
        with mock.patch("core.pagos.urlopen", return_value=respuesta_api) as abrir:
            from .pagos import consultar_transaccion
            self.assertEqual(consultar_transaccion("1234-5678-90"), {"id": "1"})
            self.assertIsNone(consultar_transaccion("../admin"))  # id con formato raro: ni se consulta
        self.assertEqual(abrir.call_count, 1)
        self.assertEqual(
            abrir.call_args.args[0].full_url, "https://sandbox.wompi.co/v1/transactions/1234-5678-90"
        )


@override_settings(DEBUG=True, PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_test_x",
                   WOMPI_INTEGRITY_SECRET="test_integrity_x", WOMPI_PRIVATE_KEY="prv_test_x")
class WompiDesdeLocalTests(ConsultaWompiTests):
    """En 127.0.0.1 Wompi bloquea el redirect-url: se cobra sin él y se busca por referencia."""

    def test_redirect_local_no_se_envia(self):
        from .pagos import url_checkout
        self.assertNotIn("redirect-url", url_checkout(pago=self.pago, redirect_url="http://127.0.0.1:8000/x/"))
        self.assertNotIn("redirect-url", url_checkout(pago=self.pago, redirect_url="http://localhost:8000/x/"))
        self.assertIn("redirect-url", url_checkout(pago=self.pago, redirect_url="https://intersoft.co/x/"))

    def test_sin_id_busca_por_referencia(self):
        with mock.patch("core.pagos.buscar_transaccion_por_referencia",
                        return_value=self.transaccion(status="DECLINED")) as buscar:
            self.client.get(reverse("pagos_resultado", args=[self.pago.pk]))
        buscar.assert_called_once_with(self.pago.referencia)
        self.pago.refresh_from_db()
        self.assertEqual(self.pago.estado, Pago.Estado.RECHAZADO)

    def test_busqueda_usa_llave_privada_en_sandbox(self):
        respuesta_api = mock.MagicMock()
        respuesta_api.__enter__.return_value.read.return_value = json.dumps({"data": [
            {"id": "viejo", "created_at": "2026-11-01T10:00:00Z"},
            {"id": "nuevo", "created_at": "2026-11-05T10:00:00Z"},
        ]}).encode()
        with mock.patch("core.pagos.urlopen", return_value=respuesta_api) as abrir:
            from .pagos import buscar_transaccion_por_referencia
            self.assertEqual(buscar_transaccion_por_referencia("INT-abc")["id"], "nuevo")
        peticion = abrir.call_args.args[0]
        self.assertEqual(peticion.full_url, "https://sandbox.wompi.co/v1/transactions?reference=INT-abc")
        self.assertEqual(peticion.get_header("Authorization"), "Bearer prv_test_x")

    @override_settings(WOMPI_PRIVATE_KEY="")
    def test_sin_llave_privada_no_consulta(self):
        with mock.patch("core.pagos.urlopen") as abrir:
            from .pagos import buscar_transaccion_por_referencia
            self.assertIsNone(buscar_transaccion_por_referencia("INT-abc"))
        abrir.assert_not_called()


@override_settings(DEBUG=True, PASARELA_SIMULADA=False, WOMPI_PUBLIC_KEY="pub_test_x",
                   WOMPI_INTEGRITY_SECRET="test_integrity_x", WOMPI_PRIVATE_KEY="prv_test_x")
class PagoPendienteTests(ConsultaWompiTests):
    """Un pago aprobado en Wompi se refleja al volver, sin pasar por la página de resultado."""

    def test_lista_muestra_verificar_en_vez_de_pagar(self):
        with mock.patch("core.pagos.buscar_transaccion_por_referencia") as buscar:
            html = self.client.get(reverse("facturas_lista")).content.decode()
        buscar.assert_not_called()  # la lista no llama a Wompi
        self.assertIn("Verificar pago", html)
        self.assertNotIn("Pagar con Wompi", html)

    def test_detalle_consulta_wompi_y_marca_pagada(self):
        with mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=self.transaccion()):
            html = self.client.get(reverse("facturas_detalle", args=[self.pago.factura_id])).content.decode()
        self.pago.refresh_from_db()
        self.assertEqual(self.pago.estado, Pago.Estado.APROBADO)
        self.assertNotIn("Pagar con Wompi", html)

    def test_no_cobra_dos_veces_si_wompi_ya_aprobo(self):
        with mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=self.transaccion()):
            respuesta = self.client.post(reverse("facturas_cobrar", args=[self.pago.factura_id]))
        self.assertEqual(respuesta.url, reverse("facturas_lista"))
        self.assertEqual(Pago.objects.count(), 1)
        self.pago.refresh_from_db()
        self.assertEqual(self.pago.estado, Pago.Estado.APROBADO)


class AislamientoPanelTests(TestCase):
    """Otra empresa nunca ve ni cambia lo de este negocio: cada vista responde 404."""

    def setUp(self):
        self.mia = Empresa.objects.create(nombre="Mía", nit="900000070", slug="mia-aislada")
        self.ajena = Empresa.objects.create(nombre="Ajena", nit="900000071", slug="ajena-aislada")
        self.usuario = Usuario.objects.create_user(username="m@test.co", email="m@test.co", password="x")
        rol = Rol.objects.create(empresa=self.mia, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.mia, rol=rol)
        self.client.force_login(self.usuario)

        dueno_ajeno = Usuario.objects.create_user(username="otro@test.co", email="otro@test.co", password="x")
        self.cliente = Cliente.objects.create(empresa=self.ajena, tipo_documento="CC", numero_documento="9", nombre="Ajeno")
        self.producto = Producto.objects.create(
            empresa=self.ajena, codigo="AJ1", nombre="Ajeno", precio=Decimal("1000"), stock=10
        )
        self.factura = crear_factura(
            empresa=self.ajena, usuario=dueno_ajeno, cliente=self.cliente,
            items=[{"producto": self.producto, "cantidad": 1}],
        )

    def test_clientes_editar(self):
        url = reverse("clientes_editar", args=[self.cliente.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        respuesta = self.client.post(url, {"tipo_documento": "CC", "numero_documento": "9", "nombre": "Cambiado"})
        self.assertEqual(respuesta.status_code, 404)
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.nombre, "Ajeno")

    def test_productos_editar(self):
        url = reverse("productos_editar", args=[self.producto.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        respuesta = self.client.post(url, {"codigo": "AJ1", "nombre": "Cambiado", "precio": "1", "iva_porcentaje": "0", "stock_minimo": "0"})
        self.assertEqual(respuesta.status_code, 404)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.nombre, "Ajeno")

    def test_productos_kardex(self):
        self.assertEqual(self.client.get(reverse("productos_kardex", args=[self.producto.pk])).status_code, 404)

    def test_productos_movimiento(self):
        url = reverse("productos_movimiento", args=[self.producto.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        respuesta = self.client.post(url, {"tipo": "entrada", "cantidad": "5", "referencia": "x"})
        self.assertEqual(respuesta.status_code, 404)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 9)

    def test_facturas_detalle(self):
        self.assertEqual(self.client.get(reverse("facturas_detalle", args=[self.factura.pk])).status_code, 404)

    def test_facturas_anular(self):
        respuesta = self.client.post(reverse("facturas_anular", args=[self.factura.pk]))
        self.assertEqual(respuesta.status_code, 404)
        self.factura.refresh_from_db()
        self.assertEqual(self.factura.estado, Factura.Estado.EMITIDA)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 9)
