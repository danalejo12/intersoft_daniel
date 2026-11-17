"""Programador de tareas periódicas: intervalos, reinicios, fallos y el comando."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from . import tareas
from .models import EjecucionTarea


class TareasPeriodicasTests(TestCase):
    def test_primera_pasada_ejecuta_todas(self):
        resultados = tareas.ejecutar_pendientes()
        self.assertEqual(set(resultados), {t.nombre for t in tareas.TAREAS})
        self.assertTrue(all(r == "ok" for r in resultados.values()), resultados)
        fila = EjecucionTarea.objects.get(nombre="liberar_reservas")
        self.assertEqual(fila.ejecuciones, 1)
        self.assertIn("Vencidos", fila.ultimo_resultado)

    def test_no_repite_antes_de_su_intervalo(self):
        tareas.ejecutar_pendientes()
        self.assertTrue(all(r == "omitida" for r in tareas.ejecutar_pendientes().values()))

    def test_cada_tarea_respeta_su_propio_intervalo(self):
        tareas.ejecutar_pendientes()
        hace_10_min = timezone.now() - timedelta(minutes=10)
        EjecucionTarea.objects.update(ultima_ejecucion=hace_10_min)
        resultados = tareas.ejecutar_pendientes()
        self.assertEqual(resultados["liberar_reservas"], "ok")       # cada 5 min
        self.assertEqual(resultados["alertas_stock"], "omitida")     # cada día
        self.assertEqual(resultados["verificar_suscripciones"], "omitida")  # cada hora

    def test_reclamar_solo_lo_gana_un_programador(self):
        tarea = tareas.TAREAS[0]
        ahora = timezone.now()
        self.assertTrue(tareas._reclamar(tarea, ahora))
        self.assertFalse(tareas._reclamar(tarea, ahora))

    def test_un_fallo_no_detiene_las_demas_y_alerta_al_tercero(self):
        original = call_command

        def falla_alertas(nombre, *args, **kwargs):
            if nombre == "procesar_reservas_y_alertas":
                raise RuntimeError("SMTP caído")
            return original(nombre, *args, **kwargs)

        with mock.patch.object(tareas, "call_command", side_effect=falla_alertas), \
                self.assertLogs("core.tareas", level="ERROR") as registros:
            for _ in range(3):
                resultados = tareas.ejecutar_pendientes(forzar=True)
        self.assertEqual(resultados["alertas_stock"], "error")
        self.assertEqual(resultados["liberar_reservas"], "ok")
        fila = EjecucionTarea.objects.get(nombre="alertas_stock")
        self.assertEqual((fila.fallos_seguidos, fila.ultimo_error), (3, "RuntimeError: SMTP caído"))
        self.assertTrue(any("CRITICAL" in r and "3 fallos" in r for r in registros.output))

        tareas.ejecutar_pendientes(forzar=True)  # se recupera
        fila.refresh_from_db()
        self.assertEqual((fila.fallos_seguidos, fila.ultimo_error), (0, ""))

    def test_comando_una_pasada_y_filtro_solo(self):
        salida = StringIO()
        call_command("tareas_periodicas", "--solo", "liberar_reservas", stdout=salida)
        self.assertEqual(salida.getvalue().strip(), "liberar_reservas: ok")
        self.assertFalse(EjecucionTarea.objects.filter(nombre="alertas_stock").exists())
