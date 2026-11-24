"""Pruebas de CAJA NEGRA de principio a fin (QA 2026-11-24).

Solo usan HTTP, como lo haría una persona con el navegador: registran cuentas, llenan formularios, compran y
pagan. No llaman servicios internos. Lo único simulado es Wompi (sistema externo): la prueba hace de banco que
responde «aprobado». Incluye particiones de equivalencia y valores límite, y pruebas de seguridad desde afuera.

Los defectos QA-01 y QA-02 se documentaron primero con @expectedFailure y ya están corregidos: sus pruebas
ahora pasan normalmente.
"""
import json
import re
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Empresa, Factura, MovimientoInventario, Pedido, Producto, TurnoCaja, Usuario
from core.testing_pagos import conectar_pruebas
from plataforma.models import RolPlataforma
from plataforma.totp import codigo_totp_actual
from pqrs.models import PQRS

CLAVE = "ClaveSegura#2026"
DATOS_ENVIO = {
    "nombre": "Laura Gómez", "tipo_documento": "CC", "numero_documento": "1020304050",
    "email": "laura@correo.co", "telefono": "3001234567", "departamento": "Cundinamarca",
    "ciudad": "Bogotá", "direccion": "Calle 80 # 10-20", "indicaciones": "Apto 301",
}


def registrar_persona(client, correo, nombre="Ana", apellido="Ruiz"):
    respuesta = client.post(reverse("registro"), {
        "first_name": nombre, "last_name": apellido, "email": correo, "password1": CLAVE, "password2": CLAVE,
        "acepta_datos": "on", "mayor_edad": "on",
    })
    assert respuesta.status_code == 302, respuesta.content[:500]
    return Usuario.objects.get(email=correo)


def transaccion_aprobada(pedido):
    pago = pedido.pagos.order_by("-creado_en").first()
    return {"id": "tx-e2e-1", "reference": pago.referencia, "status": "APPROVED",
            "amount_in_cents": pago.monto_centavos, "currency": pago.moneda, "payment_method_type": "CARD"}


