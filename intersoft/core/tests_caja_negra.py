"""Pruebas de CAJA NEGRA por técnica (26 de noviembre de 2026).

Solo usan HTTP, como lo haría una persona en el navegador: llenan formularios y miran la respuesta. No llaman
funciones internas. Cada prueba indica su técnica:

- PE: partición de equivalencia (una clase válida y varias inválidas por campo).
- VL: valores límite (justo en el límite, uno antes y uno después).
- FP: flujo positivo (el camino feliz de principio a fin).
- FN: flujo negativo (lo que el sistema debe impedir).

Casos de uso: registrar usuario, registrar empresa, registrar producto, iniciar sesión y acceso al panel.
El informe con los resultados está en docs/calidad/2026-11-26-pruebas-caja-negra-tecnicas.md."""
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from core.models import Empresa, Producto, Usuario

CLAVE = "Clave#Segura2026"


def registro(**cambios):
    """Datos válidos del formulario de registro de usuario, con los cambios indicados."""
    datos = {"first_name": "Ana", "last_name": "Ruiz", "email": "ana@correo.co", "password1": CLAVE,
             "password2": CLAVE, "acepta_datos": "on", "mayor_edad": "on"}
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not None}  # None = el campo no se envía


def negocio(**cambios):
    """Datos válidos del formulario de registro de empresa."""
    datos = {"nombre": "Pastelería Dulce", "nit": "900123456-7", "email": "", "telefono": "6011234567",
             "direccion": "Calle 10 # 5-20"}
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not None}


def producto(**cambios):
    """Datos válidos del formulario de producto."""
    datos = {"codigo": "TOR-1", "nombre": "Torta de fresa", "precio": "50000", "iva_porcentaje": "19",
             "stock_minimo": "0", "stock_inicial": "0", "peso_gramos": "0", "descripcion": ""}
    datos.update(cambios)
    return {k: v for k, v in datos.items() if v is not None}


def imagen_png(tamano_bytes=None):
    """Una imagen PNG real; si se pide un tamaño, se rellena hasta ese número de bytes."""
    salida = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(salida, format="PNG")
    contenido = salida.getvalue()
    if tamano_bytes:
        contenido += b"\0" * (tamano_bytes - len(contenido))
    return SimpleUploadedFile("foto.png", contenido, content_type="image/png")


class Base(TestCase):
    """Utilidades comunes: enviar un formulario y saber si fue aceptado o qué campos rechazó."""

    def enviar(self, cliente, url, datos):
        """Envía el formulario. Devuelve (aceptado, campos_con_error)."""
        respuesta = cliente.post(url, datos)
        if respuesta.status_code == 302:
            return True, set()
        self.assertEqual(respuesta.status_code, 200, respuesta.content[:300])
        form = respuesta.context["form"]
        return False, set(form.errors)

    def assertAcepta(self, cliente, url, datos, caso):
        aceptado, errores = self.enviar(cliente, url, datos)
        self.assertTrue(aceptado, f"{caso}: debía aceptarse y rechazó {errores}")

    def assertRechaza(self, cliente, url, datos, campo, caso):
        aceptado, errores = self.enviar(cliente, url, datos)
        self.assertFalse(aceptado, f"{caso}: debía rechazarse y se aceptó")
        self.assertIn(campo, errores, f"{caso}: se rechazó, pero no por «{campo}» sino por {errores}")


