"""Pruebas adicionales para reforzar la cobertura de bodegas y salud."""
from django.test import TestCase
from django.urls import reverse

from core import bodegas
from core.models import Bodega, Categoria, Empresa, Membresia, MovimientoInventario, Producto, Rol, Usuario
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
