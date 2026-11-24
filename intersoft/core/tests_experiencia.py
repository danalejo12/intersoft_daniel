"""Experiencia de uso: menú agrupado, buscador global (Ctrl + K), inicio del panel y de la consola."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Membresia, Permiso, Rol, Usuario
from plataforma.models import RolPlataforma
from soporte.models import ErrorRegistrado
from suscripciones.models import Suscripcion

from . import caja
from .tests_compra import crear_negocio, crear_usuario


def comandos(respuesta):
    """Texto de la lista de comandos de la paleta (solo lo que el rol puede hacer)."""
    html = respuesta.content.decode()
    ini = html.index('id="paleta-comandos"')
    return html[ini:html.index("</ul>", ini)]


class PanelTests(TestCase):
    def setUp(self):
        self.dueno = crear_usuario("dueno@correo.co", "Daniela")
        self.negocio = crear_negocio("Dulce Hogar", "900", self.dueno)
        self.client.force_login(self.dueno)

    def test_menu_agrupado_con_bodegas(self):
        respuesta = self.client.get(reverse("dashboard"))
        for grupo in ("Vender", "Catálogo", "Administrar", "Mi negocio"):
            self.assertContains(respuesta, f'class="dock-grupo" role="presentation">{grupo}<')
        self.assertContains(respuesta, reverse("bodegas_lista"))

    def test_buscador_global_con_acciones_del_administrador(self):
        lista = comandos(self.client.get(reverse("dashboard")))
        for texto in ("Nuevo producto", "Nueva factura", "Bodegas", "Plan y suscripción", "Cambiar modo día / noche"):
            self.assertIn(texto, lista)
        self.assertIn(f'data-buscar="{reverse("productos_lista")}"', lista)

    def test_buscador_respeta_los_permisos_del_rol(self):
        cajero = crear_usuario("cajero@correo.co", "Carlos")
        rol = Rol.objects.create(empresa=self.negocio, nombre="Solo caja")
        rol.permisos.add(*Permiso.objects.filter(codigo__in=["ventas.crear", "ventas.ver"]))
        Membresia.objects.create(usuario=cajero, empresa=self.negocio, rol=rol, activa=True)
        self.client.force_login(cajero)
        respuesta = self.client.get(reverse("dashboard"))
        lista = comandos(respuesta)
        self.assertIn("Punto de venta", lista)
        for prohibido in ("Nuevo producto", "Equipo y roles", "Pagos en línea", "Plan y suscripción"):
            self.assertNotIn(prohibido, lista)
        self.assertNotContains(respuesta, reverse("productos_crear"))  # ni en accesos rápidos

    def test_inicio_saluda_y_muestra_accesos_y_para_hoy(self):
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "Daniela")
        self.assertContains(respuesta, "Accesos rápidos")
        self.assertContains(respuesta, reverse("productos_crear"))
        self.assertContains(respuesta, "Para hoy")

    def test_para_hoy_avisa_caja_abierta_y_prueba_por_vencer(self):
        caja.abrir_turno(empresa=self.negocio, usuario=self.dueno, base="0")
        Suscripcion.objects.filter(empresa=self.negocio).update(vence_en=timezone.now() + timedelta(days=2))
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "Tienes la caja abierta")
        self.assertContains(respuesta, "Seguir vendiendo")
        self.assertContains(respuesta, "Tu prueba gratis")
        self.assertContains(respuesta, "en 2 días")

    def test_todo_al_dia(self):
        Suscripcion.objects.filter(empresa=self.negocio).update(vence_en=timezone.now() + timedelta(days=30))
        self.assertContains(self.client.get(reverse("dashboard")), "Todo al día")

    def test_buscador_de_la_barra_sigue_funcionando_sin_javascript(self):
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, f'action="{reverse("productos_lista")}"')
        self.assertContains(respuesta, "data-paleta-abrir")
        self.assertContains(respuesta, "core/js/paleta.js")


class ConsolaTests(TestCase):
    def entrar(self, rol):
        usuario = Usuario.objects.create_user(username=f"{rol}@intersoft.co", email=f"{rol}@intersoft.co",
                                              password="x", is_staff=True, first_name="Ana")
        RolPlataforma.objects.create(usuario=usuario, rol=rol, activo=True)
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(usuario.pk)
        sesion.save()
        return self.client.get(reverse("plataforma_inicio"))

    def test_soporte_solo_ve_sus_secciones(self):
        respuesta = self.entrar(RolPlataforma.Rol.SOPORTE)
        self.assertContains(respuesta, reverse("plataforma_pqrs"))
        self.assertNotContains(respuesta, reverse("plataforma_planes_cobros"))
        self.assertNotContains(respuesta, reverse("plataforma_operacion"))
        self.assertNotIn("Operación", comandos(respuesta))

    def test_desarrollador_ve_operacion_auditoria_y_errores_nuevos(self):
        ErrorRegistrado.objects.create(huella="abc", tipo_excepcion="ValueError", mensaje="x")
        respuesta = self.entrar(RolPlataforma.Rol.DESARROLLADOR)
        self.assertContains(respuesta, reverse("plataforma_auditoria"))
        self.assertContains(respuesta, "Requiere tu atención")
        self.assertContains(respuesta, "1 error(es) nuevo(s)")
        self.assertIn("Operación", comandos(respuesta))

    def test_sin_pendientes_todo_en_orden(self):
        respuesta = self.entrar(RolPlataforma.Rol.FINANZAS)
        self.assertContains(respuesta, "Nada urgente")