# ======================================================================================
# 1. Registrar usuario  (/registro/)
# ======================================================================================
class RegistroUsuarioCajaNegraTests(Base):
    url = reverse("registro")

    def caso(self, campo, valor, valido, nombre):
        """Ejecuta un caso en un cliente nuevo y con un correo nuevo, para que sean independientes."""
        correo = f"u{Usuario.objects.count()}{len(nombre)}@correo.co"
        cambios = {"email": correo, campo: valor}
        if campo in ("password1",):
            cambios["password2"] = valor
        datos = registro(**cambios)
        if valido:
            self.assertAcepta(Client(), self.url, datos, nombre)
        else:
            self.assertRechaza(Client(), self.url, datos, "password2" if campo == "password1" else campo, nombre)

    # ---- Nombres y apellidos ----
    def test_pe_nombres_y_apellidos(self):
        clases = [
            ("Ana María", True, "PE1 válida: letras con tilde y espacio"),
            ("José Ñañez", True, "PE2 válida: ñ"),
            ("", False, "PE3 inválida: vacío"),
            ("   ", False, "PE4 inválida: solo espacios"),
            ("Ana1", False, "PE5 inválida: con números"),
            ("@", False, "PE6 inválida: solo símbolo"),
            ("Ana-Ruiz", False, "PE7 inválida: con guion"),
            ("Ana_", False, "PE8 inválida: con guion bajo"),
        ]
        for campo in ("first_name", "last_name"):
            for valor, valido, nombre in clases:
                with self.subTest(campo=campo, caso=nombre):
                    self.caso(campo, valor, valido, f"{campo} {nombre}")

    def test_vl_nombres_y_apellidos(self):
        for campo in ("first_name", "last_name"):
            for largo, valido in ((1, True), (2, True), (149, True), (150, True), (151, False)):
                with self.subTest(campo=campo, largo=largo):
                    self.caso(campo, "a" * largo, valido, f"VL {campo} de {largo} caracteres")

    # ---- Correo ----
    def test_pe_correo(self):
        clases = [
            ("ana.ruiz@correo.com.co", True, "PE1 válida: formato correcto"),
            ("", False, "PE2 inválida: vacío"),
            ("ana.correo.co", False, "PE3 inválida: sin @"),
            ("ana@correo", False, "PE4 inválida: dominio sin punto"),
            ("ana @correo.co", False, "PE5 inválida: con espacio"),
            ("@correo.co", False, "PE6 inválida: sin usuario"),
        ]
        for valor, valido, nombre in clases:
            with self.subTest(caso=nombre):
                datos = registro(email=valor)
                if valido:
                    self.assertAcepta(Client(), self.url, datos, nombre)
                else:
                    self.assertRechaza(Client(), self.url, datos, "email", nombre)

    def test_pe_correo_repetido_sin_importar_mayusculas(self):
        self.assertAcepta(Client(), self.url, registro(email="repetido@correo.co"), "primer registro")
        self.assertRechaza(Client(), self.url, registro(email="repetido@correo.co"), "email", "PE7 mismo correo")
        self.assertRechaza(Client(), self.url, registro(email="REPETIDO@Correo.co"), "email",
                           "PE8 mismo correo en mayúsculas")

    def test_vl_correo(self):
        dominio = "@correo.co"  # 10 caracteres
        casos = [
            ("a" * 64 + dominio, True, "VL 64 antes de @ (máximo)"),
            ("a" * 65 + dominio, False, "VL 65 antes de @"),
            # Cada tramo del dominio admite 63 caracteres: se arma con dos tramos para llegar a 150
            ("a" * 60 + "@" + "b" * 43 + "." + "c" * 42 + ".co", True, "VL 150 en total (máximo)"),
            ("a" * 60 + "@" + "b" * 43 + "." + "c" * 43 + ".co", False, "VL 151 en total"),
        ]
        for valor, valido, nombre in casos:
            with self.subTest(caso=nombre, largo=len(valor)):
                datos = registro(email=valor)
                if valido:
                    self.assertAcepta(Client(), self.url, datos, nombre)
                else:
                    self.assertRechaza(Client(), self.url, datos, "email", nombre)

    # ---- Contraseña ----
    def test_pe_contrasena(self):
        clases = [
            ("Torta#Fresa-2026", True, "PE1 válida: mezcla de letras, números y símbolos"),
            ("12345678901", False, "PE2 inválida: solo números"),
            ("password", False, "PE3 inválida: común en inglés"),
            ("contraseña", False, "PE4 inválida: común en español"),
            ("Colombia2026", False, "PE5 inválida: palabra común con números"),
            ("@@@@@@@@", False, "PE6 inválida: un solo carácter repetido"),
            ("abcdefgh9", False, "PE7 inválida: secuencia"),
        ]
        for valor, valido, nombre in clases:
            with self.subTest(caso=nombre):
                self.caso("password1", valor, valido, nombre)

    def test_pe_contrasena_igual_al_correo(self):
        datos = registro(email="mariposa.azul@correo.co", password1="mariposa.azul", password2="mariposa.azul")
        self.assertRechaza(Client(), self.url, datos, "password2", "PE8 inválida: parecida al correo")

    def test_pe_confirmacion_distinta(self):
        datos = registro(password2=CLAVE + "x")
        self.assertRechaza(Client(), self.url, datos, "password2", "PE inválida: la confirmación no coincide")

    def test_vl_contrasena(self):
        for largo, valido in ((7, False), (8, True), (9, True), (128, True)):
            with self.subTest(largo=largo):
                valor = ("Tq#9" * 40)[:largo]
                self.caso("password1", valor, valido, f"VL contraseña de {largo} caracteres")

    # ---- Casillas de la Ley 1581 ----
    def test_pe_casillas_obligatorias(self):
        for campo in ("acepta_datos", "mayor_edad"):
            with self.subTest(campo=campo):
                self.assertRechaza(Client(), self.url, registro(**{campo: None}), campo,
                                   f"PE inválida: «{campo}» sin marcar")

    # ---- Flujos ----
    def test_fp_registro_completo_inicia_sesion(self):
        cliente = Client()
        respuesta = cliente.post(self.url, registro())
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.get(email="ana@correo.co")
        self.assertEqual((usuario.first_name, usuario.last_name), ("Ana", "Ruiz"))
        self.assertEqual(cliente.get(reverse("mis_pedidos")).status_code, 200)  # quedó con sesión iniciada

    def test_fn_registro_invalido_no_crea_nada(self):
        antes = Usuario.objects.count()
        Client().post(self.url, registro(first_name="", password2="otra"))
        self.assertEqual(Usuario.objects.count(), antes)


