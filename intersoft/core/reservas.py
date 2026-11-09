"""Reserva de stock y cambios de estado de un pedido.

Quien llama debe tener bloqueado el pedido (select_for_update) dentro de una transacción.
"""
import logging

from django.db import transaction

from .models import MovimientoInventario, Pedido
from .services import StockInsuficiente, crear_factura_desde_pedido, registrar_movimiento

logger = logging.getLogger(__name__)
Estado = Pedido.Estado


def _mover_stock(pedido, tipo, referencia):
    # En orden de producto para evitar bloqueos cruzados entre dos pedidos simultáneos
    for linea in pedido.lineas.select_related("producto").order_by("producto_id"):
        registrar_movimiento(
            empresa=pedido.empresa,
            producto=linea.producto,
            tipo=tipo,
            cantidad=linea.cantidad,
            usuario=pedido.comprador,
            referencia=referencia,
        )


def hay_productos_inactivos(pedido):
    return pedido.lineas.filter(producto__activo=False).exists()


def reservar_stock(pedido):
    if hay_productos_inactivos(pedido):
        raise StockInsuficiente("Un producto del pedido ya no está disponible.")
    _mover_stock(pedido, MovimientoInventario.Tipo.SALIDA, f"Reserva pedido {pedido.numero}")


def liberar_pedido(pedido, nuevo_estado):
    """Devuelve el stock reservado. Solo un pedido pendiente tiene reserva."""
    if pedido.estado != Estado.PENDIENTE:
        raise ValueError("Este pedido no tiene una reserva activa.")
    _mover_stock(pedido, MovimientoInventario.Tipo.ENTRADA, f"Liberación pedido {pedido.numero}")
    pedido.estado = nuevo_estado
    pedido.save(update_fields=["estado", "actualizado_en"])


def marcar_pagado(pedido):
    pedido.factura = crear_factura_desde_pedido(pedido)
    pedido.estado = Estado.PAGADO
    pedido.save(update_fields=["factura", "estado", "actualizado_en"])


def _pasar_a_reembolso(pedido, motivo):
    pedido.estado = Estado.REQUIERE_REEMBOLSO
    pedido.save(update_fields=["estado", "actualizado_en"])
    logger.critical("Pedido %s (empresa %s) requiere reembolso: %s", pedido.numero, pedido.empresa_id, motivo)


def registrar_pago_aprobado(pedido):
    if pedido.estado == Estado.PENDIENTE:
        marcar_pagado(pedido)
    elif pedido.estado == Estado.VENCIDO:
        try:
            with transaction.atomic():  # si falla una línea, no queda ninguna reservada
                reservar_stock(pedido)
        except StockInsuficiente:
            _pasar_a_reembolso(pedido, "pago aprobado después de vencer y ya no hay stock")
        else:
            marcar_pagado(pedido)
    elif pedido.estado == Estado.CANCELADO:
        _pasar_a_reembolso(pedido, "pago aprobado después de que el comprador canceló")


def registrar_monto_invalido(pedido):
    """Wompi aprobó un valor distinto al del pedido: no puede volver a pagarse."""
    if pedido.estado == Estado.PENDIENTE:
        liberar_pedido(pedido, Estado.REQUIERE_REEMBOLSO)
        logger.critical("Pedido %s (empresa %s) requiere reembolso: monto o moneda distintos", pedido.numero, pedido.empresa_id)
    elif pedido.estado in (Estado.VENCIDO, Estado.CANCELADO):
        _pasar_a_reembolso(pedido, "monto o moneda distintos")
