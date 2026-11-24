"""Comando de gestión para escalar PQRS vencidas del flujo B (Comprador -> Negocio)."""
from django.core.management.base import BaseCommand

from pqrs.services import escalar_pqrs_vencidas


class Command(BaseCommand):
    """Comando `python manage.py escalar_pqrs_vencidas`: Escala a Intersoft las PQRS de compradores vencidas sin
    respuesta del negocio.
    """
    help = "Escala a Intersoft las PQRS de compradores vencidas sin respuesta del negocio."

    def handle(self, *args, **options):
        escaladas = escalar_pqrs_vencidas()
        self.stdout.write(f"Escalada(s): {escaladas} PQRS.")
