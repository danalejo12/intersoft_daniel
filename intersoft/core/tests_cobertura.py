"""Pruebas adicionales para reforzar la cobertura de bodegas y salud."""
from datetime import date, timedelta
from io import BytesIO

import openpyxl
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core import bodegas, caja, erp_services
from core.importaciones import importar_productos_excel
from core.models import (
    Bodega,
    Categoria,
    Cliente,
    Compra,
    ConteoFisico,
    DetalleFactura,
    DetallePedido,
    Empresa,
    Existencia,
    Factura,
    Favorito,
    LineaCompra,
    Membresia,
    MovimientoInventario,
    Pedido,
    Producto,
    Proveedor,
    Rol,
    TrasladoBodega,
    TurnoCaja,
    Usuario,
)
from core.services import registrar_movimiento
from suscripciones.services import cambiar_plan


class BodegasVistasCoberturaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Bodegas Co", nit="940001", slug="bodegas-co", activa=True)
        cambiar_plan(self.empresa, "pro")
        self.usuario = Usuario.objects.create_user(username="bod@test.co", email="bod@test.co", password="x")
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol, activa=True)
        self.client.force_login(self.usuario)

        self.principal = bodegas.bodega_principal(self.empresa)
        self.sucursal = bodegas.guardar_bodega(
            empresa=self.empresa, nombre="Sucursal Norte", direccion="Calle 100"
        )
        self.cat = Categoria.objects.create(empresa=self.empresa, nombre="Cat")
        self.prod = Producto.objects.create(
            empresa=self.empresa, categoria=self.cat, codigo="B1", nombre="Prod 1", precio=5000
        )
        registrar_movimiento(
            empresa=self.empresa,
            producto=self.prod,
            tipo=MovimientoInventario.Tipo.ENTRADA,
            bodega=self.principal,
            cantidad=10,
            usuario=self.usuario,
            referencia="Carga inicial",
        )

    def test_bodegas_editar_desactivar_y_traslado(self):
        # Editar sucursal GET y POST
        url_editar = reverse("bodegas_editar", args=[self.sucursal.pk])
        self.assertEqual(self.client.get(url_editar).status_code, 200)
        resp_post = self.client.post(
            url_editar,
            {"nombre": "Sucursal Norte 2", "direccion": "Calle 101"},
            follow=True,
        )
        self.assertEqual(resp_post.status_code, 200)
        self.sucursal.refresh_from_db()
        self.assertEqual(self.sucursal.nombre, "Sucursal Norte 2")

        # Traslado GET y POST (error por exceso y éxito)
        url_traslado = reverse("productos_trasladar", args=[self.prod.pk])
        self.assertEqual(self.client.get(url_traslado).status_code, 200)
        resp_exceso = self.client.post(
            url_traslado,
            {"origen": str(self.principal.pk), "destino": str(self.sucursal.pk), "cantidad": "99"},
        )
        self.assertEqual(resp_exceso.status_code, 200)

        resp_ok = self.client.post(
            url_traslado,
            {"origen": str(self.principal.pk), "destino": str(self.sucursal.pk), "cantidad": "4"},
            follow=True,
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(bodegas.existencia(self.prod, self.sucursal), 4)

        # Desactivar principal falla con mensaje; desactivar sucursal vacía funciona
        bodegas.trasladar(
            empresa=self.empresa,
            producto=self.prod,
            origen=self.sucursal,
            destino=self.principal,
            cantidad=4,
            usuario=self.usuario,
        )
        self.client.post(reverse("bodegas_desactivar", args=[self.principal.pk]))
        self.principal.refresh_from_db()
        self.assertTrue(self.principal.activa)

        self.client.post(reverse("bodegas_desactivar", args=[self.sucursal.pk]))
        self.sucursal.refresh_from_db()
        self.assertFalse(self.sucursal.activa)

    def test_salud_endpoint(self):
        self.assertEqual(self.client.get(reverse("salud")).status_code, 200)

    def test_compra_con_bodega_destino_ingresa_a_esa_bodega(self):
        prov = Proveedor.objects.create(empresa=self.empresa, nombre="Prov 1", documento="8001")
        compra = Compra.objects.create(
            empresa=self.empresa,
            proveedor=prov,
            referencia="FC-100",
            bodega=self.sucursal,
            vencimiento=date.today() + timedelta(days=30),
        )
        LineaCompra.objects.create(
            empresa=self.empresa,
            compra=compra,
            producto=self.prod,
            cantidad=7,
            costo=2000,
        )
        erp_services.recibir_compra(empresa=self.empresa, pk=compra.pk, usuario=self.usuario)
        self.assertEqual(bodegas.existencia(self.prod, self.sucursal), 7)
        self.assertEqual(bodegas.existencia(self.prod, self.principal), 10)
        self.assertTrue(
            MovimientoInventario.objects.filter(
                empresa=self.empresa, producto=self.prod, bodega=self.sucursal, referencia="Compra FC-100"
            ).exists()
        )

    def test_alerta_stock_minimo_por_bodega(self):
        self.prod.stock_minimo = 0
        self.prod.save(update_fields=["stock_minimo"])
        Existencia.objects.create(
            empresa=self.empresa, bodega=self.sucursal, producto=self.prod, cantidad=2, stock_minimo=5
        )
        mail.outbox.clear()
        call_command("procesar_reservas_y_alertas")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Sucursal Norte", mail.outbox[0].body)

    def test_traslado_en_transito_y_confirmacion_idempotente(self):
        resp_env = self.client.post(
            reverse("productos_trasladar", args=[self.prod.pk]),
            {
                "origen": str(self.principal.pk),
                "destino": str(self.sucursal.pk),
                "cantidad": "6",
                "en_transito": "1",
            },
        )
        self.assertEqual(resp_env.status_code, 302)
        traslado = TrasladoBodega.objects.get(empresa=self.empresa)
        self.assertEqual(traslado.estado, TrasladoBodega.Estado.ENVIADO)
        self.assertEqual(bodegas.existencia(self.prod, self.principal), 4)
        self.assertEqual(bodegas.existencia(self.prod, self.sucursal), 0)

        # Confirmar recepción (y segunda confirmación idempotente no duplica)
        self.client.post(reverse("bodegas_traslado_confirmar", args=[traslado.pk]))
        bodegas.confirmar_traslado(empresa=self.empresa, pk=traslado.pk, usuario=self.usuario)
        traslado.refresh_from_db()
        self.assertEqual(traslado.estado, TrasladoBodega.Estado.RECIBIDO)
        self.assertEqual(bodegas.existencia(self.prod, self.sucursal), 6)

    def test_conteo_fisico_hoja_imprimible_y_ajuste_masivo(self):
        url_conteo = reverse("bodegas_conteo", args=[self.principal.pk])
        resp_get = self.client.get(url_conteo)
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Imprimir hoja")

        resp_post = self.client.post(
            url_conteo,
            {"observaciones": "Conteo cierre", f"conteo_{self.prod.pk}": "8"},
            follow=True,
        )
        self.assertEqual(resp_post.status_code, 200)
        self.assertEqual(bodegas.existencia(self.prod, self.principal), 8)
        self.assertTrue(ConteoFisico.objects.filter(empresa=self.empresa, bodega=self.principal, aplicado=True).exists())
        self.assertTrue(
            MovimientoInventario.objects.filter(
                empresa=self.empresa,
                producto=self.prod,
                bodega=self.principal,
                tipo=MovimientoInventario.Tipo.AJUSTE,
                cantidad=-2,
            ).exists()
        )

    def test_importar_productos_excel_valida_errores_e_importa_stock_inicial(self):
        # 1. Excel con error en fila 2 (precio negativo) -> 0 creados y reporte por fila
        wb_err = openpyxl.Workbook()
        ws_err = wb_err.active
        ws_err.append(["codigo", "nombre", "categoria", "precio", "stock_inicial"])
        ws_err.append(["EX1", "Producto Malo", "Cat", -100, 5])
        buf_err = BytesIO()
        wb_err.save(buf_err)
        buf_err.seek(0)

        res_err = importar_productos_excel(
            empresa=self.empresa, archivo=buf_err, usuario=self.usuario, bodega=self.sucursal
        )
        self.assertEqual(res_err["creados"], 0)
        self.assertEqual(res_err["errores"][0]["fila"], 2)
        self.assertFalse(Producto.objects.filter(empresa=self.empresa, codigo="EX1").exists())

        # 2. Excel válido vía vista -> crea producto y registra stock inicial en la bodega elegida
        wb_ok = openpyxl.Workbook()
        ws_ok = wb_ok.active
        ws_ok.append(["codigo", "nombre", "categoria", "precio", "stock_inicial"])
        ws_ok.append(["EX2", "Producto Excel", "Línea Nueva", 15000, 12])
        buf_ok = BytesIO()
        wb_ok.save(buf_ok)
        archivo = SimpleUploadedFile(
            "catalogo.xlsx",
            buf_ok.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp_imp = self.client.post(
            reverse("productos_importar"),
            {"archivo": archivo, "bodega": str(self.sucursal.pk)},
            follow=True,
        )
        self.assertEqual(resp_imp.status_code, 200)
        prod_ex = Producto.objects.get(empresa=self.empresa, codigo="EX2")
        self.assertEqual(bodegas.existencia(prod_ex, self.sucursal), 12)

    def test_ticket_pos_pdf_y_envio_por_correo_y_reportes_bodega_turno(self):
        turno = caja.abrir_turno(
            empresa=self.empresa, usuario=self.usuario, base=50000, bodega=self.principal
        )
        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nombre="Cliente Ticket",
            tipo_documento="CC",
            numero_documento="101010",
            email="ticket@cliente.co",
        )
        factura = Factura.objects.create(
            empresa=self.empresa,
            numero=501,
            cliente=cliente,
            creada_por=self.usuario,
            turno=turno,
            bodega=self.principal,
            subtotal=10000,
            iva=0,
            total=10000,
            estado=Factura.Estado.EMITIDA,
        )
        DetalleFactura.objects.create(
            empresa=self.empresa,
            factura=factura,
            producto=self.prod,
            cantidad=2,
            precio_unitario=5000,
            iva_porcentaje=0,
        )

        # 1. Ticket PDF
        resp_pdf = self.client.get(reverse("pos_ticket_pdf", args=[factura.pk]))
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf["Content-Type"], "application/pdf")
        self.assertTrue(resp_pdf.content.startswith(b"%PDF-"))

        # 2. Envío por correo con adjunto PDF
        mail.outbox.clear()
        resp_mail = self.client.post(
            reverse("pos_ticket_correo", args=[factura.pk]),
            {"correo": "comprador@correo.co"},
            follow=True,
        )
        self.assertEqual(resp_mail.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 1)

        # 3. Reportes ERP por bodega, turno, margen y rotación
        resp_rep = self.client.get(reverse("erp_reportes"))
        self.assertEqual(resp_rep.status_code, 200)
        self.assertContains(resp_rep, "Ventas por bodega")
        self.assertContains(resp_rep, "Ventas por turno de caja")
        self.assertContains(resp_rep, "Márgenes y rotación")
        self.assertEqual(len(resp_rep.context["ventas_por_bodega"]), 1)
        self.assertEqual(len(resp_rep.context["ventas_por_turno"]), 1)
        self.assertEqual(len(resp_rep.context["rotacion_margenes"]), 1)

    def test_linea_tiempo_envio_favoritos_y_volver_a_comprar(self):
        self.empresa.direccion = "Calle 1 # 2-3"
        self.empresa.telefono = "3001112233"
        self.empresa.save(update_fields=["direccion", "telefono"])
        self.prod.publicado = True
        self.prod.save(update_fields=["publicado"])

        comprador = Usuario.objects.create_user(username="comp-fav@test.co", email="comp-fav@test.co", password="x")
        otro = Usuario.objects.create_user(username="otro-fav@test.co", email="otro-fav@test.co", password="x")
        from django.utils import timezone

        pedido = Pedido.objects.create(
            empresa=self.empresa,
            comprador=comprador,
            numero=900,
            nombre="Comprador Favorito",
            email="comp-fav@test.co",
            estado=Pedido.Estado.PAGADO,
            estado_envio=Pedido.EstadoEnvio.ENVIADO,
            transportadora="Servientrega",
            numero_guia="GUIA-777",
            expira_en=timezone.now() + timedelta(days=1),
            total=10000,
        )
        DetallePedido.objects.create(
            empresa=self.empresa,
            pedido=pedido,
            producto=self.prod,
            cantidad=2,
            precio_unitario=5000,
            iva_porcentaje=0,
        )

        self.client.force_login(comprador)
        # Línea de tiempo en detalle de pedido
        resp_ped = self.client.get(reverse("pedido_detalle", args=[pedido.pk]))
        self.assertEqual(resp_ped.status_code, 200)
        self.assertContains(resp_ped, "Seguimiento de envío")
        self.assertContains(resp_ped, "GUIA-777")

        # Favoritos toggle + lista
        self.client.post(reverse("favorito_toggle", args=[self.prod.pk]))
        self.assertTrue(Favorito.objects.filter(usuario=comprador, producto=self.prod).exists())
        resp_fav = self.client.get(reverse("favoritos_lista"))
        self.assertContains(resp_fav, self.prod.nombre)

        # Volver a comprar recarga el carrito
        resp_re = self.client.post(reverse("pedido_volver_a_comprar", args=[pedido.pk]), follow=True)
        self.assertEqual(resp_re.status_code, 200)
        self.assertContains(resp_re, self.prod.nombre)

        # Otro comprador no puede volver a comprar un pedido ajeno (404)
        self.client.force_login(otro)
        self.assertEqual(self.client.post(reverse("pedido_volver_a_comprar", args=[pedido.pk])).status_code, 404)

    def test_rate_limiting_webhooks_endpoints_y_drf(self):
        from django.core.cache import cache
        from django.test import override_settings

        cache.clear()
        reglas_estrictas = (
            ("/webhooks/wompi/", ("POST",), 2, 60, "test_wompi"),
            ("/login/", ("POST",), 2, 60, "test_login"),
        )
        with override_settings(RATELIMIT_ACTIVO=True, RATELIMIT_REGLAS=reglas_estrictas):
            # 1. Webhook Wompi limitado a 2 peticiones/minuto
            for _ in range(2):
                r = self.client.post("/webhooks/wompi/", data="{}", content_type="application/json")
                self.assertNotEqual(r.status_code, 429)
            r_429 = self.client.post("/webhooks/wompi/", data="{}", content_type="application/json")
            self.assertEqual(r_429.status_code, 429)
            self.assertIn("Retry-After", r_429)

            # 2. Endpoint crítico /login/ limitado
            self.client.logout()
            for _ in range(2):
                r = self.client.post("/login/", {"username": "no@existe.co", "password": "x"})
                self.assertNotEqual(r.status_code, 429)
            r_login_429 = self.client.post("/login/", {"username": "no@existe.co", "password": "x"})
            self.assertEqual(r_login_429.status_code, 429)

        cache.clear()

        # 3. DRF throttling configurado en settings
        from django.conf import settings
        self.assertIn("rest_framework.throttling.AnonRateThrottle", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"])
        self.assertIn("rest_framework.throttling.UserRateThrottle", settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"])

    def test_accesibilidad_tienda_y_pos(self):
        # Tienda pública: enlace saltar-contenido, #contenido-principal y aria-live en carrito
        self.client.logout()
        resp_tienda = self.client.get(reverse("marketplace"))
        self.assertEqual(resp_tienda.status_code, 200)
        self.assertContains(resp_tienda, 'class="saltar-contenido"')
        self.assertContains(resp_tienda, 'id="contenido-principal"')
        self.assertContains(resp_tienda, 'aria-live="polite"')

        # POS con turno abierto: controles con aria-label y saltar-contenido
        self.client.force_login(self.usuario)
        caja.abrir_turno(empresa=self.empresa, usuario=self.usuario, base=50000, bodega=self.principal)
        resp_pos = self.client.get(reverse("pos"))
        self.assertEqual(resp_pos.status_code, 200)
        self.assertContains(resp_pos, 'class="saltar-contenido"')
        self.assertContains(resp_pos, 'aria-label="Resultados de productos"')
        self.assertContains(resp_pos, 'aria-label="Buscar cliente por nombre o documento"')
        self.assertContains(resp_pos, 'aria-label="Productos en la venta"')
        self.assertContains(resp_pos, 'aria-label="Vaciar venta actual"')