class RecorridoNegocioYCompraTests(TestCase):
    """Un negocio nace, publica productos y vende en línea; un comprador compra y paga; todo cuadra."""

    def setUp(self):
        self.duena = Client()
        self.compradora = Client()

    def crear_negocio_con_producto(self):
        registrar_persona(self.duena, "duena@pasteleria.co", "Marta", "López")
        respuesta = self.duena.post(reverse("negocio_registrar"), {
            "nombre": "Pastelería Dulce", "nit": "901234567", "email": "hola@pasteleria.co",
            "telefono": "6017654321", "direccion": "Carrera 7 # 45-10",
        })
        self.assertEqual(respuesta.status_code, 302)
        self.negocio = Empresa.objects.get(nit="901234567")
        self.assertEqual(self.duena.get(reverse("dashboard")).status_code, 200)

        self.duena.post(reverse("categorias_crear"), {"nombre": "Tortas"})
        respuesta = self.duena.post(reverse("productos_crear"), {
            "codigo": "TOR-1", "nombre": "Torta de chocolate", "categoria": self.negocio_categoria(),
            "precio": "50000", "iva_porcentaje": "19", "stock_minimo": "1", "peso_gramos": "800",
            "descripcion": "Para 10 personas", "publicado": "on", "stock_inicial": "5",
        })
        self.assertEqual(respuesta.status_code, 302, respuesta.content[:800])
        self.producto = Producto.objects.get(empresa=self.negocio, codigo="TOR-1")
        # Precondición: el administrador conectó su pasarela (la verificación real va contra Wompi)
        conectar_pruebas(self.negocio)

    def negocio_categoria(self):
        from core.models import Categoria
        return Categoria.objects.get(empresa=self.negocio, nombre="Tortas").pk

    @mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None)
    def test_de_principio_a_fin(self, buscar):
        self.crear_negocio_con_producto()

        # El producto se ve en el marketplace y en la tienda del negocio
        self.assertContains(self.compradora.get(reverse("marketplace")), "Torta de chocolate")
        self.assertContains(self.compradora.get(reverse("tienda_negocio", args=[self.negocio.slug])),
                            "Torta de chocolate")

        # Compra: carrito sin cuenta, luego registro y datos de envío
        self.compradora.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 2})
        compradora = registrar_persona(self.compradora, "laura@correo.co", "Laura", "Gómez")
        self.assertEqual(self.compradora.session["carrito"], {str(self.producto.pk): 2})  # sobrevive al registro
        respuesta = self.compradora.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        pedido = Pedido.objects.get(comprador=compradora)
        self.assertRedirects(respuesta, reverse("pedido_detalle", args=[pedido.pk]), fetch_redirect_response=False)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3, "La reserva descuenta el stock")

        # Pago: va a Wompi y vuelve; el servidor consulta y Wompi (simulado) responde aprobado
        respuesta = self.compradora.post(reverse("pedido_pagar", args=[pedido.pk]))
        self.assertTrue(respuesta.url.startswith("https://checkout.wompi.co/p/"))
        self.assertNotIn("test_integrity", respuesta.url, "El secreto nunca viaja al navegador")
        buscar.return_value = transaccion_aprobada(pedido)
        detalle = self.compradora.get(reverse("pedido_detalle", args=[pedido.pk]))
        self.assertContains(detalle, "Gracias por tu compra")

        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, Pedido.Estado.PAGADO)
        factura = Factura.objects.get(pedido=pedido)
        self.assertEqual(factura.total, pedido.total, "La factura cobra lo mismo que se pagó")
        self.assertEqual(MovimientoInventario.objects.filter(producto=self.producto, tipo="salida").count(), 1)

        # La compra queda verificada para opinar
        self.compradora.post(reverse("comentar", args=[self.producto.pk]),
                             {"calificacion": 5, "texto": "¡Deliciosa!"})
        self.assertContains(self.compradora.get(reverse("tienda_producto", args=[self.producto.pk])),
                            "Compra verificada")

        # La dueña ve el pedido y lo despacha
        self.assertContains(self.duena.get(reverse("pedidos_panel_lista")), "Laura")
        self.duena.post(reverse("pedidos_panel_detalle", args=[pedido.pk]), {
            "accion": "actualizar_envio", "estado_envio": "enviado", "transportadora": "Servientrega",
            "numero_guia": "SG123",
        })
        pedido.refresh_from_db()
        self.assertEqual((pedido.estado_envio, pedido.numero_guia), ("enviado", "SG123"))

        # Una persona ajena no ve el pedido ni puede pagarlo
        intrusa = Client()
        registrar_persona(intrusa, "intrusa@correo.co")
        self.assertEqual(intrusa.get(reverse("pedido_detalle", args=[pedido.pk])).status_code, 404)
        self.assertEqual(intrusa.post(reverse("pedido_pagar", args=[pedido.pk])).status_code, 404)