# ======================================================================================
# 2. Iniciar sesión y acceso
# ======================================================================================
class SesionCajaNegraTests(Base):
    def setUp(self):
        Client().post(reverse("registro"), registro())

    def ingresar(self, correo, clave):
        """Intenta iniciar sesión y dice si lo logró."""
        cliente = Client()
        cliente.post(reverse("login"), {"username": correo, "password": clave})
        return "_auth_user_id" in cliente.session

    def test_pe_inicio_de_sesion(self):
        self.assertTrue(self.ingresar("ana@correo.co", CLAVE), "PE1 válida: datos correctos")
        self.assertTrue(self.ingresar("ANA@Correo.co", CLAVE), "PE2 válida: correo en mayúsculas")
        self.assertFalse(self.ingresar("ana@correo.co", "Otra#Clave2026"), "PE3 inválida: contraseña errada")
        self.assertFalse(self.ingresar("nadie@correo.co", CLAVE), "PE4 inválida: correo no registrado")
        self.assertFalse(self.ingresar("", ""), "PE5 inválida: vacío")

    def test_fn_panel_sin_sesion_lleva_al_login(self):
        for nombre in ("dashboard", "productos_lista", "productos_crear", "mis_pedidos", "mis_datos"):
            with self.subTest(ruta=nombre):
                respuesta = Client().get(reverse(nombre))
                self.assertEqual(respuesta.status_code, 302)
                self.assertIn(reverse("login"), respuesta["Location"])

    def test_fn_redireccion_externa_tras_login_no_se_sigue(self):
        cliente = Client()
        respuesta = cliente.post(reverse("login") + "?next=https://sitio-malo.com/",
                                 {"username": "ana@correo.co", "password": CLAVE,
                                  "next": "https://sitio-malo.com/"})
        self.assertNotIn("sitio-malo.com", respuesta.get("Location", ""))


