"""Comando de gestión para enviar recordatorios de vencimiento de suscripción (7, 3 y 1 día)."""
from django.core.management.base import BaseCommand

from suscripciones.services import enviar_recordatorios_vencimiento


class Command(BaseCommand):
    help = "Envía recordatorios por correo 7, 3 y 1 día antes del vencimiento de Trials y suscripciones."

    def handle(self, *args, **options):
        enviados = enviar_recordatorios_vencimiento()
        self.stdout.write(f"Recordatorios enviados: {enviados}.")