class ParticionesYLimitesTests(TestCase):
    """Valores válidos, inválidos y en el borde, sin mirar el código."""

    def setUp(self):
        self.duena = Client()
        registrar_persona(self.duena, "duena@negocio.co")
        self.duena.post(reverse("negocio_registrar"), {
            "nombre": "Panadería Límite", "nit": "900111222", "email": "", "telefono": "6011111111",
            "direccion": "Calle 1 # 1-1",
        })
        self.negocio = Empresa.objects.get(nit="900111222")
        conectar_pruebas(self.negocio)
        self.producto = Producto.objects.create(empresa=self.negocio, codigo="P1", nombre="Pan",
                                                precio=Decimal("1000"), stock=3, publicado=True)

    def test_cantidad_en_el_carrito(self):
        casos = {"-1": 1, "0": 1, "1": 1, "3": 3, "4": 3, "abc": 1, "": 1}   # se ajusta a 1..stock
        for pedida, esperado in casos.items():
            cliente = Client()
            cliente.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": pedida})
            self.assertEqual(cliente.session.get("carrito", {}).get(str(self.producto.pk)), esperado, pedida)

    def test_precio_del_producto(self):
        for precio, valido in (("-1", False), ("0", True), ("0.01", True), ("abc", False),
                               ("9999999999.99", True), ("99999999999", False)):
            respuesta = self.duena.post(reverse("productos_crear"), {
                "codigo": f"C{precio}", "nombre": "Prueba", "precio": precio, "iva_porcentaje": "0",
                "stock_minimo": "0", "peso_gramos": "0",
            })
            creado = Producto.objects.filter(empresa=self.negocio, codigo=f"C{precio}").exists()
            self.assertEqual(creado, valido, f"precio={precio} → {respuesta.status_code}")

    def test_codigo_de_producto_repetido_en_el_mismo_negocio(self):
        datos = {"codigo": "P1", "nombre": "Otro", "precio": "10", "iva_porcentaje": "0",
                 "stock_minimo": "0", "peso_gramos": "0"}
        self.assertEqual(self.duena.post(reverse("productos_crear"), datos).status_code, 200)
        self.assertEqual(Producto.objects.filter(empresa=self.negocio, codigo="P1").count(), 1)

    def test_datos_de_envio_invalidos_no_crean_pedido(self):
        compradora = Client()
        registrar_persona(compradora, "c@correo.co")
        compradora.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 1})
        for campo, valor in (("email", "no-es-correo"), ("telefono", ""), ("direccion", ""), ("nombre", "")):
            datos = {**DATOS_ENVIO, campo: valor}
            respuesta = compradora.post(reverse("checkout", args=[self.negocio.slug]), datos)
            self.assertEqual(respuesta.status_code, 200, campo)
        self.assertFalse(Pedido.objects.exists())

    def test_no_compra_mas_de_lo_que_hay(self):
        compradora = Client()
        registrar_persona(compradora, "c2@correo.co")
        compradora.post(reverse("carrito_agregar", args=[self.producto.pk]), {"cantidad": 3})
        Producto.objects.filter(pk=self.producto.pk).update(stock=1)   # otra persona compró mientras tanto
        respuesta = compradora.post(reverse("checkout", args=[self.negocio.slug]), DATOS_ENVIO)
        self.assertRedirects(respuesta, reverse("carrito"), fetch_redirect_response=False)
        self.assertFalse(Pedido.objects.exists())


class RecorridoCajaPOSTests(TestCase):
    def setUp(self):
        self.cajera = Client()
        registrar_persona(self.cajera, "cajera@negocio.co")
        self.cajera.post(reverse("negocio_registrar"), {
            "nombre": "Panadería Caja", "nit": "900333444", "email": "", "telefono": "6012222222",
            "direccion": "Calle 2 # 2-2",
        })
        self.negocio = Empresa.objects.get(nit="900333444")
        self.producto = Producto.objects.create(empresa=self.negocio, codigo="PB", nombre="Pan de bono",
                                                precio=Decimal("2000"), iva_porcentaje=0, stock=10)

    def vender(self, cantidad, recibido):
        return self.cajera.post(reverse("pos_vender"), json.dumps({
            "lineas": [{"producto": str(self.producto.pk), "cantidad": cantidad}],
            "pagos": [{"metodo": "efectivo", "recibido": str(recibido)}],
        }), content_type="application/json")

    def test_abrir_vender_y_cerrar_con_arqueo(self):
        self.cajera.post(reverse("pos_abrir"), {"base": "50000"})
        venta = self.vender(3, 10000).json()
        self.assertTrue(venta["ok"])
        self.assertEqual(Decimal(venta["cambio"]), Decimal("4000"))
        self.assertEqual(self.cajera.get(venta["ticket"]).status_code, 200)

        for cantidad, recibido in ((0, 100), (-1, 100), (11, 999999), (1, 500)):   # límites e inválidos
            self.assertFalse(self.vender(cantidad, recibido).json()["ok"], (cantidad, recibido))

        self.cajera.post(reverse("pos_cerrar"), {"contado": "55000", "observaciones": "Faltan mil"})
        turno = TurnoCaja.objects.get(empresa=self.negocio)
        self.assertEqual((turno.efectivo_esperado, turno.diferencia), (Decimal("56000"), Decimal("-1000")))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 7)