# ======================================================================================
# 3. Registrar empresa  (/negocio/registrar/)
# ======================================================================================
class RegistroEmpresaCajaNegraTests(Base):
    url = reverse("negocio_registrar")

    def setUp(self):
        self.contador = 0

    def cliente_nuevo(self):
        """Una persona nueva con sesión iniciada (cada persona puede registrar sus negocios)."""
        self.contador += 1
        cliente = Client()
        respuesta = cliente.post(reverse("registro"), registro(email=f"duena{self.contador}@correo.co"))
        self.assertEqual(respuesta.status_code, 302)
        return cliente

    def caso(self, campo, valor, valido, nombre):
        """Ejecuta un caso con un NIT único para que no choque con los otros casos."""
        cambios = {campo: valor}
        if campo != "nit":
            cambios["nit"] = f"90000{self.contador:04d}{len(nombre) % 10}"
        datos = negocio(**cambios)
        if valido:
            self.assertAcepta(self.cliente_nuevo(), self.url, datos, nombre)
        else:
            self.assertRechaza(self.cliente_nuevo(), self.url, datos, campo, nombre)

    def test_pe_nombre(self):
        for valor, valido, nombre in (
            ("Pastelería Dulce & Café", True, "PE1 válida: letras, espacios y símbolos con letras"),
            ("Tienda 24", True, "PE2 válida: con números"),
            ("", False, "PE3 inválida: vacío"),
            ("   ", False, "PE4 inválida: solo espacios"),
            ("=@", False, "PE5 inválida: solo símbolos"),
        ):
            with self.subTest(caso=nombre):
                self.caso("nombre", valor, valido, nombre)

    def test_vl_nombre(self):
        for largo, valido in ((1, True), (150, True), (151, False)):
            with self.subTest(largo=largo):
                self.caso("nombre", "a" * largo, valido, f"VL nombre de {largo}")

    def test_pe_nit(self):
        for valor, valido, nombre in (
            ("900.123.456-7", True, "PE1 válida: con puntos y guion"),
            ("900123457", True, "PE2 válida: solo números"),
            ("", False, "PE3 inválida: vacío"),
            ("=", False, "PE4 inválida: símbolo no permitido"),
            ("ABC-DEF", False, "PE5 inválida: sin números"),
            ("9001*2345", False, "PE6 inválida: con asterisco"),
        ):
            with self.subTest(caso=nombre):
                self.caso("nit", valor, valido, nombre)

    def test_pe_nit_repetido(self):
        self.assertAcepta(self.cliente_nuevo(), self.url, negocio(nit="800111222"), "primer negocio")
        self.assertRechaza(self.cliente_nuevo(), self.url, negocio(nit="800111222"), "nit", "PE7 NIT repetido")
        self.assertRechaza(self.cliente_nuevo(), self.url, negocio(nit="800.111.222"), "nit",
                           "PE8 mismo NIT escrito con puntos")

    def test_vl_nit(self):
        for largo, valido in ((1, True), (20, True), (21, False)):
            with self.subTest(largo=largo):
                self.caso("nit", ("1" * largo), valido, f"VL NIT de {largo}")

    def test_pe_correo_opcional(self):
        self.caso("email", "", True, "PE1 válida: vacío (es opcional)")
        self.caso("email", "hola@pasteleria.co", True, "PE2 válida: formato correcto")
        self.caso("email", "hola@pasteleria", False, "PE3 inválida: dominio sin punto")

    def test_pe_telefono(self):
        for valor, valido, nombre in (
            ("601 234 5678", True, "PE1 válida: con espacios"),
            ("+57 300-123-4567", True, "PE2 válida: con + al inicio y guiones"),
            ("", False, "PE3 inválida: vacío"),
            ("300ABC4567", False, "PE4 inválida: con letras"),
            ("300+1234567", False, "PE5 inválida: + en medio"),
        ):
            with self.subTest(caso=nombre):
                self.caso("telefono", valor, valido, nombre)

    def test_vl_telefono(self):
        for largo, valido in ((6, False), (7, True), (20, True), (21, False)):
            with self.subTest(largo=largo):
                self.caso("telefono", "3" * largo, valido, f"VL teléfono de {largo}")

    def test_pe_direccion(self):
        for valor, valido, nombre in (
            ("Carrera 7 # 45-10", True, "PE1 válida: vía y número"),
            ("", False, "PE2 inválida: vacía"),
            ("a", False, "PE3 inválida: un solo carácter"),
            ("Bogotá", False, "PE4 inválida: sin número"),
            ("123456", False, "PE5 inválida: sin letras"),
        ):
            with self.subTest(caso=nombre):
                self.caso("direccion", valor, valido, nombre)

    def test_vl_direccion(self):
        for largo, valido in ((5, False), (6, True), (200, True), (201, False)):
            with self.subTest(largo=largo):
                valor = ("1 Calle" + "a" * 300)[:largo]  # con número y letras: solo cambia el largo
                self.caso("direccion", valor, valido, f"VL dirección de {largo}")

    def test_fp_registro_de_empresa_deja_al_usuario_como_administrador(self):
        cliente = self.cliente_nuevo()
        self.assertEqual(cliente.post(self.url, negocio()).status_code, 302)
        empresa = Empresa.objects.get(nit="900123456-7")
        self.assertEqual(cliente.get(reverse("dashboard")).status_code, 200)
        self.assertTrue(empresa.membresias.filter(rol__es_admin=True).exists())

    def test_fn_registrar_empresa_exige_sesion(self):
        respuesta = Client().post(self.url, negocio())
        self.assertEqual(respuesta.status_code, 302)
        # Sin sesión lo lleva a crear cuenta (o ingresar) y luego vuelve al registro del negocio
        self.assertTrue(respuesta["Location"].startswith((reverse("registro"), reverse("login"))))
        self.assertIn("next=" + self.url, respuesta["Location"])
        self.assertFalse(Empresa.objects.exists())


