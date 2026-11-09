from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Empresa, Membresia, Producto, Rol
from .negocios import registrar_negocio

Usuario = get_user_model()
CLAVE = "ClaveSegura#2026"


def crear_empresa(nombre, nit, slug, activa=True):
    return Empresa.objects.create(nombre=nombre, nit=nit, slug=slug, activa=activa)


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
    return {"nombre": nombre, "nit": nit, "email": "", "telefono": "", "direccion": ""}


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