class RecorridoPQRSTests(TestCase):
    @mock.patch("core.pagos.buscar_transaccion_por_referencia", return_value=None)
    def test_comprador_radica_negocio_responde_y_comprador_califica(self, _):
        duena = Client()
        registrar_persona(duena, "duena@pqrs.co")
        duena.post(reverse("negocio_registrar"), {
            "nombre": "Panadería PQRS", "nit": "900555666", "email": "", "telefono": "6013333333",
            "direccion": "Calle 3 # 3-3",
        })
        negocio = Empresa.objects.get(nit="900555666")
        compradora = Client()
        registrar_persona(compradora, "queja@correo.co")
        respuesta = compradora.post(reverse("pqrs_radicar"), {
            "tipo": PQRS.Tipo.RECLAMO, "empresa": negocio.pk, "asunto": "Pan frío",
            "descripcion": "Llegó frío y aplastado",
        })
        pqrs = PQRS.objects.get()
        self.assertTrue(re.fullmatch(r"PQRS-\d{4}-\d{5}", pqrs.radicado))
        self.assertRedirects(respuesta, reverse("pqrs_detalle", args=[pqrs.pk]), fetch_redirect_response=False)

        duena.post(reverse("panel_pqrs_detalle", args=[pqrs.pk]),
                   {"accion": "mensaje", "texto": "Te reponemos el pedido mañana"})
        self.assertContains(compradora.get(reverse("pqrs_detalle", args=[pqrs.pk])), "Te reponemos")
        compradora.post(reverse("pqrs_detalle", args=[pqrs.pk]),
                        {"accion": "encuesta", "calificacion": 5, "comentario_satisfaccion": "Bien"})
        pqrs.refresh_from_db()
        self.assertEqual((pqrs.estado, pqrs.calificacion), (PQRS.Estado.CERRADA, 5))


class RecorridoConsolaTests(TestCase):
    def test_entrar_con_2fa_y_operar(self):
        Usuario.objects.create_user(username="dev@intersoft.co", email="dev@intersoft.co", password=CLAVE,
                                    is_staff=True)
        RolPlataforma.objects.create(usuario=Usuario.objects.get(email="dev@intersoft.co"),
                                     rol=RolPlataforma.Rol.DUENO, activo=True)
        cliente = Client()
        self.assertRedirects(cliente.get(reverse("plataforma_inicio")),
                             f"{reverse('login')}?next=/plataforma/", fetch_redirect_response=False)
        cliente.post(reverse("login"), {"username": "dev@intersoft.co", "password": CLAVE})
        # Primera vez: activar el 2FA con un código real calculado desde la clave mostrada
        self.assertRedirects(cliente.get(reverse("plataforma_inicio")), reverse("plataforma_totp"),
                             fetch_redirect_response=False)
        cliente.get(reverse("plataforma_totp"))
        secreto = cliente.session["plataforma_totp_setup"]
        self.assertEqual(cliente.post(reverse("plataforma_totp"), {"codigo": "000000"}).status_code, 200)
        cliente.post(reverse("plataforma_totp"), {"codigo": codigo_totp_actual(secreto)})
        self.assertEqual(cliente.get(reverse("plataforma_inicio")).status_code, 200)
        self.assertEqual(cliente.get(reverse("plataforma_operacion")).status_code, 200)
        respuesta = cliente.post(reverse("plataforma_operacion"),
                                 {"accion": "ejecutar_tarea", "tarea": "liberar_reservas"}, follow=True)
        self.assertContains(respuesta, "terminó")


