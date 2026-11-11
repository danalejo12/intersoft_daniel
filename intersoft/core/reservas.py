"""Reserva de stock y cambios de estado de un pedido.

Quien llama debe tener bloqueado el pedido (select_for_update) dentro de una transacción.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .models import MovimientoInventario, Pedido
from .notificaciones import (
    notificar_envio_actualizado,
    notificar_pedido_pagado,
    notificar_reembolso_registrado,
)
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
    notificar_pedido_pagado(pedido)


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


@transaction.atomic
def registrar_reembolso(*, pedido, usuario, referencia, nota=""):
    """Marca un pedido en 'requiere_reembolso' como reembolsado dejando trazabilidad completa."""
    bloqueado = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if bloqueado.estado != Estado.REQUIERE_REEMBOLSO:
        raise ValueError("Solo se pueden reembolsar pedidos en estado 'Requiere reembolso'.")
    referencia_limpia = (referencia or "").strip()
    if not referencia_limpia:
        raise ValueError("Debes indicar la referencia o comprobante del reembolso.")
    bloqueado.estado = Estado.REEMBOLSADO
    bloqueado.reembolsado_en = timezone.now()
    bloqueado.reembolso_referencia = referencia_limpia[:80]
    bloqueado.reembolso_nota = (nota or "").strip()[:250]
    bloqueado.reembolsado_por = usuario
    bloqueado.save(
        update_fields=[
            "estado",
            "reembolsado_en",
            "reembolso_referencia",
            "reembolso_nota",
            "reembolsado_por",
            "actualizado_en",
        ]
    )
    notificar_reembolso_registrado(bloqueado)
    return bloqueado


@transaction.atomic
def actualizar_envio_pedido(*, pedido, estado_envio, transportadora="", numero_guia=""):
    """Actualiza el estado logístico y datos de guía de un pedido pagado."""
    bloqueado = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if bloqueado.estado != Estado.PAGADO:
        raise ValueError("Solo se puede gestionar el envío de pedidos pagados.")
    if estado_envio not in Pedido.EstadoEnvio.values:
        raise ValueError("Estado de envío no válido.")

    ahora = timezone.now()
    bloqueado.estado_envio = estado_envio
    bloqueado.transportadora = (transportadora or "").strip()[:80]
    bloqueado.numero_guia = (numero_guia or "").strip()[:80]
    if estado_envio in (Pedido.EstadoEnvio.ENVIADO, Pedido.EstadoEnvio.ENTREGADO) and bloqueado.enviado_en is None:
        bloqueado.enviado_en = ahora
    if estado_envio == Pedido.EstadoEnvio.ENTREGADO and bloqueado.entregado_en is None:
        bloqueado.entregado_en = ahora

    bloqueado.save(
        update_fields=[
            "estado_envio",
            "transportadora",
            "numero_guia",
            "enviado_en",
            "entregado_en",
            "actualizado_en",
        ]
    )
    notificar_envio_actualizado(bloqueado)
    return bloqueado


@transaction.atomic
def registrar_dispersion_pedido(*, pedido, referencia, estado_dispersion=Pedido.EstadoDispersion.LIQUIDADA):
    """Registra la dispersión o liquidación del neto del vendedor para un pedido pagado."""
    bloqueado = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if bloqueado.estado != Estado.PAGADO:
        raise ValueError("Solo se puede dispersar un pedido pagado.")
    if estado_dispersion not in Pedido.EstadoDispersion.values:
        raise ValueError("Estado de dispersión no válido.")
    referencia_limpia = (referencia or "").strip()
    if not referencia_limpia:
        raise ValueError("Debes indicar la referencia de la transferencia o dispersión.")

    bloqueado.estado_dispersion = estado_dispersion
    bloqueado.dispersion_referencia = referencia_limpia[:80]
    if estado_dispersion == Pedido.EstadoDispersion.LIQUIDADA:
        bloqueado.dispersado_en = timezone.now()
    bloqueado.save(
        update_fields=[
            "estado_dispersion",
            "dispersion_referencia",
            "dispersado_en",
            "actualizado_en",
        ]
    )
    return bloqueado
