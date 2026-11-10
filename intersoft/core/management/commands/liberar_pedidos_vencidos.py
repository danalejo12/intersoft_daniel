from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.compras import vencer_pedido
from core.models import Pedido


class Command(BaseCommand):
    help = "Vence los pedidos pendientes cuyo plazo terminó y devuelve su stock. Es seguro ejecutarlo varias veces."

    def handle(self, *args, **options):
        vencidos = Pedido.objects.filter(estado=Pedido.Estado.PENDIENTE, expira_en__lte=timezone.now())
        resultados = Counter(vencer_pedido(pk) for pk in list(vencidos.values_list("pk", flat=True)))
        self.stdout.write(
            f"Vencidos: {resultados['vencido']} · Pagados al revisar: {resultados['pagado']} · "
            f"Esperando a Wompi: {resultados['esperando']} · Omitidos: {resultados['omitido']}"
        )
