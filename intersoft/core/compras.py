"""Compra en el marketplace: el pedido reserva el stock y la factura nace al aprobarse el pago."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import reservas
from .models import Comentario, DetallePedido, Pago, Pedido, Producto
from .pagos import ResultadoWompi, revisar_en_wompi, sincronizar_pago
from .services import CENTAVOS, StockInsuficiente, siguiente_consecutivo

Estado = Pedido.Estado


class OperacionNoPermitida(Exception):
    """El mensaje se le muestra al comprador."""


def _nuevo_vencimiento():
    return timezone.now() + timedelta(minutes=settings.PEDIDO_MINUTOS_RESERVA)


@transaction.atomic
def crear_pedido(*, usuario, negocio, lineas, datos):
    """Crea el pedido con precios congelados y reserva el stock: todo o nada. No crea factura."""
    # Productos primero y empresa después, el mismo orden de crear_factura, para evitar bloqueos cruzados
    cantidades = {linea["producto"].pk: linea["cantidad"] for linea in lineas}
    productos = list(
        Producto.objects.select_for_update()
        .filter(empresa=negocio, id__in=cantidades, activo=True)
        .order_by("id")
    )
    if len(productos) != len(cantidades):
        raise ValueError("Producto inexistente, inactivo o de otro negocio.")

    subtotal = iva = Decimal("0")
    for producto in productos:  # misma fórmula de services.crear_factura
        valor = producto.precio * cantidades[producto.pk]
        subtotal += valor
        iva += (valor * producto.iva_porcentaje / 100).quantize(CENTAVOS)

    pedido = Pedido.objects.create(
        empresa=negocio,
        comprador=usuario,
        numero=siguiente_consecutivo(Pedido, negocio),
        expira_en=_nuevo_vencimiento(),
        subtotal=subtotal.quantize(CENTAVOS),
        iva=iva,
        total=(subtotal + iva).quantize(CENTAVOS),
        tipo_documento=datos["tipo_documento"],
        numero_documento=datos["numero_documento"],
        nombre=datos["nombre"],
        email=datos["email"],
        telefono=datos["telefono"],
        departamento=datos["departamento"],
        ciudad=datos["ciudad"],
        direccion=datos["direccion"],
        indicaciones=datos["indicaciones"],
    )
    for producto in productos:
        DetallePedido.objects.create(
            empresa=negocio,
            pedido=pedido,
            producto=producto,
            cantidad=cantidades[producto.pk],
            precio_unitario=producto.precio,
            iva_porcentaje=producto.iva_porcentaje,
        )
    reservas.reservar_stock(pedido)
    return pedido


def actualizar_pagos(pedido, transaccion_id=""):
    """Le pregunta a Wompi por los intentos sin respuesta. El navegador nunca decide el estado."""
    for pago in pedido.pagos.filter(estado=Pago.Estado.PENDIENTE):
        sincronizar_pago(pago=pago, transaccion_id=transaccion_id)
    pedido.refresh_from_db()  # aplicar_transaccion trabaja sobre su propia copia bloqueada


def cancelar_pedido(pedido):
    """Solo se cancela si Wompi confirma que ningún intento sigue vivo."""
    resultado = revisar_en_wompi(pedido)
    if resultado == ResultadoWompi.APROBADO:
        raise OperacionNoPermitida("Tu pago ya fue aprobado, así que este pedido no se puede cancelar.")
    if resultado == ResultadoWompi.EN_PROCESO:
        raise OperacionNoPermitida("Tu pago sigue en proceso en Wompi. Espera el resultado antes de cancelar.")
    if resultado == ResultadoWompi.SIN_RESPUESTA:
        raise OperacionNoPermitida("No pudimos confirmar tu pago con Wompi. Inténtalo de nuevo en un momento.")

    with transaction.atomic():
        bloqueado = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if bloqueado.estado != Estado.PENDIENTE:
            raise OperacionNoPermitida("Este pedido ya no se puede cancelar.")
        reservas.liberar_pedido(bloqueado, Estado.CANCELADO)


@transaction.atomic
def renovar_reserva(pedido):
    pedido = Pedido.objects.select_for_update().get(pk=pedido.pk)
    if pedido.renovaciones >= settings.PEDIDO_MAX_RENOVACIONES:
        raise OperacionNoPermitida("Ya renovaste esta reserva las veces permitidas. Puedes hacer un pedido nuevo.")

    if pedido.estado == Estado.VENCIDO:
        # El stock se había liberado: hay que volver a reservarlo con lo que haya hoy
        try:
            with transaction.atomic():
                reservas.reservar_stock(pedido)
        except StockInsuficiente:
            raise OperacionNoPermitida("Lo sentimos, ya no hay unidades suficientes para este pedido.") from None
    elif pedido.estado == Estado.PENDIENTE:
        if not pedido.necesita_renovar:
            raise OperacionNoPermitida("Tu reserva sigue vigente, no hace falta renovarla.")
        if reservas.hay_productos_inactivos(pedido):
            raise OperacionNoPermitida("Lo sentimos, un producto de este pedido ya no está disponible.")
    else:
        raise OperacionNoPermitida("Este pedido ya no se puede renovar.")

    pedido.estado = Estado.PENDIENTE
    pedido.expira_en = _nuevo_vencimiento()
    pedido.renovaciones += 1
    pedido.save(update_fields=["estado", "expira_en", "renovaciones", "actualizado_en"])
    return pedido


def compro_el_producto(usuario, producto):
    return DetallePedido.objects.filter(
        producto=producto,
        pedido__comprador=usuario,
        pedido__estado=Estado.PAGADO,
    ).exists()


def guardar_comentario(*, usuario, producto, calificacion, texto):
    """Una opinión por persona y producto: si ya existe, se actualiza."""
    return Comentario.objects.update_or_create(
        producto=producto,
        autor=usuario,
        defaults={
            "empresa_id": producto.empresa_id,
            "calificacion": calificacion,
            "texto": texto,
            "compra_verificada": compro_el_producto(usuario, producto),
        },
    )[0]
