"""Pruebas adversarias de QA: fuzzing de UUIDs, borde $0 Wompi, sesión corrupta y XSS en correos."""
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from . import compras, reservas
from .models import CuponTienda, ItemCarrito, Producto, Usuario
from .negocios import registrar_negocio
from .testing_pagos import conectar_pruebas

DATOS_ENVIO = {
    "tipo_documento": "CC",
    "numero_documento": "10101010",
    "nombre": "Ana QA",
    "email": "ana-qa@ejemplo.co",
    "telefono": "3001234567",
    "departamento": "Antioquia",
    "ciudad": "Medellín",
    "direccion": "Calle 10 # 20-30",
    "indicaciones": "",
}


class QAAdversarioTests(TestCase):
    """Intenta romper el sistema con entradas maliciosas, UUIDs corruptos y casos borde financieros."""

    def setUp(self):
        self.dueno = Usuario.objects.create_user(
            username="qa-dueno@alfa.co", email="qa-dueno@alfa.co", password="Password123*", first_name="QA"
        )
        self.negocio = registrar_negocio(
            usuario=self.dueno,
            datos={
                "nombre": "QA Store",
                "nit": "900888777-1",
                "email": "qa@store.co",
                "telefono": "3007778899",
                "direccion": "Calle QA # 1-2",
            },
        )
        conectar_pruebas(self.negocio)
        self.comprador = Usuario.objects.create_user(
            username="ana-qa@ejemplo.co", email="ana-qa@ejemplo.co", password="Password123*", first_name="Ana"
        )
        self.producto = Producto.objects.create(
            empresa=self.negocio,
            codigo="QA-1",
            nombre="Producto QA",
            precio=Decimal("10000.00"),
            iva_porcentaje=Decimal("0.00"),
            stock=10,
            publicado=True,
            activo=True,
        )

    def test_uuids_corruptos_en_post_nunca_dan_500(self):
        """Enviar basura o SQLi en campos *_id por POST debe devolver 404 limpio, nunca HTTP 500."""
        self.client.force_login(self.dueno)
        url_cupones = reverse("cupones_panel")
        for malo in ("no-es-uuid", "", "' OR 1=1 --", "<script>alert(1)</script>"):
            resp_toggle = self.client.post(url_cupones, {"accion": "toggle", "cupon_id": malo})
            self.assertEqual(resp_toggle.status_code, 404)
            resp_del = self.client.post(url_cupones, {"accion": "eliminar", "cupon_id": malo})
            self.assertEqual(resp_del.status_code, 404)

    def test_cupon_no_puede_dejar_total_bajo_minimo_wompi(self):
        """Un cupón de 100% o monto mayor al pedido no puede crear un pedido impagable ($0) en Wompi."""
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="GRATIS100",
            tipo=CuponTienda.Tipo.PORCENTAJE,
            valor=Decimal("100"),
        )
        CuponTienda.objects.create(
            empresa=self.negocio,
            codigo="BAJO1500",
            tipo=CuponTienda.Tipo.FIJO,
            valor=Decimal("9000"),
        )
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.evaluar_cupon(negocio=self.negocio, codigo="GRATIS100", total_productos=Decimal("10000"))
        with self.assertRaises(compras.OperacionNoPermitida):
            compras.crear_pedido(
                usuario=self.comprador,
                negocio=self.negocio,
                lineas=[{"producto": self.producto, "cantidad": 1}],
                datos=DATOS_ENVIO,
                codigo_cupon="BAJO1500",
            )

    def test_sesion_carrito_corrupta_no_rompe_carrito_ni_login(self):
        """Claves no-UUID o cantidades inválidas en session['carrito'] se descartan sin HTTP 500."""
        cliente = Client()
        sesion = cliente.session
        sesion["carrito"] = {"basura-no-uuid": 2, str(self.producto.pk): 1}
        sesion.save()

        # Invitado ve /carrito/ sin 500 y conserva el producto válido
        resp_inv = cliente.get(reverse("carrito"))
        self.assertEqual(resp_inv.status_code, 200)
        self.assertEqual(resp_inv.context["grupos"][0]["unidades"], 1)

        # Inyecta otra clave corrupta antes de iniciar sesión -> fusión no da 500
        sesion = cliente.session
        sesion["carrito"] = {"otra-basura": "nan", str(self.producto.pk): 2}
        sesion.save()
        cliente.force_login(self.comprador)
        self.assertEqual(ItemCarrito.objects.get(usuario=self.comprador, producto=self.producto).cantidad, 2)

    def test_xss_en_transportadora_escapado_en_correo_html(self):
        """Cualquier etiqueta HTML en transportadora o guía se escapa en el correo HTML."""
        pedido = compras.crear_pedido(
            usuario=self.comprador,
            negocio=self.negocio,
            lineas=[{"producto": self.producto, "cantidad": 1}],
            datos=DATOS_ENVIO,
        )
        reservas.marcar_pagado(pedido)
        mail.outbox.clear()

        reservas.actualizar_envio_pedido(
            pedido=pedido,
            estado_envio="enviado",
            transportadora='<script>alert("xss")</script>',
            numero_guia="<b>G-1</b>",
        )
        self.assertEqual(len(mail.outbox), 1)
        html, _ = mail.outbox[0].alternatives[0]
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>G-1</b>", html)

    def test_filtros_get_corruptos_en_pqrs_tienda_y_panel_no_dan_500(self):
        """Parámetros GET maliciosos (UUID inválido, fechas imposibles, páginas basura) nunca causan 500."""
        self.client.force_login(self.comprador)
        for ruta in (
            f"{reverse('pqrs_radicar')}?pedido=no-es-uuid",
            f"{reverse('pqrs_radicar')}?pedido=' OR 1=1 --",
            f"{reverse('marketplace')}?categoria=<script>&orden=invalido&page=abc",
            f"{reverse('mis_pedidos')}?estado=invalido&page=-5",
        ):
            resp = self.client.get(ruta)
            self.assertNotEqual(resp.status_code, 500, f"HTTP 500 inesperado en {ruta}")

        self.client.force_login(self.dueno)
        for ruta in (
            f"{reverse('dashboard')}?bodega=no-es-uuid",
            f"{reverse('pedidos_panel_lista')}?estado=basura&envio=basura&page=xyz",
        ):
            resp = self.client.get(ruta)
            self.assertNotEqual(resp.status_code, 500, f"HTTP 500 inesperado en {ruta}")

    def test_limites_paginacion_marketplace_stock_minimo_telefono_y_pqrs(self):
        """Paginación fuera de rango devuelve 200, y formularios rechazan stock_minimo<0, teléfono inválido y PQRS >2000."""
        from .forms import ClienteForm, ProductoForm
        from pqrs.forms import RadicarPQRSCompradorForm

        # 1. Marketplace ?page=999999 y ?page=-5 devuelven 200 (no 404)
        self.assertEqual(self.client.get(f"{reverse('marketplace')}?page=999999").status_code, 200)
        self.assertEqual(self.client.get(f"{reverse('marketplace')}?page=-5").status_code, 200)

        # 2. ProductoForm rechaza stock_minimo negativo
        form_prod = ProductoForm(
            {
                "codigo": "NEG-1",
                "nombre": "Test",
                "precio": "10000",
                "iva_porcentaje": "19",
                "stock_inicial": "5",
                "stock_minimo": "-5",
            },
            empresa=self.negocio,
        )
        self.assertFalse(form_prod.is_valid())
        self.assertIn("stock_minimo", form_prod.errors)

        # 3. ClienteForm rechaza teléfono con letras/símbolos
        form_cli = ClienteForm(
            {
                "tipo_documento": "CC",
                "numero_documento": "12345678",
                "nombre": "Cliente QA",
                "telefono": "abc!@#123456",
            },
            empresa=self.negocio,
        )
        self.assertFalse(form_cli.is_valid())
        self.assertIn("telefono", form_cli.errors)

        # 4. RadicarPQRSCompradorForm rechaza descripción > 2000 caracteres
        form_pqrs = RadicarPQRSCompradorForm(
            {
                "tipo": "queja",
                "empresa": str(self.negocio.pk),
                "asunto": "Prueba límite",
                "descripcion": "X" * 2005,
            },
            usuario=self.comprador,
        )
        self.assertFalse(form_pqrs.is_valid())
        self.assertIn("descripcion", form_pqrs.errors)

    def test_validaciones_perfil_cliente_doc_y_nit_negocio(self):
        """PerfilUsuarioForm, ClienteForm y RegistroNegocioForm rechazan formatos inválidos."""
        from .forms import ClienteForm, PerfilUsuarioForm
        from .forms_tienda import RegistroNegocioForm

        # 1. Perfil rechaza teléfono con letras/símbolos
        form_perfil = PerfilUsuarioForm(
            {
                "first_name": "Comprador",
                "last_name": "QA",
                "telefono": "abc!!!@@@123",
            },
            instance=self.comprador,
        )
        self.assertFalse(form_perfil.is_valid())
        self.assertIn("telefono", form_perfil.errors)

        # 2. Cliente rechaza símbolos inválidos en numero_documento
        form_cli = ClienteForm(
            {
                "tipo_documento": "CC",
                "numero_documento": "DOC-INVALIDO!!!",
                "nombre": "Cliente QA",
                "telefono": "3001234567",
            },
            empresa=self.negocio,
        )
        self.assertFalse(form_cli.is_valid())
        self.assertIn("numero_documento", form_cli.errors)

        # 3. Registro de negocio rechaza NIT con símbolos o sin dígitos
        form_neg = RegistroNegocioForm(
            {
                "nombre": "Negocio QA",
                "nit": "NIT-INVALIDO!!!",
                "email": "negocio@ejemplo.co",
                "telefono": "3001234567",
                "direccion": "Calle 10 # 20-30",
            }
        )
        self.assertFalse(form_neg.is_valid())
        self.assertIn("nit", form_neg.errors)

    def test_validadores_nombres_personas_negocios_y_nit(self):
        """Registro de cuenta, perfil y negocio aceptan nombres reales y rechazan símbolos extraños o XSS."""
        from django.core.exceptions import ValidationError

        from .forms import PerfilUsuarioForm
        from .forms_tienda import RegistroCompradorForm, RegistroNegocioForm
        from .validadores import validar_nit_negocio, validar_nombre_negocio, validar_nombre_persona

        # Nombres reales de persona (incluye tildes, ñ, guion, apóstrofe, abreviatura)
        for valido in (
            "María José",
            "Ángel Ñáñez",
            "Ana-María",
            "Jean-Luc Pérez-Gómez",
            "O'Connor",
            "D’Angelo",
            "Ma. Fernanda",
            "Carlos Jr.",
            "De la Cruz",
        ):
            self.assertEqual(validar_nombre_persona(valido), valido)

        # Nombres inválidos de persona (números, XSS, símbolos raros, bordes)
        for invalido in (
            "QA <script>window.__xss=1</script>",
            "Juan123",
            "Juan--Carlos",
            "-Juan",
            "Juan-",
            "---",
            "Juan@mail.com",
            "Juan!!!",
            "😀🔥",
        ):
            with self.assertRaises(ValidationError, msg=f"Debió rechazar persona: {invalido}"):
                validar_nombre_persona(invalido)

        # Nombres reales de negocio (guion, S.A.S., &, apóstrofe, coma, números)
        for valido in (
            "mi-empresa",
            "Inversiones El Sol S.A.S.",
            "Café & Pan",
            "H&M",
            "Gómez, Pérez & Cía.",
            "McDonald's",
            "Ferretería 365",
            "7-Eleven",
            "Dr. Mueble",
        ):
            self.assertEqual(validar_nombre_negocio(valido), valido)

        # Nombres inválidos de negocio
        for invalido in (
            "Tienda <script>alert(1)</script>",
            "Tienda!!!",
            "mi--empresa",
            "-mi-empresa",
            "mi-empresa-",
            "---",
            "Mi_Empresa$100",
            "Empresa @gmail",
        ):
            with self.assertRaises(ValidationError, msg=f"Debió rechazar negocio: {invalido}"):
                validar_nombre_negocio(invalido)

        # NIT colombiano válido vs inválido
        self.assertEqual(validar_nit_negocio("900.123.456-7"), "900123456-7")
        self.assertEqual(validar_nit_negocio("901998877"), "901998877")
        for nit_malo in ("NIT-INVALIDO!!!", "ABC-123", "900--123", "-900123", "900123-"):
            with self.assertRaises(ValidationError, msg=f"Debió rechazar NIT: {nit_malo}"):
                validar_nit_negocio(nit_malo)

        # Integración en formularios reales
        form_reg = RegistroCompradorForm(
            {
                "first_name": "QA <script>alert(1)</script>",
                "last_name": "Pérez123",
                "email": "nuevo.qa@ejemplo.co",
                "password1": "ClaveSegura2026!",
                "password2": "ClaveSegura2026!",
                "acepta_datos": True,
                "mayor_edad": True,
            }
        )
        self.assertFalse(form_reg.is_valid())
        self.assertIn("first_name", form_reg.errors)
        self.assertIn("last_name", form_reg.errors)

        form_perfil = PerfilUsuarioForm(
            {"first_name": "Ana-María", "last_name": "O'Connor", "telefono": "300 123 4567"},
            instance=self.comprador,
        )
        self.assertTrue(form_perfil.is_valid(), form_perfil.errors)

        form_neg_ok = RegistroNegocioForm(
            {
                "nombre": "mi-empresa S.A.S.",
                "nit": "901.555.444-2",
                "email": "hola@mi-empresa.co",
                "telefono": "3001234567",
                "direccion": "Calle 10 # 20-30",
            }
        )
        self.assertTrue(form_neg_ok.is_valid(), form_neg_ok.errors)

        form_neg_mal = RegistroNegocioForm(
            {
                "nombre": "mi_empresa!!!",
                "nit": "901.555.444-2",
                "email": "hola@mi-empresa.co",
                "telefono": "3001234567",
                "direccion": "Calle 10 # 20-30",
            }
        )
        self.assertFalse(form_neg_mal.is_valid())
        self.assertIn("nombre", form_neg_mal.errors)
