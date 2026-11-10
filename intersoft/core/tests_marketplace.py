import io
import tempfile
from decimal import Decimal
from unittest import mock

from django.contrib.auth import authenticate, get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .backends import EmailBackend
from .models import Empresa, Membresia, Producto, Rol
from .negocios import registrar_negocio

Usuario = get_user_model()
CLAVE = "ClaveSegura#2026"


def crear_empresa(nombre, nit, slug, activa=True):
    # Con dirección y teléfono: sin ellos el negocio no publica (Ley 1480, art. 53)
    return Empresa.objects.create(
        nombre=nombre, nit=nit, slug=slug, activa=activa, direccion="Calle 1 # 2-3", telefono="6011234567"
    )


def crear_producto(empresa, nombre, codigo="P-1", publicado=True, activo=True, stock=5):
    return Producto.objects.create(
        empresa=empresa, nombre=nombre, codigo=codigo, precio=Decimal("1000"),
        publicado=publicado, activo=activo, stock=stock,
    )


def crear_usuario(correo="ana@correo.co"):
    return Usuario.objects.create_user(username=correo, email=correo, password=CLAVE)


def datos_registro(correo="nueva@correo.co", **extra):
    return {
        "first_name": "Nueva", "last_name": "Compradora", "email": correo,
        "password1": CLAVE, "password2": CLAVE, **extra,
    }


def datos_negocio(nombre="Mi Tienda", nit="900111222"):
    return {"nombre": nombre, "nit": nit, "email": "", "telefono": "6011234567", "direccion": "Calle 1 # 2-3"}


class CatalogoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uno = crear_empresa("Panadería Uno", "111", "panaderia-uno")
        cls.dos = crear_empresa("Ferretería Dos", "222", "ferreteria-dos")
        cls.inactiva = crear_empresa("Cerrada", "333", "cerrada", activa=False)
        cls.pan = crear_producto(cls.uno, "Pan integral")
        cls.martillo = crear_producto(cls.dos, "Martillo")
        cls.borrador = crear_producto(cls.uno, "Borrador secreto", codigo="P-2", publicado=False)
        cls.eliminado = crear_producto(cls.uno, "Producto eliminado", codigo="P-3", activo=False)
        cls.de_inactiva = crear_producto(cls.inactiva, "Producto de cerrada")

    def inicio(self, **parametros):
        return self.client.get(reverse("marketplace"), parametros)

    def test_inicio_es_publico_y_muestra_varios_negocios(self):
        respuesta = self.inicio()
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Pan integral")
        self.assertContains(respuesta, "Martillo")
        self.assertContains(respuesta, "Panadería Uno")
        self.assertContains(respuesta, "Ferretería Dos")

    def test_no_muestra_sin_publicar_eliminados_ni_negocios_inactivos(self):
        respuesta = self.inicio()
        self.assertNotContains(respuesta, "Borrador secreto")
        self.assertNotContains(respuesta, "Producto eliminado")
        self.assertNotContains(respuesta, "Producto de cerrada")
        self.assertNotContains(respuesta, "Cerrada")

    def test_detalle_sin_publicar_responde_404(self):
        for producto in (self.borrador, self.eliminado, self.de_inactiva):
            with self.subTest(producto=producto.nombre):
                url = reverse("tienda_producto", args=[producto.pk])
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_detalle_publicado_responde_200(self):
        respuesta = self.client.get(reverse("tienda_producto", args=[self.pan.pk]))
        self.assertContains(respuesta, "Pan integral")

    def test_vitrina_solo_muestra_sus_productos(self):
        respuesta = self.client.get(reverse("tienda_negocio", args=["panaderia-uno"]))
        self.assertContains(respuesta, "Pan integral")
        self.assertNotContains(respuesta, "Martillo")
        self.assertNotContains(respuesta, "Borrador secreto")

    def test_vitrina_de_negocio_inactivo_o_inexistente_responde_404(self):
        for slug in ("cerrada", "no-existe"):
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get(reverse("tienda_negocio", args=[slug])).status_code, 404)

    def test_busqueda_por_producto(self):
        respuesta = self.inicio(q="martillo")
        self.assertContains(respuesta, "Martillo")
        self.assertNotContains(respuesta, "Pan integral")

    def test_busqueda_por_negocio(self):
        respuesta = self.inicio(q="panadería")
        self.assertContains(respuesta, "Pan integral")
        self.assertNotContains(respuesta, "Martillo")

    def test_busqueda_no_encuentra_productos_sin_publicar(self):
        self.assertNotContains(self.inicio(q="Borrador"), "Borrador secreto")

    def test_no_muestra_stock_exacto(self):
        producto = crear_producto(self.uno, "Azúcar", codigo="P-4", stock=7391)
        agotado = crear_producto(self.uno, "Sal", codigo="P-5", stock=0)
        for url in (reverse("marketplace"), reverse("tienda_producto", args=[producto.pk])):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertNotContains(respuesta, "7391")
                self.assertContains(respuesta, "Disponible")
        self.assertContains(self.client.get(reverse("tienda_producto", args=[agotado.pk])), "Agotado")

    def test_pagina_de_a_24(self):
        for numero in range(30):
            crear_producto(self.dos, f"Tornillo {numero}", codigo=f"T-{numero}")
        respuesta = self.inicio()
        self.assertEqual(len(respuesta.context["productos"]), 24)
        self.assertTrue(respuesta.context["page_obj"].has_next())


