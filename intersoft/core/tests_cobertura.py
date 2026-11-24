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
        self.assertContains(resp_rep, 'class="tabla-wrap"')
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
        self.assertContains(resp_pos, 'aria-label="Resultados de productos"')
        self.assertContains(resp_pos, 'aria-label="Buscar cliente por nombre o documento"')
        self.assertContains(resp_pos, 'aria-label="Productos en la venta"')
        self.assertContains(resp_pos, 'aria-label="Vaciar venta actual"')

    def test_importacion_excel_errores_y_validaciones(self):
        import io
        import openpyxl
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.importaciones import importar_productos_excel

        # 1. Archivo corrupto / no Excel
        malo = SimpleUploadedFile("malo.xlsx", b"no-es-un-zip", content_type="application/octet-stream")
        res_malo = importar_productos_excel(empresa=self.empresa, archivo=malo, usuario=self.usuario)
        self.assertEqual(res_malo["creados"], 0)
        self.assertTrue(res_malo["errores"])

        # 2. Archivo vacío
        wb_vacio = openpyxl.Workbook()
        ws_v = wb_vacio.active
        ws_v.delete_rows(1, ws_v.max_row + 1)
        buf_v = io.BytesIO()
        wb_vacio.save(buf_v)
        buf_v.seek(0)
        res_vacio = importar_productos_excel(empresa=self.empresa, archivo=buf_v, usuario=self.usuario)
        self.assertEqual(res_vacio["creados"], 0)
        self.assertIn("vacío", res_vacio["errores"][0]["error"])

        # 3. Falta columna obligatoria 'precio'
        wb_col = openpyxl.Workbook()
        wb_col.active.append(["codigo", "nombre"])
        buf_col = io.BytesIO()
        wb_col.save(buf_col)
        buf_col.seek(0)
        res_col = importar_productos_excel(empresa=self.empresa, archivo=buf_col, usuario=self.usuario)
        self.assertIn("precio", res_col["errores"][0]["error"])

        # 4. Filas con múltiples errores (código existente, duplicado, negativos, IVA > 100, fila en blanco)
        wb_err = openpyxl.Workbook()
        ws_e = wb_err.active
        ws_e.append(["codigo", "nombre", "precio", "costo", "iva_porcentaje", "stock_minimo", "stock_inicial"])
        ws_e.append([None, None, None, None, None, None, None])  # fila vacía ignorada
        ws_e.append([self.prod.codigo, "Repetido", 1000, 500, 19, 1, 2])  # código existente
        ws_e.append(["", "", -10, "abc", 150, -2, "xyz"])  # múltiples errores de tipo/rango
        ws_e.append(["DUP1", "Valido", 2000, 1000, 19, 1, 5])
        ws_e.append(["DUP1", "Duplicado en archivo", 2000, 1000, 19, 1, 5])  # duplicado en archivo
        buf_err = io.BytesIO()
        wb_err.save(buf_err)
        buf_err.seek(0)
        res_err = importar_productos_excel(empresa=self.empresa, archivo=buf_err, usuario=self.usuario)
        self.assertEqual(res_err["creados"], 0)
        self.assertEqual(len(res_err["errores"]), 3)
        self.assertFalse(Producto.objects.filter(empresa=self.empresa, codigo="DUP1").exists())

    def test_configuracion_cache_redis_y_locmem(self):
        from intersoft.settings import construir_caches

        locmem = construir_caches("")
        self.assertEqual(locmem["default"]["BACKEND"], "django.core.cache.backends.locmem.LocMemCache")

        redis_cfg = construir_caches("redis://redis:6379/1")
        self.assertEqual(redis_cfg["default"]["BACKEND"], "django.core.cache.backends.redis.RedisCache")
        self.assertEqual(redis_cfg["default"]["LOCATION"], "redis://redis:6379/1")

    def test_pwa_camara_pos_y_campana_notificaciones(self):
        # 1. Service worker en la raíz y manifest en tienda
        resp_sw = self.client.get(reverse("sw_js"))
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn("javascript", resp_sw["Content-Type"])
        self.assertContains(self.client.get(reverse("marketplace")), "manifest.webmanifest")

        # 2. Campana de notificaciones en /panel/ con stock bajo + escáner cámara en POS
        self.prod.stock = 1
        self.prod.stock_minimo = 5
        self.prod.save(update_fields=["stock", "stock_minimo"])

        self.client.force_login(self.usuario)
        resp_dash = self.client.get(reverse("dashboard"))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, "notificaciones-menu")
        self.assertContains(resp_dash, "stock bajo")

        caja.abrir_turno(empresa=self.empresa, usuario=self.usuario, base=50000, bodega=self.principal)
        resp_pos = self.client.get(reverse("pos"))
        self.assertEqual(resp_pos.status_code, 200)
        self.assertContains(resp_pos, 'id="pos-escanear-camara"')
        self.assertContains(resp_pos, 'id="pos-camara-dialogo"')

    def test_dashboard_comparativa_bodega_y_exportaciones_excel(self):
        import io
        import openpyxl
        from django.utils import timezone

        cliente = Cliente.objects.create(
            empresa=self.empresa,
            nombre="Cliente Analitica",
            tipo_documento="CC",
            numero_documento="202020",
        )
        ahora = timezone.localtime()
        inicio_mes = ahora.replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        mes_ant_fecha = (inicio_mes - timedelta(days=5))

        f_ant = Factura.objects.create(
            empresa=self.empresa,
            numero=801,
            cliente=cliente,
            creada_por=self.usuario,
            bodega=self.principal,
            subtotal=10000,
            iva=0,
            total=10000,
            estado=Factura.Estado.EMITIDA,
        )
        Factura.objects.filter(pk=f_ant.pk).update(creado_en=mes_ant_fecha)

        Factura.objects.create(
            empresa=self.empresa,
            numero=802,
            cliente=cliente,
            creada_por=self.usuario,
            bodega=self.principal,
            subtotal=15000,
            iva=0,
            total=15000,
            estado=Factura.Estado.EMITIDA,
        )

        # 1. Dashboard: comparativa vs mes anterior (+50%) y filtro por bodega
        self.client.force_login(self.usuario)
        resp_dash = self.client.get(f"{reverse('dashboard')}?bodega={self.principal.pk}")
        self.assertEqual(resp_dash.status_code, 200)
        self.assertEqual(resp_dash.context["ventas_mes"], 15000)
        self.assertEqual(resp_dash.context["ventas_mes_anterior"], 10000)
        self.assertEqual(resp_dash.context["variacion_mes_pct"], 50.0)
        self.assertContains(resp_dash, "+50")

        # 2. Exportar pedidos marketplace a Excel
        Pedido.objects.create(
            empresa=self.empresa,
            comprador=self.usuario,
            numero=888,
            nombre="Comprador Export",
            email="exp@test.co",
            ciudad="Bogotá",
            estado=Pedido.Estado.PAGADO,
            expira_en=timezone.now() + timedelta(days=1),
            total=25000,
            neto_vendedor=25000,
        )
        resp_ped_xlsx = self.client.get(reverse("pedidos_panel_exportar"))
        self.assertEqual(resp_ped_xlsx.status_code, 200)
        self.assertIn("spreadsheetml", resp_ped_xlsx["Content-Type"])
        wb_p = openpyxl.load_workbook(io.BytesIO(resp_ped_xlsx.content))
        self.assertEqual(wb_p.active.cell(row=2, column=1).value, 888)

        # 3. Exportar turnos POS a Excel
        caja.abrir_turno(empresa=self.empresa, usuario=self.usuario, base=50000, bodega=self.principal)
        resp_pos_xlsx = self.client.get(reverse("pos_turnos_exportar"))
        self.assertEqual(resp_pos_xlsx.status_code, 200)
        self.assertIn("spreadsheetml", resp_pos_xlsx["Content-Type"])
        wb_t = openpyxl.load_workbook(io.BytesIO(resp_pos_xlsx.content))
        self.assertEqual(wb_t.active.cell(row=2, column=8).value, "Abierta")

    def test_cabecera_content_security_policy(self):
        resp = self.client.get(reverse("marketplace"))
        self.assertEqual(resp.status_code, 200)
        csp = resp.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertNotIn("'unsafe-inline'", csp.split("script-src")[1].split(";")[0])

    def test_paginas_legales_publicas(self):
        self.client.logout()
        home = self.client.get(reverse("marketplace"))
        self.assertContains(home, reverse("legal_terminos"))
        self.assertContains(home, reverse("legal_privacidad"))
        self.assertContains(home, reverse("legal_devoluciones"))

        for ruta, texto in (
            ("legal_terminos", "Términos y Condiciones de Uso"),
            ("legal_privacidad", "Ley 1581 de 2012"),
            ("legal_devoluciones", "Ley 1480 de 2011"),
        ):
            resp = self.client.get(reverse(ruta))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, texto)



