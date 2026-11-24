"""Pruebas de la Ley 1581 de 2012: autorización con prueba, derechos del titular, plazos y supresión."""
import json
from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Comentario, Empresa, Membresia, Pedido, Rol, Usuario
from plataforma.models import AuditoriaPlataforma, RolPlataforma
from pqrs.dias_habiles import sumar_dias_habiles

from . import politica, services
from .models import AutorizacionDatos, SolicitudDatos

CLAVE = "ClaveSegura#2026"


def crear_usuario(correo="titular@correo.co", **extra):
    """Usuario de prueba con nombre y teléfono."""
    return Usuario.objects.create_user(username=correo, email=correo, password=CLAVE, first_name="Ana",
                                       last_name="Ruiz", telefono="3001234567", **extra)


def datos_registro(**extra):
    """Datos válidos del formulario de registro, con las dos casillas marcadas."""
    return {"first_name": "Ana", "last_name": "Ruiz", "email": "nueva@correo.co", "password1": CLAVE,
            "password2": CLAVE, "acepta_datos": "on", "mayor_edad": "on", **extra}


class RegistroConAutorizacionTests(TestCase):
    def test_sin_marcar_la_autorizacion_no_crea_la_cuenta(self):
        datos = datos_registro()
        del datos["acepta_datos"]
        respuesta = self.client.post(reverse("registro"), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "debes autorizar el tratamiento")
        self.assertFalse(Usuario.objects.filter(email="nueva@correo.co").exists())

    def test_sin_declarar_mayoria_de_edad_no_crea_la_cuenta(self):
        datos = datos_registro()
        del datos["mayor_edad"]
        self.client.post(reverse("registro"), datos)
        self.assertFalse(Usuario.objects.filter(email="nueva@correo.co").exists())

    def test_las_casillas_no_vienen_marcadas(self):
        html = self.client.get(reverse("registro")).content.decode()
        self.assertIn('name="acepta_datos"', html)
        self.assertNotRegex(html, r'<input type="checkbox"[^>]*\bchecked\b')
        self.assertIn(reverse("legal_privacidad"), html)  # enlace a la política (consentimiento informado)

    def test_guarda_la_prueba_de_la_autorizacion(self):
        self.client.post(reverse("registro"), datos_registro(), REMOTE_ADDR="190.24.5.6",
                         HTTP_USER_AGENT="Navegador de prueba")
        usuario = Usuario.objects.get(email="nueva@correo.co")
        autorizacion = usuario.autorizaciones_datos.get()
        self.assertEqual(autorizacion.version_politica, politica.VERSION_POLITICA)
        self.assertEqual(autorizacion.medio, "registro")
        self.assertEqual(autorizacion.ip, "190.24.5.6")
        self.assertEqual(autorizacion.navegador, "Navegador de prueba")
        self.assertTrue(autorizacion.mayor_de_edad)
        self.assertEqual(autorizacion.finalidades, list(politica.FINALIDADES))


@override_settings(PROTECCION_DATOS_EXIGIR_AUTORIZACION=True)
class ExigirAutorizacionTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario()
        self.client.force_login(self.usuario)

    def test_cuenta_sin_autorizacion_es_llevada_a_autorizar(self):
        respuesta = self.client.get(reverse("mis_pedidos"))
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(respuesta["Location"].startswith(reverse("datos_autorizar")))

    def test_puede_leer_la_politica_y_ejercer_derechos_sin_aceptar(self):
        self.assertEqual(self.client.get(reverse("legal_privacidad")).status_code, 200)
        self.assertEqual(self.client.get(reverse("mis_datos")).status_code, 200)

    def test_al_aceptar_vuelve_a_la_pagina_que_pedia(self):
        destino = reverse("mis_pedidos")
        respuesta = self.client.post(reverse("datos_autorizar"), {"acepta_datos": "on", "mayor_edad": "on",
                                                                  "next": destino})
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        self.assertIsNotNone(services.autorizacion_vigente(self.usuario))
        self.assertEqual(self.client.get(destino).status_code, 200)

    def test_cambio_de_version_de_la_politica_pide_aceptar_de_nuevo(self):
        services.registrar_autorizacion(self.usuario, medio="registro")
        AutorizacionDatos.objects.update(version_politica="0.9")
        self.assertEqual(self.client.get(reverse("mis_pedidos")).status_code, 302)

    @override_settings(PROTECCION_DATOS_EXIGIR_AUTORIZACION=False)
    def test_se_puede_apagar_por_configuracion(self):
        self.assertEqual(self.client.get(reverse("mis_pedidos")).status_code, 200)


