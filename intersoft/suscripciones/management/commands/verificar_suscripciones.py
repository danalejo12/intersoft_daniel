"""Comando de gestión para vencer periodos de prueba y suscripciones expiradas."""
from django.core.management.base import BaseCommand

from suscripciones.services import verificar_vencimientos


class Command(BaseCommand):
    help = (
        "Revisa todas las suscripciones TRIAL y ACTIVAS cuya fecha vence_en ya expiró "
        "y las pasa automáticamente al plan 'gratis' sin bloquear la cuenta. Es idempotente."
    )

    def handle(self, *args, **options):
        resumen = verificar_vencimientos()
        self.stdout.write(
            self.style.SUCCESS(
                f"Suscripciones procesadas: {resumen['procesadas']} · "
                f"Trials vencidos: {resumen['trials_vencidos']} · "
                f"Activas vencidas: {resumen['activas_vencidas']}"
            )
        )