class RegistroCompradorTests(TestCase):
    def test_crea_usuario_sin_membresia_en_minusculas_y_con_sesion(self):
        respuesta = self.client.post(reverse("registro"), datos_registro("NUEVA@Correo.CO"))
        self.assertRedirects(respuesta, reverse("marketplace"))
        usuario = Usuario.objects.get()
        self.assertEqual(usuario.email, "nueva@correo.co")
        self.assertEqual(usuario.username, "nueva@correo.co")
        self.assertFalse(Membresia.objects.filter(usuario=usuario).exists())
        self.assertEqual(self.client.session["_auth_user_id"], str(usuario.pk))

    def test_rechaza_correo_repetido_sin_distinguir_mayusculas(self):
        crear_usuario("ana@correo.co")
        respuesta = self.client.post(reverse("registro"), datos_registro("ANA@correo.co"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("email", respuesta.context["form"].errors)
        self.assertEqual(Usuario.objects.count(), 1)

    def test_respeta_next_interno(self):
        destino = reverse("negocio_registrar")
        respuesta = self.client.post(reverse("registro"), datos_registro(next=destino))
        self.assertRedirects(respuesta, destino)

    def test_ignora_next_externo(self):
        for numero, externo in enumerate(("https://malo.example/", "//malo.example/")):
            with self.subTest(externo=externo):
                self.client.logout()
                datos = datos_registro(f"persona{numero}@correo.co", next=externo)
                respuesta = self.client.post(reverse("registro"), datos)
                self.assertRedirects(respuesta, reverse("marketplace"))

    def test_next_sin_barra_no_rompe_la_pagina(self):
        respuesta = self.client.post(reverse("registro"), datos_registro(next="algo"))
        self.assertEqual(respuesta.status_code, 302)


class RegistroNegocioTests(TestCase):
    def test_sin_sesion_lleva_a_registro_con_next(self):
        url = reverse("negocio_registrar")
        respuesta = self.client.get(url)
        self.assertRedirects(respuesta, f"{reverse('registro')}?next={url}")

    def test_recorrido_completo(self):
        self.client.post(reverse("registro"), datos_registro())
        respuesta = self.client.post(reverse("negocio_registrar"), datos_negocio("Mi Tienda", "900.111 222"))
        self.assertRedirects(respuesta, reverse("dashboard"))

        empresa = Empresa.objects.get()
        self.assertEqual(empresa.nit, "900111222")
        self.assertEqual(empresa.slug, "mi-tienda")
        membresia = Membresia.objects.get(usuario=Usuario.objects.get(), empresa=empresa)
        self.assertEqual(membresia.rol.nombre, "Administrador")
        self.assertTrue(membresia.rol.es_admin)
        self.assertEqual(self.client.session["empresa_id"], str(empresa.pk))
        self.assertEqual(self.client.get(reverse("clientes_lista")).status_code, 200)

    def test_nit_repetido_no_crea_nada(self):
        crear_empresa("Existente", "900111222", "existente")
        self.client.force_login(crear_usuario())
        respuesta = self.client.post(reverse("negocio_registrar"), datos_negocio("Otra", "900.111.222"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("nit", respuesta.context["form"].errors)
        self.assertEqual(Empresa.objects.count(), 1)
        self.assertFalse(Rol.objects.exists())
        self.assertFalse(Membresia.objects.exists())

    def test_slug_repetido_recibe_sufijo(self):
        usuario = crear_usuario()
        primera = registrar_negocio(usuario=usuario, datos=datos_negocio("La Tienda", "1"))
        segunda = registrar_negocio(usuario=crear_usuario("b@correo.co"), datos=datos_negocio("La Tienda", "2"))
        tercera = registrar_negocio(usuario=crear_usuario("c@correo.co"), datos=datos_negocio("La Tienda", "3"))
        self.assertEqual(
            [primera.slug, segunda.slug, tercera.slug],
            ["la-tienda", "la-tienda-2", "la-tienda-3"],
        )

    def test_comprador_que_abre_el_panel_va_a_registrar_su_negocio(self):
        self.client.force_login(crear_usuario())
        for nombre in ("dashboard", "clientes_lista", "facturas_lista"):
            with self.subTest(ruta=nombre):
                self.assertRedirects(self.client.get(reverse(nombre)), reverse("negocio_registrar"))

    def test_sin_sesion_el_panel_sigue_pidiendo_login(self):
        url = reverse("dashboard")
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")


class DespuesDeLoginTests(TestCase):
    def test_comprador_va_al_marketplace(self):
        self.client.force_login(crear_usuario())
        self.assertRedirects(self.client.get(reverse("despues_login")), reverse("marketplace"))

    def test_dueno_va_al_panel(self):
        usuario = crear_usuario()
        registrar_negocio(usuario=usuario, datos=datos_negocio())
        self.client.force_login(usuario)
        self.assertRedirects(self.client.get(reverse("despues_login")), reverse("dashboard"))

    def test_login_real_pasa_por_despues_login(self):
        crear_usuario()
        respuesta = self.client.post(reverse("login"), {"username": "ana@correo.co", "password": CLAVE})
        self.assertRedirects(respuesta, reverse("despues_login"), fetch_redirect_response=False)


class ProductoFormularioTests(TestCase):
    def test_checkbox_publicado_aparece_en_el_panel(self):
        usuario = crear_usuario()
        registrar_negocio(usuario=usuario, datos=datos_negocio())
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("productos_crear"))
        self.assertContains(respuesta, 'name="publicado"')
        self.assertContains(respuesta, 'type="checkbox"')

    def test_producto_nuevo_no_se_publica_solo(self):
        empresa = crear_empresa("Una", "1", "una")
        producto = Producto.objects.create(empresa=empresa, nombre="X", codigo="X", precio=1)
        self.assertFalse(producto.publicado)


class PrecioConIvaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = crear_empresa("Una", "1", "una")

    def producto(self, iva, precio="1000", codigo="P-1"):
        producto = crear_producto(self.empresa, "Arroz", codigo=codigo)
        producto.precio = Decimal(precio)
        producto.iva_porcentaje = Decimal(iva)
        producto.save()
        return producto

    def test_catalogo_y_detalle_muestran_el_precio_con_iva(self):
        producto = self.producto("19")
        for url in (reverse("marketplace"), reverse("tienda_producto", args=[producto.pk])):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertContains(respuesta, "$1.190")
                self.assertContains(respuesta, "IVA incluido")
                self.assertNotContains(respuesta, "+ IVA")

    def test_iva_cero_muestra_el_mismo_precio(self):
        self.producto("0")
        respuesta = self.client.get(reverse("marketplace"))
        self.assertContains(respuesta, "$1.000")
        self.assertNotContains(respuesta, "1.190")

    def test_redondea_hacia_arriba(self):
        producto = self.producto("1", precio="0.50")
        self.assertEqual(producto.precio_con_iva, Decimal("0.51"))


class LoginSinMayusculasTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario("ana@correo.co")

    def ingresar(self, correo, clave=CLAVE):
        return self.client.post(reverse("login"), {"username": correo, "password": clave})

    def test_correo_en_mayusculas_inicia_sesion(self):
        self.assertEqual(self.ingresar("ANA@CORREO.CO").status_code, 302)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.usuario.pk))

    def test_contrasena_incorrecta_falla(self):
        self.assertEqual(self.ingresar("ANA@CORREO.CO", "otra-clave").status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_la_base_no_permite_correos_que_solo_difieren_en_mayusculas(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create_user(username="otra", email="ANA@correo.co", password=CLAVE)

    def test_usuario_inactivo_no_inicia_sesion(self):
        Usuario.objects.filter(pk=self.usuario.pk).update(is_active=False)
        self.assertIsNone(authenticate(username="ana@correo.co", password=CLAVE))

    def test_usuario_inexistente_calcula_el_hash(self):
        with mock.patch.object(Usuario, "set_password") as calcular_hash:
            self.assertIsNone(authenticate(username="nadie@correo.co", password=CLAVE))
        calcular_hash.assert_called_once_with(CLAVE)

    def test_si_encuentra_mas_de_uno_no_autentica(self):
        with mock.patch.object(Usuario._default_manager, "filter", return_value=[self.usuario, self.usuario]):
            self.assertIsNone(EmailBackend().authenticate(None, username="ana@correo.co", password=CLAVE))


class NegocioElegidoTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario()
        self.alfa = registrar_negocio(usuario=self.usuario, datos=datos_negocio("Alfa", "1"))
        self.beta = registrar_negocio(usuario=self.usuario, datos=datos_negocio("Beta", "2"))
        self.ajena = registrar_negocio(usuario=crear_usuario("otra@correo.co"), datos=datos_negocio("Ajena", "3"))
        self.client.force_login(self.usuario)

    def elegir(self, valor):
        sesion = self.client.session
        sesion["empresa_id"] = valor
        sesion.save()

    def empresa_activa(self):
        # El middleware deja el negocio activo en la petición; quien_soy ya no existe
        return self.client.get(reverse("dashboard")).wsgi_request.empresa.nombre

    def test_la_sesion_elige_el_segundo_negocio(self):
        self.elegir(str(self.beta.pk))
        self.assertEqual(self.empresa_activa(), "Beta")

    def test_sin_eleccion_usa_el_primero_por_nombre_y_actualiza_la_sesion(self):
        self.assertEqual(self.empresa_activa(), "Alfa")
        self.assertEqual(self.client.session["empresa_id"], str(self.alfa.pk))

    def test_empresa_ajena_se_ignora(self):
        self.elegir(str(self.ajena.pk))
        self.assertEqual(self.empresa_activa(), "Alfa")
        self.assertEqual(self.client.session["empresa_id"], str(self.alfa.pk))

    def test_comprador_con_empresa_ajena_en_la_sesion_no_entra(self):
        self.client.force_login(crear_usuario("comprador@correo.co"))
        self.elegir(str(self.ajena.pk))
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("negocio_registrar"))

    def test_valor_invalido_no_falla(self):
        for valor in ("no-es-un-uuid", -1):
            with self.subTest(valor=valor):
                self.elegir(valor)
                self.assertEqual(self.empresa_activa(), "Alfa")

    def test_empresa_inactiva_en_la_sesion_se_ignora(self):
        Empresa.objects.filter(pk=self.beta.pk).update(activa=False)
        self.elegir(str(self.beta.pk))
        self.assertEqual(self.empresa_activa(), "Alfa")

    def test_registrar_otro_negocio_abre_ese_negocio(self):
        self.client.post(reverse("negocio_registrar"), datos_negocio("Zeta", "4"))
        self.assertEqual(self.empresa_activa(), "Zeta")


def archivo_png(nombre="Foto Original.PNG", relleno=0):
    contenido = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(contenido, "PNG")
    return SimpleUploadedFile(nombre, contenido.getvalue() + b"0" * relleno, "image/png")


class ImagenProductoTests(TestCase):
    def setUp(self):
        carpeta = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(carpeta.cleanup)
        ajuste = override_settings(MEDIA_ROOT=carpeta.name)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        self.usuario = crear_usuario()
        self.empresa = registrar_negocio(usuario=self.usuario, datos=datos_negocio())
        self.client.force_login(self.usuario)

    def datos(self, **extra):
        return {"codigo": "A-1", "nombre": "Arroz", "precio": "1000", "iva_porcentaje": "19",
                "stock_inicial": "0", "stock_minimo": "0", "descripcion": "", **extra}

    def test_subir_imagen_desde_el_panel(self):
        respuesta = self.client.post(reverse("productos_crear"), self.datos(imagen=archivo_png()))
        self.assertRedirects(respuesta, reverse("productos_lista"))
        nombre = Producto.objects.get().imagen.name
        self.assertTrue(nombre.startswith(f"productos/{self.empresa.pk}/"))
        self.assertTrue(nombre.endswith(".png"))
        self.assertNotIn("Original", nombre)

    def test_archivo_que_no_es_imagen_se_rechaza(self):
        falso = SimpleUploadedFile("foto.png", b"esto no es una imagen", "image/png")
        respuesta = self.client.post(reverse("productos_crear"), self.datos(imagen=falso))
        self.assertIn("imagen", respuesta.context["form"].errors)
        self.assertFalse(Producto.objects.exists())

    def test_extension_no_permitida_se_rechaza(self):
        respuesta = self.client.post(reverse("productos_crear"), self.datos(imagen=archivo_png("foto.gif")))
        self.assertIn("imagen", respuesta.context["form"].errors)

    def test_imagen_demasiado_grande_se_rechaza(self):
        pesada = archivo_png(relleno=5 * 1024 * 1024 + 1)
        respuesta = self.client.post(reverse("productos_crear"), self.datos(imagen=pesada))
        self.assertIn("imagen", respuesta.context["form"].errors)

    def test_cambiar_la_foto_borra_el_credito_anterior(self):
        producto = crear_producto(self.empresa, "Arroz", codigo="A-1")
        producto.imagen.save("a.png", archivo_png())
        Producto.objects.filter(pk=producto.pk).update(imagen_credito="Autor, CC BY", imagen_fuente="https://ejemplo.co/a")
        self.client.post(reverse("productos_editar", args=[producto.pk]), self.datos(imagen=archivo_png("b.png")))
        producto.refresh_from_db()
        self.assertEqual(producto.imagen_credito, "")
        self.assertEqual(producto.imagen_fuente, "")

    def test_editar_sin_cambiar_la_foto_conserva_el_credito(self):
        producto = crear_producto(self.empresa, "Arroz", codigo="A-1")
        producto.imagen.save("a.png", archivo_png())
        Producto.objects.filter(pk=producto.pk).update(imagen_credito="Autor, CC BY")
        self.client.post(reverse("productos_editar", args=[producto.pk]), self.datos(nombre="Arroz blanco"))
        producto.refresh_from_db()
        self.assertEqual(producto.nombre, "Arroz blanco")
        self.assertEqual(producto.imagen_credito, "Autor, CC BY")

    def test_catalogo_y_detalle_muestran_la_foto_y_el_credito(self):
        producto = crear_producto(self.empresa, "Arroz")
        producto.imagen.save("a.png", archivo_png())
        Producto.objects.filter(pk=producto.pk).update(imagen_credito="Autor, CC BY")
        self.assertContains(self.client.get(reverse("marketplace")), producto.imagen.url)
        detalle = self.client.get(reverse("tienda_producto", args=[producto.pk]))
        self.assertContains(detalle, producto.imagen.url)
        self.assertContains(detalle, "Autor, CC BY")

    def test_producto_sin_foto_sigue_mostrando_la_inicial(self):
        crear_producto(self.empresa, "Arroz")
        self.assertContains(self.client.get(reverse("marketplace")), 'data-letra="A"')


class BotonMarketplaceTests(TestCase):
    def test_el_panel_tiene_el_boton_al_marketplace(self):
        usuario = crear_usuario()
        registrar_negocio(usuario=usuario, datos=datos_negocio())
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("productos_lista"))
        self.assertContains(respuesta, f'href="{reverse("marketplace")}"')
        self.assertContains(respuesta, "Ir al marketplace")
