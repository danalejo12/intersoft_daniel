"""Consulta en Wompi los cobros de planes pendientes y anula los abandonados (más de 48 h)."""
from django.core.management.base import BaseCommand

from suscripciones.cobros import conciliar_pendientes


class Command(BaseCommand):
    """Comando `python manage.py conciliar_cobros_suscripcion`: Concilia con Wompi los cobros de planes pendientes.
    Es seguro ejecutarlo varias veces.
    """
    help = "Concilia con Wompi los cobros de planes pendientes. Es seguro ejecutarlo varias veces."

    def handle(self, *args, **options):
        resultados = conciliar_pendientes()
        self.stdout.write(
            f"Aprobados: {resultados['aprobado']} · Rechazados: {resultados['rechazado']} · "
            f"Siguen pendientes: {resultados['pendiente']} · Anulados sin pago: {resultados['anulado']} · "
            f"Requieren revisión: {resultados['requiere_revision']}"
        )