@override_settings(DATOS_RESPONSABLE_RAZON_SOCIAL="", DATOS_RESPONSABLE_NIT="")
class PoliticaTests(TestCase):
    def test_tiene_los_elementos_del_decreto_1377(self):
        html = self.client.get(reverse("legal_privacidad")).content.decode()
        for texto in ("Ley 1581 de 2012", "Responsable del tratamiento", "Finalidades", "derechos",
                      "10 días hábiles", "15 días hábiles", "Superintendencia de Industria y Comercio",
                      politica.VERSION_POLITICA, "Menores de edad", "Cookies"):
            self.assertIn(texto, html)

    def test_marca_en_rojo_los_datos_del_responsable_que_faltan(self):
        html = self.client.get(reverse("legal_privacidad")).content.decode()
        self.assertIn("por configurar", html)
        self.assertIn("razon_social", html)

    @override_settings(DATOS_RESPONSABLE_RAZON_SOCIAL="Intersoft S.A.S.", DATOS_RESPONSABLE_NIT="900123456-7",
                       DATOS_RESPONSABLE_DIRECCION="Calle 1 # 2-3, Bogotá", DATOS_RESPONSABLE_CORREO="datos@x.co",
                       DATOS_RESPONSABLE_TELEFONO="6011234567")
    def test_con_los_datos_configurados_no_hay_avisos_pendientes(self):
        html = self.client.get(reverse("legal_privacidad")).content.decode()
        self.assertIn("Intersoft S.A.S.", html)
        self.assertNotIn("por configurar", html)


class DerechosDelTitularTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario()
        services.registrar_autorizacion(self.usuario, medio="registro")
        self.client.force_login(self.usuario)

    def test_descarga_todos_sus_datos_en_json(self):
        respuesta = self.client.get(reverse("mis_datos_descargar"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("attachment", respuesta["Content-Disposition"])
        self.assertEqual(respuesta["Cache-Control"], "no-store")
        datos = json.loads(respuesta.content)
        self.assertEqual(datos["cuenta"]["correo"], "titular@correo.co")
        self.assertEqual(len(datos["autorizaciones"]), 1)
        for clave in ("pedidos", "opiniones", "pqrs", "negocios", "solicitudes_de_datos"):
            self.assertIn(clave, datos)

    def test_la_descarga_exige_sesion(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("mis_datos_descargar")).status_code, 302)

    def test_consulta_con_radicado_y_plazo_de_10_dias_habiles(self):
        antes = timezone.now()
        respuesta = self.client.post(reverse("mis_datos"), {"tipo": "conocer", "detalle": "¿Qué datos tienen?"})
        self.assertRedirects(respuesta, reverse("mis_datos"))
        solicitud = SolicitudDatos.objects.get()
        self.assertRegex(solicitud.radicado, r"^HD-\d{4}-00001$")
        self.assertTrue(solicitud.es_consulta)
        esperado = sumar_dias_habiles(antes, 10)
        self.assertLess(abs(solicitud.fecha_limite - esperado), timedelta(minutes=1))
        self.assertIn(solicitud.radicado, mail.outbox[0].subject)  # acuse de recibo al titular

    def test_reclamo_con_plazo_de_15_dias_habiles(self):
        antes = timezone.now()
        self.client.post(reverse("mis_datos"), {"tipo": "suprimir"})
        solicitud = SolicitudDatos.objects.get()
        self.assertFalse(solicitud.es_consulta)
        self.assertLess(abs(solicitud.fecha_limite - sumar_dias_habiles(antes, 15)), timedelta(minutes=1))

    def test_tipo_invalido_no_radica(self):
        respuesta = self.client.post(reverse("mis_datos"), {"tipo": "otra-cosa"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(SolicitudDatos.objects.exists())

    def test_solo_ve_sus_propias_solicitudes(self):
        otro = crear_usuario("otro@correo.co")
        ajena = services.radicar_solicitud(titular=otro, tipo="conocer")
        html = self.client.get(reverse("mis_datos")).content.decode()
        self.assertNotIn(ajena.radicado, html)

    def test_solicitud_sin_respuesta_a_tiempo_queda_vencida(self):
        solicitud = services.radicar_solicitud(titular=self.usuario, tipo="conocer")
        SolicitudDatos.objects.filter(pk=solicitud.pk).update(fecha_limite=timezone.now() - timedelta(days=1))
        solicitud.refresh_from_db()
        self.assertTrue(solicitud.vencida)


class SupresionTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario()
        services.registrar_autorizacion(self.usuario, medio="registro")
        self.empresa = Empresa.objects.create(nombre="Pastelería", nit="900000099", slug="pasteleria")

    def crear_pedido(self):
        """Pedido del titular con sus datos de envío."""
        return Pedido.objects.create(
            empresa=self.empresa, comprador=self.usuario, numero=1, expira_en=timezone.now() + timedelta(hours=1),
            tipo_documento="CC", numero_documento="1020304050", nombre="Ana Ruiz", email="titular@correo.co",
            telefono="3001234567", departamento="Cundinamarca", ciudad="Bogotá", direccion="Calle 10 # 5-20",
        )

    def test_anonimiza_al_titular_y_conserva_los_pedidos_sin_identificarlo(self):
        pedido = self.crear_pedido()
        services.suprimir_datos_titular(self.usuario)
        self.usuario.refresh_from_db()
        pedido.refresh_from_db()
        self.assertFalse(self.usuario.is_active)
        self.assertFalse(self.usuario.has_usable_password())
        self.assertTrue(self.usuario.email.endswith("@anonimo.invalid"))
        self.assertEqual(self.usuario.telefono, "")
        self.assertNotIn("Ana", self.usuario.get_full_name())
        # El pedido (soporte contable) se conserva, pero sin datos que identifiquen al titular
        self.assertEqual(pedido.numero_documento, "SUPRIMIDO")
        self.assertNotIn("Calle 10", pedido.direccion)
        self.assertEqual(pedido.telefono, "")
        # La autorización queda como prueba histórica, marcada como revocada
        self.assertIsNotNone(self.usuario.autorizaciones_datos.get().revocada_en)

    def test_borra_las_opiniones_del_titular(self):
        from core.models import Producto

        producto = Producto.objects.create(empresa=self.empresa, nombre="Torta", precio=10000)
        Comentario.objects.create(empresa=self.empresa, producto=producto, autor=self.usuario, calificacion=5,
                                  texto="Muy rica")
        services.suprimir_datos_titular(self.usuario)
        self.assertFalse(Comentario.objects.exists())

    def test_no_suprime_al_unico_administrador_de_un_negocio(self):
        rol = Rol.objects.create(empresa=self.empresa, nombre="Admin", es_admin=True)
        Membresia.objects.create(usuario=self.usuario, empresa=self.empresa, rol=rol)
        with self.assertRaises(services.SupresionNoPermitida):
            services.suprimir_datos_titular(self.usuario)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)


class ConsolaPlataformaTests(TestCase):
    def setUp(self):
        self.titular = crear_usuario()
        self.solicitud = services.radicar_solicitud(titular=self.titular, tipo="suprimir", detalle="Borren todo")
        self.soporte = Usuario.objects.create_user(username="soporte@x.co", email="soporte@x.co", password=CLAVE,
                                                   is_staff=True)
        RolPlataforma.objects.create(usuario=self.soporte, rol=RolPlataforma.Rol.SOPORTE, activo=True)
        self.client.force_login(self.soporte)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(self.soporte.pk)
        sesion.save()
        mail.outbox.clear()

    def test_lista_las_solicitudes(self):
        respuesta = self.client.get(reverse("plataforma_datos"))
        self.assertContains(respuesta, self.solicitud.radicado)

    def test_usuario_sin_permiso_pqrs_no_entra(self):
        finanzas = Usuario.objects.create_user(username="fin@x.co", email="fin@x.co", password=CLAVE, is_staff=True)
        RolPlataforma.objects.create(usuario=finanzas, rol=RolPlataforma.Rol.FINANZAS, activo=True)
        self.client.force_login(finanzas)
        sesion = self.client.session
        sesion["plataforma_totp_verificado"] = str(finanzas.pk)
        sesion.save()
        self.assertEqual(self.client.get(reverse("plataforma_datos")).status_code, 403)

    def test_un_comprador_no_entra_a_la_consola(self):
        self.client.force_login(self.titular)
        self.assertEqual(self.client.get(reverse("plataforma_datos")).status_code, 403)

    def test_responder_cierra_la_solicitud_y_avisa_al_titular(self):
        url = reverse("plataforma_datos_detalle", args=[self.solicitud.pk])
        self.client.post(url, {"accion": "responder", "respuesta": "Listo, revisamos tu caso."})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudDatos.Estado.RESPONDIDA)
        self.assertEqual(self.solicitud.atendida_por, self.soporte)
        self.assertEqual(mail.outbox[0].to, ["titular@correo.co"])
        self.assertTrue(AuditoriaPlataforma.objects.filter(accion="datos_personales_responder").exists())

    def test_suprimir_responde_al_correo_real_y_luego_anonimiza(self):
        url = reverse("plataforma_datos_detalle", args=[self.solicitud.pk])
        self.client.post(url, {"accion": "suprimir", "respuesta": "Suprimimos tus datos."})
        self.solicitud.refresh_from_db()
        self.titular.refresh_from_db()
        self.assertIsNotNone(self.solicitud.datos_suprimidos_en)
        self.assertFalse(self.titular.is_active)
        self.assertEqual(mail.outbox[0].to, ["titular@correo.co"])

    def test_no_suprime_desde_una_consulta(self):
        consulta = services.radicar_solicitud(titular=self.titular, tipo="conocer")
        url = reverse("plataforma_datos_detalle", args=[consulta.pk])
        self.client.post(url, {"accion": "suprimir", "respuesta": "x"})
        self.titular.refresh_from_db()
        self.assertTrue(self.titular.is_active)

    def test_respuesta_vacia_no_cierra(self):
        url = reverse("plataforma_datos_detalle", args=[self.solicitud.pk])
        respuesta = self.client.post(url, {"accion": "responder", "respuesta": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, SolicitudDatos.Estado.RADICADA)


class ClientePosTests(TestCase):
    def test_registra_la_fecha_de_la_autorizacion_del_cliente(self):
        from core.forms import ClienteForm

        empresa = Empresa.objects.create(nombre="Tienda", nit="900000098", slug="tienda")
        form = ClienteForm({"tipo_documento": "CC", "numero_documento": "123", "nombre": "Luis",
                            "autoriza_datos": "on"}, empresa=empresa)
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.empresa = empresa
        cliente = form.save()
        self.assertIsNotNone(cliente.autoriza_datos_en)
