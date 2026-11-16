"""Mejoras de usabilidad: galería, sugerencias, guía de primeros pasos, menú y aviso al negocio."""
import tempfile
from unittest import mock

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import FOTOS_EXTRA_MAXIMO, FotoProducto, Producto
from .negocios import registrar_negocio
from .notificaciones import notificar_negocio_pedido_pagado, telefono_whatsapp
from .tests_compra import crear_usuario
from .tests_marketplace import archivo_png, datos_negocio
from .tests_pedidos import PedidoBase


class ConMedios(TestCase):
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
        return {"codigo": "A-1", "nombre": "Tarta", "precio": "1000", "iva_porcentaje": "19",
                "stock_inicial": "0", "stock_minimo": "0", "descripcion": "", **extra}


class GaleriaTests(ConMedios):
    def test_sube_varias_fotos_y_las_muestra_en_el_marketplace(self):
        respuesta = self.client.post(reverse("productos_crear"), self.datos(
            imagen=archivo_png("principal.png"), publicado="on",
            fotos_extra=[archivo_png("a.png"), archivo_png("b.png")],
        ))
        self.assertRedirects(respuesta, reverse("productos_lista"))
        producto = Producto.objects.get()
        self.assertEqual(producto.fotos.count(), 2)
        self.assertTrue(all(f.imagen.name.startswith(f"productos/{self.empresa.pk}/") for f in producto.fotos.all()))
        detalle = self.client.get(reverse("tienda_producto", args=[producto.pk]))
        self.assertContains(detalle, "data-galeria-foto", count=3)

    def test_quitar_fotos_desde_el_formulario(self):
        self.client.post(reverse("productos_crear"), self.datos(fotos_extra=[archivo_png("a.png"), archivo_png("b.png")]))
        producto = Producto.objects.get()
        quitar = producto.fotos.first()
        datos = self.datos(quitar_fotos=[str(quitar.pk)])
        datos.pop("stock_inicial")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("productos_editar", args=[producto.pk]), datos)
        self.assertEqual(producto.fotos.count(), 1)
        self.assertFalse(FotoProducto.objects.filter(pk=quitar.pk).exists())

    def test_limite_de_fotos(self):
        archivos = [archivo_png(f"{i}.png") for i in range(FOTOS_EXTRA_MAXIMO + 1)]
        respuesta = self.client.post(reverse("productos_crear"), self.datos(fotos_extra=archivos))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Producto.objects.exists())

    def test_archivo_falso_se_rechaza(self):
        falso = SimpleUploadedFile("x.png", b"no soy imagen", "image/png")
        respuesta = self.client.post(reverse("productos_crear"), self.datos(fotos_extra=[falso]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(FotoProducto.objects.exists())


class SugerenciasTests(TestCase):
    def setUp(self):
        dueno = crear_usuario("d@correo.co")
        self.empresa = registrar_negocio(usuario=dueno, datos=datos_negocio("Dulce", "901"))
        Producto.objects.create(empresa=self.empresa, nombre="Torta de fresa", codigo="T", precio=1000, publicado=True)
        Producto.objects.create(empresa=self.empresa, nombre="Fresa oculta", codigo="O", precio=1000, publicado=False)

    def test_devuelve_solo_productos_publicados(self):
        datos = self.client.get(reverse("sugerencias_busqueda"), {"q": "fresa"}).json()
        self.assertEqual([p["nombre"] for p in datos["productos"]], ["Torta de fresa"])

    def test_busqueda_corta_no_consulta(self):
        self.assertEqual(self.client.get(reverse("sugerencias_busqueda"), {"q": "f"}).json()["productos"], [])

    def test_solo_get(self):
        self.assertEqual(self.client.post(reverse("sugerencias_busqueda"), {"q": "fresa"}).status_code, 405)


class GuiaPrimerosPasosTests(ConMedios):
    def test_negocio_nuevo_ve_la_guia(self):
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "Prepara tu negocio para vender")
        self.assertContains(respuesta, "Crea tu primer producto")

    def test_menu_lateral_tiene_boton_para_expandir(self):
        self.assertContains(self.client.get(reverse("dashboard")), "data-dock-expandir")


class AvisoAlNegocioTests(PedidoBase):
    def test_correo_al_negocio_con_el_detalle_del_pedido(self):
        self.negocio.email = "ventas@negocio.co"
        self.negocio.save()
        mail.outbox.clear()
        enviados, whatsapp = notificar_negocio_pedido_pagado(self.pedido)
        self.assertEqual(enviados, 1)
        self.assertFalse(whatsapp)  # sin llaves de WhatsApp no se intenta
        correo = mail.outbox[-1]
        self.assertIn("ventas@negocio.co", correo.to)
        self.assertIn(f"#{self.pedido.numero}", correo.subject)
        self.assertIn(self.producto.nombre, correo.body)

    @override_settings(WHATSAPP_TOKEN="t", WHATSAPP_TELEFONO_ID="1", WHATSAPP_PLANTILLA_PEDIDO="pedido_pagado")
    def test_whatsapp_usa_la_plantilla_si_esta_configurado(self):
        self.negocio.telefono = "300 123 4567"
        self.negocio.save()
        respuesta = mock.MagicMock(status=200)
        respuesta.__enter__.return_value = respuesta
        with mock.patch("urllib.request.urlopen", return_value=respuesta) as abrir:
            _, whatsapp = notificar_negocio_pedido_pagado(self.pedido)
        self.assertTrue(whatsapp)
        solicitud = abrir.call_args.args[0]
        self.assertIn(b'"to": "573001234567"', solicitud.data)
        self.assertIn(b'"pedido_pagado"', solicitud.data)

    def test_telefono_whatsapp(self):
        self.assertEqual(telefono_whatsapp("+57 300 123 4567"), "573001234567")
        self.assertIsNone(telefono_whatsapp("601 234 5678"))  # fijo: no tiene WhatsApp
        self.assertIsNone(telefono_whatsapp(""))
