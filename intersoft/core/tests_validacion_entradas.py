"""Regresión del informe de pruebas de validación de datos de entrada (25 de noviembre de 2026).

Cada clase corresponde a un caso que no cumplía (CP-02, 04, 08, 09, 12, 13, 14 y 15)."""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase

from .forms import PerfilUsuarioForm, ProductoForm
from .forms_equipo import MiembroCrearForm
from .forms_tienda import RegistroCompradorForm, RegistroNegocioForm
from .models import Empresa, Rol, Usuario

CLAVE = "Clave#Segura2026"


def datos_negocio(**extra):
    """Datos válidos del registro de negocio."""
    return {"nombre": "Pastelería Dulce", "nit": "900123456-7", "email": "", "telefono": "6011234567",
            "direccion": "Calle 10 # 5-20", **extra}


class CP02ApellidosTests(TestCase):
    def test_registro_exige_apellidos(self):
        for apellido in ("", "   "):
            form = RegistroCompradorForm({"first_name": "Ana", "last_name": apellido, "email": "a@x.co",
                                          "password1": CLAVE, "password2": CLAVE, "acepta_datos": "on",
                                          "mayor_edad": "on"})
            self.assertIn("last_name", form.errors)

    def test_crear_miembro_nuevo_exige_nombres_y_apellidos(self):
        empresa = Empresa.objects.create(nombre="Tienda", nit="900000001", slug="tienda")
        rol = Rol.objects.create(empresa=empresa, nombre="Vendedor")
        form = MiembroCrearForm({"email": "nuevo@x.co", "first_name": "", "last_name": " ", "rol": rol.pk,
                                 "password": CLAVE}, empresa=empresa)
        self.assertFalse(form.is_valid())
        self.assertIn("first_name", form.errors)
        self.assertIn("last_name", form.errors)

    def test_perfil_no_deja_borrar_los_apellidos(self):
        usuario = Usuario.objects.create_user(username="u@x.co", email="u@x.co", password=CLAVE, first_name="Ana", last_name="Prueba")
        form = PerfilUsuarioForm({"first_name": "Ana", "last_name": "  "}, instance=usuario)
        self.assertIn("last_name", form.errors)


class CP04ContrasenaTests(SimpleTestCase):
    def test_rechaza_contrasenas_comunes_repetidas_y_secuencias(self):
        for clave in ("contraseña", "Contrasena2026!", "Colombia2026", "intersoft1", "@@@@@@@@", "aaaaaaaa",
                      "abcdefgh1", "12345678", "password", "qwerty123"):
            with self.subTest(clave=clave), self.assertRaises(ValidationError):
                validate_password(clave)

    def test_acepta_una_contrasena_segura(self):
        validate_password("Torta#Fresa-2026")


class CP08CP09CP12EmpresaTests(TestCase):
    def errores(self, **extra):
        """Errores del formulario de registro de negocio con los datos indicados."""
        form = RegistroNegocioForm(datos_negocio(**extra))
        form.is_valid()
        return form.errors

    def test_datos_validos(self):
        self.assertEqual(self.errores(), {})

    def test_nombre_solo_simbolos(self):
        for nombre in ("=@", "***", "="):
            self.assertIn("nombre", self.errores(nombre=nombre))

    def test_nit_con_simbolos(self):
        for nit in ("=", "90012=3456", "abc*"):
            self.assertIn("nit", self.errores(nit=nit))

    def test_nit_con_guion_y_puntos_es_valido(self):
        self.assertNotIn("nit", self.errores(nit="900.123.456-7"))

    def test_direccion_incompleta(self):
        for direccion in ("a", "casa", "123", "=@#$%&"):
            self.assertIn("direccion", self.errores(direccion=direccion))


class CP13CP14CP15ProductoTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nombre="Tienda", nit="900000002", slug="tienda-2")

    def errores(self, **extra):
        """Errores del formulario de producto con los datos indicados."""
        datos = {"codigo": "P-001", "nombre": "Torta de fresa", "precio": "10000", "iva_porcentaje": "19",
                 "stock_minimo": "0", "stock_inicial": "0", "descripcion": "", **extra}
        form = ProductoForm(datos, empresa=self.empresa)
        form.instance.empresa = self.empresa
        form.is_valid()
        return form.errors

    def test_datos_validos(self):
        self.assertEqual(self.errores(), {})

    def test_codigo_con_simbolos(self):
        for codigo in ("=", "*", "P*1", "-P1"):
            self.assertIn("codigo", self.errores(codigo=codigo))

    def test_codigos_normales_son_validos(self):
        for codigo in ("LAP-PRO-14", "TEC_01", "A.1/2", "X"):
            self.assertNotIn("codigo", self.errores(codigo=codigo))

    def test_nombre_solo_simbolos(self):
        for nombre in ("=", "*", "=*"):
            self.assertIn("nombre", self.errores(nombre=nombre))

    def test_descripcion_tiene_limite_en_el_navegador_y_en_el_servidor(self):
        form = ProductoForm(empresa=self.empresa)
        self.assertEqual(form.fields["descripcion"].widget.attrs.get("maxlength"), "5000")
        self.assertIn('maxlength="5000"', str(form["descripcion"]))
        self.assertIn("descripcion", self.errores(descripcion="x" * 5001))
        self.assertNotIn("descripcion", self.errores(descripcion="x" * 5000))