# ======================================================================================
# 4. Registrar producto  (/panel/productos/nuevo/)
# ======================================================================================
class RegistroProductoCajaNegraTests(Base):
    url = reverse("productos_crear")

    def setUp(self):
        self.duena = Client()
        self.duena.post(reverse("registro"), registro(email="duena@correo.co"))
        self.duena.post(reverse("negocio_registrar"), negocio())
        self.empresa = Empresa.objects.get(nit="900123456-7")
        self.contador = 0

    def caso(self, campo, valor, valido, nombre):
        """Crea un producto con un código único; si el caso prueba el código, usa el valor dado."""
        self.contador += 1
        cambios = {campo: valor}
        if campo != "codigo":
            cambios["codigo"] = f"P-{self.contador}"
        datos = producto(**cambios)
        if valido:
            self.assertAcepta(self.duena, self.url, datos, nombre)
        else:
            self.assertRechaza(self.duena, self.url, datos, campo, nombre)

    def test_pe_codigo(self):
        for valor, valido, nombre in (
            ("LAP-PRO-14", True, "PE1 válida: letras, números y guion"),
            ("A.1/2_b", True, "PE2 válida: punto, barra y guion bajo"),
            ("", False, "PE3 inválida: vacío"),
            ("=", False, "PE4 inválida: «=»"),
            ("*", False, "PE5 inválida: «*»"),
            ("-P1", False, "PE6 inválida: empieza con símbolo"),
        ):
            with self.subTest(caso=nombre):
                self.caso("codigo", valor, valido, nombre)

    def test_pe_codigo_repetido_y_aislamiento_entre_negocios(self):
        self.caso("codigo", "REP-1", True, "primer producto")
        self.caso("codigo", "rep-1", False, "PE7 código repetido (en minúsculas)")
        otra = Client()
        otra.post(reverse("registro"), registro(email="otra@correo.co"))
        otra.post(reverse("negocio_registrar"), negocio(nit="811222333"))
        self.assertAcepta(otra, self.url, producto(codigo="REP-1"), "PE8 válida: mismo código en otro negocio")

    def test_vl_codigo(self):
        for largo, valido in ((1, True), (30, True), (31, False)):
            with self.subTest(largo=largo):
                self.caso("codigo", "C" * largo, valido, f"VL código de {largo}")

    def test_pe_nombre(self):
        for valor, valido, nombre in (
            ("Torta de fresa x 10", True, "PE1 válida"),
            ("", False, "PE2 inválida: vacío"),
            ("=", False, "PE3 inválida: «=»"),
            ("*", False, "PE4 inválida: «*»"),
        ):
            with self.subTest(caso=nombre):
                self.caso("nombre", valor, valido, nombre)

    def test_vl_nombre(self):
        for largo, valido in ((1, True), (150, True), (151, False)):
            with self.subTest(largo=largo):
                self.caso("nombre", "n" * largo, valido, f"VL nombre de {largo}")

    def test_vl_descripcion(self):
        for largo, valido in ((0, True), (4999, True), (5000, True), (5001, False)):
            with self.subTest(largo=largo):
                self.caso("descripcion", "d" * largo, valido, f"VL descripción de {largo}")

    def test_fn_descripcion_gigante_no_bloquea_el_servidor(self):
        """CP-15: 1 millón de caracteres se rechaza con un mensaje, sin colgarse."""
        self.caso("descripcion", "x" * 1_000_000, False, "FN descripción de 1.000.000")

    def test_pe_y_vl_precio(self):
        for valor, valido, nombre in (
            ("0", True, "VL 0 (mínimo)"),
            ("0.01", True, "VL 0,01"),
            ("-0.01", False, "VL -0,01"),
            ("9999999999.99", True, "VL máximo (12 dígitos, 2 decimales)"),
            ("10000000000", False, "VL máximo + 1"),
            ("10.555", False, "PE inválida: 3 decimales"),
            ("abc", False, "PE inválida: texto"),
            ("", False, "PE inválida: vacío"),
        ):
            with self.subTest(caso=nombre):
                self.caso("precio", valor, valido, f"precio {nombre}")

    def test_pe_y_vl_iva(self):
        for valor, valido, nombre in (
            ("0", True, "VL 0"), ("19", True, "PE válida 19"), ("100", True, "VL 100"),
            ("-0.01", False, "VL -0,01"), ("100.01", False, "VL 100,01"), ("abc", False, "PE texto"),
        ):
            with self.subTest(caso=nombre):
                self.caso("iva_porcentaje", valor, valido, f"IVA {nombre}")

    def test_vl_stock_y_peso(self):
        for campo in ("stock_inicial", "stock_minimo", "peso_gramos"):
            for valor, valido in (("-1", False), ("0", True), ("1", True)):
                with self.subTest(campo=campo, valor=valor):
                    self.caso(campo, valor, valido, f"VL {campo} = {valor}")
            with self.subTest(campo=campo, valor="2.5"):
                self.caso(campo, "2.5", False, f"PE {campo} con decimales")

    def test_pe_y_vl_imagen(self):
        limite = 5 * 1024 * 1024
        casos = [
            (imagen_png(), True, "PE válida: PNG real"),
            (imagen_png(limite), True, "VL exactamente 5 MB"),
            (imagen_png(limite + 1), False, "VL 5 MB + 1 byte"),
            (SimpleUploadedFile("falsa.png", b"esto no es una imagen", content_type="image/png"), False,
             "PE inválida: texto con extensión .png"),
            (SimpleUploadedFile("doc.pdf", b"%PDF-1.4 ...", content_type="application/pdf"), False,
             "PE inválida: PDF"),
        ]
        for archivo, valido, nombre in casos:
            with self.subTest(caso=nombre):
                self.caso("imagen", archivo, valido, f"imagen {nombre}")

    def test_fp_producto_publicado_aparece_en_el_marketplace(self):
        datos = producto(codigo="PUB-1", nombre="Torta de mora", publicado="on", stock_inicial="3")
        self.assertAcepta(self.duena, self.url, datos, "FP crear y publicar")
        creado = Producto.objects.get(empresa=self.empresa, codigo="PUB-1")
        self.assertEqual(creado.stock, 3)
        self.assertEqual(creado.precio, Decimal("50000"))
        self.assertContains(Client().get(reverse("marketplace")), "Torta de mora")

    def test_fn_producto_no_publicado_no_aparece_en_el_marketplace(self):
        self.assertAcepta(self.duena, self.url, producto(codigo="OCU-1", nombre="Receta secreta"), "crear")
        self.assertNotContains(Client().get(reverse("marketplace")), "Receta secreta")

    def test_fn_otro_negocio_no_puede_editar_mis_productos(self):
        self.assertAcepta(self.duena, self.url, producto(codigo="MIO-1"), "crear")
        mio = Producto.objects.get(empresa=self.empresa, codigo="MIO-1")
        intrusa = Client()
        intrusa.post(reverse("registro"), registro(email="intrusa@correo.co"))
        intrusa.post(reverse("negocio_registrar"), negocio(nit="822333444"))
        respuesta = intrusa.post(reverse("productos_editar", args=[mio.pk]), producto(codigo="ROBADO"))
        self.assertEqual(respuesta.status_code, 404)
        mio.refresh_from_db()
        self.assertEqual(mio.codigo, "MIO-1")

    def test_fn_comprador_sin_negocio_no_crea_productos(self):
        comprador = Client()
        comprador.post(reverse("registro"), registro(email="comprador@correo.co"))
        respuesta = comprador.post(self.url, producto(codigo="NO-1"))
        self.assertIn(respuesta.status_code, (302, 403))
        self.assertFalse(Producto.objects.filter(codigo="NO-1").exists())
