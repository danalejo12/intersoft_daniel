"""Comando que ejecuta las tareas periódicas a las que ya les toca (una pasada o en bucle)."""
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.tareas import TAREAS, ejecutar_pendientes


class Command(BaseCommand):
    """Comando `python manage.py tareas_periodicas`: Ejecuta las tareas periódicas a las que ya les toca (reservas,
    suscripciones, cobros de planes y alertas de stock). Sin --bucle hace una sola pasada: prográmalo cada 5
    minutos en cron o en el Programador de tareas de Windows.
    """
    help = (
        "Ejecuta las tareas periódicas a las que ya les toca (reservas, suscripciones, cobros de planes "
        "y alertas de stock). Sin --bucle hace una sola pasada: prográmalo cada 5 minutos en cron o en "
        "el Programador de tareas de Windows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--bucle", action="store_true",
                            help="No termina: revisa las tareas cada --pausa segundos (contenedor scheduler).")
        parser.add_argument("--pausa", type=int, default=60, help="Segundos entre revisiones con --bucle.")
        parser.add_argument("--forzar", action="store_true",
                            help="Ejecuta las tareas aunque no les toque todavía.")
        parser.add_argument("--solo", nargs="+", choices=[t.nombre for t in TAREAS],
                            help="Limita la pasada a estas tareas.")

    def handle(self, *args, **options):
        while True:
            resultados = ejecutar_pendientes(forzar=options["forzar"], solo=options["solo"])
            ejecutadas = {n: r for n, r in resultados.items() if r != "omitida"}
            if ejecutadas or not options["bucle"]:
                self.stdout.write(" · ".join(f"{n}: {r}" for n, r in resultados.items()))
            if not options["bucle"]:
                return
            close_old_connections()  # en un proceso eterno, no dejar conexiones colgadas
            time.sleep(max(options["pausa"], 5))