class NombresDePersonaTests(TestCase):
    """Nombres y apellidos de personas: solo letras y espacios, sin números ni caracteres especiales."""

    INVALIDOS = ("@", "Ana1", "Ana-María", "O'Neil", "Ana_", "=", "Ana.", "*Luis")
    VALIDOS = ("Ana María", "José Ñañez", "Müller")

    def registro(self, nombre, apellido):
        """Formulario de registro con el nombre y apellido indicados."""
        return RegistroCompradorForm({"first_name": nombre, "last_name": apellido, "email": "a@x.co",
                                      "password1": CLAVE, "password2": CLAVE, "acepta_datos": "on",
                                      "mayor_edad": "on"})

    def test_registro_rechaza_caracteres_especiales(self):
        for texto in self.INVALIDOS:
            with self.subTest(texto=texto):
                errores = self.registro(texto, texto).errors
                self.assertIn("first_name", errores)
                self.assertIn("last_name", errores)

    def test_registro_acepta_letras_con_tildes(self):
        for texto in self.VALIDOS:
            with self.subTest(texto=texto):
                self.assertTrue(self.registro(texto, texto).is_valid())

    def test_perfil_y_equipo_rechazan_caracteres_especiales(self):
        usuario = Usuario.objects.create_user(username="u@x.co", email="u@x.co", password=CLAVE, first_name="Ana", last_name="Prueba")
        perfil = PerfilUsuarioForm({"first_name": "Ana@", "last_name": "Ruiz1"}, instance=usuario)
        self.assertIn("first_name", perfil.errors)
        self.assertIn("last_name", perfil.errors)
        empresa = Empresa.objects.create(nombre="Tienda", nit="900000003", slug="tienda-3")
        rol = Rol.objects.create(empresa=empresa, nombre="Vendedor")
        equipo = MiembroCrearForm({"email": "n@x.co", "first_name": "L=uis", "last_name": "Pérez*", "rol": rol.pk,
                                   "password": CLAVE}, empresa=empresa)
        self.assertIn("first_name", equipo.errors)
        self.assertIn("last_name", equipo.errors)

    def test_nombre_del_comprador_al_pagar(self):
        from .forms_tienda import DatosEnvioForm

        self.assertIn("nombre", DatosEnvioForm({"nombre": "Ana @Ruiz"}).errors)
        self.assertNotIn("nombre", DatosEnvioForm({"nombre": "Ana Ruiz"}).errors)


class NombresNoNulosNiVaciosTests(TestCase):
    """Nombres y apellidos not null y not blank, también en la base de datos (no solo en los formularios)."""

    def test_la_base_de_datos_rechaza_nombres_vacios_o_solo_espacios(self):
        from django.db import IntegrityError, transaction

        for nombre, apellido in (("", "Ruiz"), ("Ana", ""), ("   ", "Ruiz"), ("Ana", "  ")):
            with self.subTest(nombre=nombre, apellido=apellido), self.assertRaises(IntegrityError), \
                    transaction.atomic():
                Usuario.objects.create_user(username=f"{nombre}{apellido}@x.co", email=f"v{len(nombre)}@x.co",
                                            password=CLAVE, first_name=nombre, last_name=apellido)

    def test_el_modelo_exige_nombres_y_apellidos(self):
        usuario = Usuario(username="m@x.co", email="m@x.co")
        with self.assertRaises(ValidationError) as error:
            usuario.full_clean(exclude=["password"])
        self.assertIn("first_name", error.exception.message_dict)
        self.assertIn("last_name", error.exception.message_dict)

    def test_createsuperuser_pide_nombres_y_apellidos(self):
        self.assertIn("first_name", Usuario.REQUIRED_FIELDS)
        self.assertIn("last_name", Usuario.REQUIRED_FIELDS)