class SeguridadDesdeAfueraTests(TestCase):
    def setUp(self):
        cache.clear()
        self.duena = Client()
        registrar_persona(self.duena, "duena@seguro.co")
        self.duena.post(reverse("negocio_registrar"), {
            "nombre": "Negocio Seguro", "nit": "900777888", "email": "", "telefono": "6014444444",
            "direccion": "Calle 4 # 4-4",
        })
        self.negocio = Empresa.objects.get(nit="900777888")

    def test_sin_sesion_no_entra_al_panel_ni_a_la_consola(self):
        anonimo = Client()
        for ruta in ("dashboard", "productos_lista", "facturas_lista", "pos", "plataforma_inicio"):
            self.assertEqual(anonimo.get(reverse(ruta)).status_code, 302, ruta)

    def test_un_negocio_no_ve_datos_de_otro(self):
        producto = Producto.objects.create(empresa=self.negocio, codigo="S1", nombre="Secreto", precio=1)
        otro = Client()
        registrar_persona(otro, "otro@negocio.co")
        otro.post(reverse("negocio_registrar"), {"nombre": "Otro", "nit": "900999000", "email": "",
                                                 "telefono": "6015555555", "direccion": "Calle 5 # 5-5"})
        for ruta in ("productos_editar", "productos_kardex", "productos_movimiento"):
            self.assertEqual(otro.get(reverse(ruta, args=[producto.pk])).status_code, 404, ruta)
        self.assertNotContains(otro.get(reverse("productos_lista")), "Secreto")

    def test_csrf_obligatorio(self):
        estricto = Client(enforce_csrf_checks=True)
        self.assertEqual(estricto.post(reverse("login"), {"username": "x", "password": "y"}).status_code, 403)
        estricto.force_login(Usuario.objects.get(email="duena@seguro.co"))
        self.assertEqual(estricto.post(reverse("categorias_crear"), {"nombre": "X"}).status_code, 403)

    def test_html_malicioso_se_muestra_como_texto(self):
        self.duena.post(reverse("productos_crear"), {
            "codigo": "XSS", "nombre": "<script>alert(1)</script>", "precio": "10", "iva_porcentaje": "0",
            "stock_minimo": "0", "peso_gramos": "0", "publicado": "on",
        })
        html = self.duena.get(reverse("productos_lista")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_no_redirige_a_sitios_externos_al_entrar(self):
        anonimo = Client()
        respuesta = anonimo.post(f"{reverse('login')}?next=https://malicioso.example/robar",
                                 {"username": "duena@seguro.co", "password": CLAVE,
                                  "next": "https://malicioso.example/robar"})
        self.assertNotIn("malicioso.example", respuesta.get("Location", ""))

    def test_cabeceras_de_seguridad(self):
        respuesta = Client().get(reverse("marketplace"))
        self.assertIn("Content-Security-Policy", respuesta.headers)
        self.assertNotIn("'unsafe-inline'", respuesta.headers["Content-Security-Policy"].split("script-src")[1].split(";")[0])
        self.assertEqual(respuesta.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(respuesta.headers.get("X-Content-Type-Options"), "nosniff")

    def test_bloqueo_tras_intentos_fallidos_de_ingreso(self):
        atacante = Client()
        for _ in range(5):
            atacante.post(reverse("login"), {"username": "duena@seguro.co", "password": "mala"})
        respuesta = atacante.post(reverse("login"), {"username": "duena@seguro.co", "password": CLAVE})
        self.assertNotIn("_auth_user_id", atacante.session, "Tras 5 fallos ni la clave correcta entra")
        self.assertIn(respuesta.status_code, (403, 429, 200))

    @override_settings(RATELIMIT_ACTIVO=True)
    def test_limite_de_registro_funciona_desde_una_misma_ip(self):
        cliente = Client()
        codigos = [cliente.post(reverse("registro"), {"email": f"r{i}@x.co"}).status_code for i in range(12)]
        self.assertIn(429, codigos)

    # Corregido QA-01: antes confiaba en X-Forwarded-For enviado por el cliente
    @override_settings(RATELIMIT_ACTIVO=True)
    def test_limite_no_se_evade_cambiando_x_forwarded_for(self):
        cliente = Client()
        codigos = [
            cliente.post(reverse("registro"), {"email": f"r{i}@x.co"},
                         HTTP_X_FORWARDED_FOR=f"203.0.113.{i}").status_code
            for i in range(12)
        ]
        self.assertIn(429, codigos)

    # Corregido QA-02: la regla apuntaba a /registrar-negocio/ y la ruta real es /negocio/registrar/
    @override_settings(RATELIMIT_ACTIVO=True)
    def test_registrar_negocios_tiene_limite(self):
        codigos = [self.duena.post(reverse("negocio_registrar"), {"nombre": f"N{i}"}).status_code for i in range(12)]
        self.assertIn(429, codigos)
