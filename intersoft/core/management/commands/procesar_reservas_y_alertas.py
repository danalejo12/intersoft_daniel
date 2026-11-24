"""Comando que libera reservas vencidas y envía las alertas de stock mínimo."""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from core.compras import vencer_pedido
from core.models import Existencia, Pedido, Producto
from core.notificaciones import notificar_alerta_stock_minimo


class Command(BaseCommand):
    """Comando `python manage.py procesar_reservas_y_alertas`: Libera reservas de pedidos vencidos de forma
    idempotente y envía alertas de stock mínimo a los roles Administrador y Bodega e inventario.
    """
    help = (
        "Libera reservas de pedidos vencidos de forma idempotente y envía alertas de stock mínimo "
        "a los roles Administrador y Bodega e inventario."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sin-correo",
            action="store_true",
            help="Calcula y muestra las alertas de stock mínimo sin enviar correos.",
        )

    def handle(self, *args, **options):
        vencidos_qs = Pedido.objects.filter(
            estado=Pedido.Estado.PENDIENTE,
            expira_en__lte=timezone.now(),
        )
        resultados = Counter(
            vencer_pedido(pk) for pk in list(vencidos_qs.values_list("pk", flat=True))
        )

        criticos_qs = (
            Producto.objects.filter(
                activo=True,
                empresa__activa=True,
                stock__lte=F("stock_minimo"),
            )
            .select_related("empresa")
            .order_by("empresa__nombre", "codigo")
        )
        por_empresa = defaultdict(list)
        por_empresa_bodega = defaultdict(list)
        empresas_map = {}
        for prod in criticos_qs:
            por_empresa[prod.empresa_id].append(prod)
            empresas_map[prod.empresa_id] = prod.empresa

        existencias_criticas_qs = (
            Existencia.objects.filter(
                bodega__activa=True,
                producto__activo=True,
                empresa__activa=True,
                stock_minimo__isnull=False,
                cantidad__lte=F("stock_minimo"),
            )
            .select_related("empresa", "bodega", "producto")
            .order_by("empresa__nombre", "bodega__nombre", "producto__codigo")
        )
        for ex in existencias_criticas_qs:
            por_empresa_bodega[ex.empresa_id].append(ex)
            empresas_map[ex.empresa_id] = ex.empresa

        correos_enviados = 0
        if not options.get("sin_correo"):
            for emp_id, empresa in empresas_map.items():
                correos_enviados += notificar_alerta_stock_minimo(
                    empresa=empresa,
                    productos_criticos=por_empresa.get(emp_id, []),
                    existencias_criticas=por_empresa_bodega.get(emp_id, []),
                )

        total_criticos = sum(len(v) for v in por_empresa.values()) + sum(len(v) for v in por_empresa_bodega.values())
        self.stdout.write(
            f"Reservas vencidas: {resultados['vencido']} · "
            f"Pagados al revisar: {resultados['pagado']} · "
            f"Esperando a Wompi: {resultados['esperando']} · "
            f"Empresas con alerta de stock: {len(por_empresa)} · "
            f"Productos en stock crítico: {total_criticos} · "
            f"Notificaciones enviadas: {correos_enviados}"
        )
