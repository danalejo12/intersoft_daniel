"""Sección Operación de /plataforma/ y bitácora de auditoría."""
import os
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import EjecucionTarea, Usuario
from core.tareas import TAREAS

from . import auditoria, operacion
from .models import AuditoriaPlataforma, RolPlataforma
from .tests import _TotpAutoMixin


def staff(correo, rol):
    usuario = Usuario.objects.create_user(username=correo, email=correo, password="x", is_staff=True)
    RolPlataforma.objects.create(usuario=usuario, rol=rol, activo=True)
    return usuario


class OperacionTests(_TotpAutoMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.dev = staff("dev@intersoft.co", RolPlataforma.Rol.DESARROLLADOR)
        self.client.force_login(self.dev)

    def test_muestra_estado_tareas_despliegue_y_entorno(self):
        respuesta = self.client.get(reverse("plataforma_operacion"))
        self.assertEqual(respuesta.status_code, 200)
        for texto in ("Base de datos", "Migraciones", "Copias de seguridad", "Revisión de despliegue", "Entorno"):
            self.assertContains(respuesta, texto)
        for tarea in TAREAS:
            self.assertContains(respuesta, tarea.nombre)
        self.assertNotContains(respuesta, "Próximamente")

    def test_nunca_muestra_secretos(self):
        with self.settings(PAGOS_CLAVES_CIFRADO="clave-ultra-secreta-123", SENTRY_DSN="https://token-secreto@sentry.io/1"):
            respuesta = self.client.get(reverse("plataforma_operacion"))
        self.assertNotContains(respuesta, "clave-ultra-secreta-123")
        self.assertNotContains(respuesta, "token-secreto")
        self.assertContains(respuesta, "Clave propia configurada")
        self.assertContains(respuesta, "Sentry configurado")

    def test_ejecutar_tarea_ahora_queda_registrada(self):
        respuesta = self.client.post(reverse("plataforma_operacion"),
                                     {"accion": "ejecutar_tarea", "tarea": "liberar_reservas"}, follow=True)
        self.assertContains(respuesta, "«liberar_reservas» terminó")
        self.assertEqual(EjecucionTarea.objects.get(nombre="liberar_reservas").ejecuciones, 1)
        registro = AuditoriaPlataforma.objects.get(accion="ejecutar_tarea_manual")
        self.assertEqual((registro.actor, registro.objeto_id, registro.detalle["resultado"]),
                         (self.dev, "liberar_reservas", "ok"))

    def test_tarea_que_falla_se_informa(self):
        with mock.patch("core.tareas.call_command", side_effect=RuntimeError("SMTP caído")), \
                self.assertLogs("core.tareas", level="ERROR"):
            respuesta = self.client.post(reverse("plataforma_operacion"),
                                         {"accion": "ejecutar_tarea", "tarea": "alertas_stock"}, follow=True)
        self.assertContains(respuesta, "SMTP caído")
        self.assertEqual(EjecucionTarea.objects.get(nombre="alertas_stock").fallos_seguidos, 1)

    def test_no_ejecuta_tareas_inventadas(self):
        respuesta = self.client.post(reverse("plataforma_operacion"),
                                     {"accion": "ejecutar_tarea", "tarea": "borrar_todo"}, follow=True)
        self.assertContains(respuesta, "Tarea no válida")
        self.assertFalse(AuditoriaPlataforma.objects.filter(accion="ejecutar_tarea_manual").exists())

    def test_solo_dueno_y_desarrollador(self):
        for rol in (RolPlataforma.Rol.FINANZAS, RolPlataforma.Rol.SOPORTE):
            self.client.force_login(staff(f"{rol}@intersoft.co", rol))
            self.assertEqual(self.client.get(reverse("plataforma_operacion")).status_code, 403)
            self.assertEqual(self.client.post(reverse("plataforma_operacion"),
                                              {"accion": "ejecutar_tarea", "tarea": "liberar_reservas"}).status_code, 403)
            self.assertEqual(self.client.get(reverse("plataforma_auditoria")).status_code, 403)
        self.client.force_login(staff("jefe@intersoft.co", RolPlataforma.Rol.DUENO))
        self.assertEqual(self.client.get(reverse("plataforma_operacion")).status_code, 200)


class DiagnosticoTests(TestCase):
    def test_tarea_atrasada_o_con_fallos(self):
        tarea = TAREAS[0]
        EjecucionTarea.objects.create(nombre=tarea.nombre, ultima_ejecucion=timezone.now() - tarea.cada * 5)
        estado = next(t for t in operacion.estado_tareas() if t.nombre == tarea.nombre)
        self.assertTrue(estado.atrasada)
        self.assertEqual(estado.estado, operacion.AVISO)
        EjecucionTarea.objects.filter(nombre=tarea.nombre).update(ultima_ejecucion=timezone.now(), fallos_seguidos=2)
        estado = next(t for t in operacion.estado_tareas() if t.nombre == tarea.nombre)
        self.assertEqual((estado.atrasada, estado.estado), (False, operacion.FALLA))
        self.assertEqual(operacion.revisar_tareas().estado, operacion.FALLA)

    def test_respaldos_ninguno_reciente_y_viejo(self):
        with tempfile.TemporaryDirectory() as carpeta, self.settings(RESPALDOS_DIR=carpeta):
            self.assertEqual(operacion.revisar_respaldos().estado, operacion.AVISO)
            archivo = Path(carpeta) / "intersoft_20261123.dump"
            archivo.write_bytes(b"x" * 1024)
            self.assertEqual(operacion.revisar_respaldos().estado, operacion.OK)
            viejo = time.time() - 30 * 3600
            os.utime(archivo, (viejo, viejo))
            self.assertEqual(operacion.revisar_respaldos().estado, operacion.FALLA)

    def test_una_revision_que_explota_no_rompe_la_pagina(self):
        revision = operacion._seguro("Caché", lambda: 1 / 0)
        self.assertEqual(revision.estado, operacion.FALLA)
        self.assertIn("ZeroDivisionError", revision.detalle)

    def test_migraciones_al_dia_en_pruebas(self):
        self.assertEqual(operacion.revisar_migraciones().estado, operacion.OK)


class BitacoraTests(_TotpAutoMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.jefe = staff("jefe@intersoft.co", RolPlataforma.Rol.DUENO)
        self.client.force_login(self.jefe)

    def test_filtra_y_pagina(self):
        for i in range(55):
            auditoria.registrar(actor=self.jefe, accion="editar_plan", objeto_tipo="Plan", objeto_id=str(i))
        auditoria.registrar(actor=self.jefe, accion="activar_totp", objeto_tipo="RolPlataforma")
        primera = self.client.get(reverse("plataforma_auditoria"))
        self.assertContains(primera, "Página 1 de 2")
        filtrada = self.client.get(reverse("plataforma_auditoria"), {"q": "totp"})
        self.assertContains(filtrada, "activar_totp")
        self.assertNotContains(filtrada, "editar_plan")
        futura = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertContains(self.client.get(reverse("plataforma_auditoria"), {"desde": futura}), "No hay registros")
