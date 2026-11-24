"""Tareas periódicas de Intersoft y cada cuánto se ejecutan.

Un solo punto de entrada (`python manage.py tareas_periodicas`) sirve para:
- Docker: el contenedor `scheduler` lo corre con `--bucle`.
- cron / Programador de tareas de Windows: una pasada cada 5 minutos.

Cada tarea se "reclama" con un UPDATE condicional sobre su fila de EjecucionTarea: si dos
programadores corren a la vez, solo uno gana; y un reinicio no la repite antes de su intervalo.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db.models import Q
from django.utils import timezone

from .models import EjecucionTarea

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tarea:
    """Una tarea periódica: nombre, comando que ejecuta, cada cuánto y descripción."""
    nombre: str
    comando: str
    cada: timedelta
    descripcion: str
    argumentos: tuple = ()


TAREAS = (
    Tarea("liberar_reservas", "liberar_pedidos_vencidos", timedelta(minutes=5),
          "Vence pedidos sin pagar y devuelve su stock."),
    Tarea("verificar_suscripciones", "verificar_suscripciones", timedelta(hours=1),
          "Pasa a Gratis las suscripciones y pruebas vencidas."),
    Tarea("conciliar_cobros_suscripcion", "conciliar_cobros_suscripcion", timedelta(minutes=15),
          "Consulta en Wompi los cobros de planes que siguen pendientes."),
    Tarea("alertas_stock", "procesar_reservas_y_alertas", timedelta(hours=24),
          "Envía una vez al día las alertas de stock mínimo."),
    Tarea("escalar_pqrs_vencidas", "escalar_pqrs_vencidas", timedelta(hours=1),
          "Escala a Intersoft las PQRS de compradores vencidas sin respuesta del negocio."),
    Tarea("recordatorios_vencimiento_plan", "enviar_recordatorios_vencimiento", timedelta(hours=12),
          "Envía recordatorios por correo 7, 3 y 1 día antes de vencer un Trial o plan pago."),
)


def _reclamar(tarea, ahora):
    """True si esta ejecución ganó el turno de la tarea (y ya quedó marcada)."""
    EjecucionTarea.objects.get_or_create(nombre=tarea.nombre)
    return bool(
        EjecucionTarea.objects
        .filter(nombre=tarea.nombre)
        .filter(Q(ultima_ejecucion__isnull=True) | Q(ultima_ejecucion__lte=ahora - tarea.cada))
        .update(ultima_ejecucion=ahora)
    )


def ejecutar_pendientes(*, forzar=False, solo=None):
    """Ejecuta las tareas a las que ya les toca. Devuelve {nombre: "ok" | "omitida" | "error"}.
    Un error en una tarea no detiene las demás."""
    resultados = {}
    for tarea in TAREAS:
        if solo and tarea.nombre not in solo:
            continue
        ahora = timezone.now()
        if forzar:
            EjecucionTarea.objects.update_or_create(nombre=tarea.nombre, defaults={"ultima_ejecucion": ahora})
        elif not _reclamar(tarea, ahora):
            resultados[tarea.nombre] = "omitida"
            continue

        salida = StringIO()
        try:
            call_command(tarea.comando, *tarea.argumentos, stdout=salida)
        except Exception as error:  # noqa: BLE001 - se registra y se sigue con las demás
            logger.exception("Falló la tarea periódica %s", tarea.nombre)
            fila = EjecucionTarea.objects.get(nombre=tarea.nombre)
            fila.ultimo_error = f"{type(error).__name__}: {error}"[:500]
            fila.fallos_seguidos += 1
            fila.ejecuciones += 1
            fila.save(update_fields=["ultimo_error", "fallos_seguidos", "ejecuciones", "actualizado_en"])
            if fila.fallos_seguidos == 3:
                logger.critical("La tarea periódica %s lleva 3 fallos seguidos: %s", tarea.nombre, fila.ultimo_error)
            resultados[tarea.nombre] = "error"
            continue

        fila = EjecucionTarea.objects.get(nombre=tarea.nombre)
        fila.ultimo_resultado = salida.getvalue().strip()[:500]
        fila.ultimo_error = ""
        fila.fallos_seguidos = 0
        fila.ejecuciones += 1
        fila.save(update_fields=["ultimo_resultado", "ultimo_error", "fallos_seguidos", "ejecuciones",
                                 "actualizado_en"])
        resultados[tarea.nombre] = "ok"
    return resultados
