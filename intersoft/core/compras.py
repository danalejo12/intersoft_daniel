"""Compra en el marketplace. Reutiliza la facturación y los pagos del panel, sin duplicarlos."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Cliente, Comentario, DetalleFactura, Pago, Pedido
from .pagos import sincronizar_pago
from .services import anular_factura, crear_factura


@transaction.atomic
def crear_pedido(*, usuario, negocio, lineas, datos):
    """Crea cliente, factura y pedido, y reserva el stock: las tres cosas o ninguna."""
    cliente, _ = Cliente.objects.get_or_create(
        empresa=negocio,
        tipo_documento=datos["tipo_documento"],
        numero_documento=datos["numero_documento"],
        defaults={
            "nombre": datos["nombre"],
            "email": datos["email"],
            "telefono": datos["telefono"],
            "direccion": datos["direccion"],
        },
    )
    factura = crear_factura(
        empresa=negocio,
        usuario=usuario,
        cliente=cliente,
        items=[{"producto": linea["producto"], "cantidad": linea["cantidad"]} for linea in lineas],
    )
    return Pedido.objects.create(
        empresa=negocio,
        comprador=usuario,
        factura=factura,
        numero=factura.numero,
        expira_en=timezone.now() + timedelta(minutes=settings.PEDIDO_MINUTOS_RESERVA),
        subtotal=factura.subtotal,
        iva=factura.iva,
        total=factura.total,
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


def actualizar_pagos(pedido, transaccion_id=""):
    """Le pregunta a Wompi por los intentos sin respuesta. El navegador nunca decide el estado."""
    for pago in pedido.factura.pagos.filter(estado=Pago.Estado.PENDIENTE):
        sincronizar_pago(pago=pago, transaccion_id=transaccion_id)


def cancelar_pedido(pedido):
    """Devuelve el stock. Antes confirma con Wompi, por si el pago ya se aprobó."""
    actualizar_pagos(pedido)
    return anular_factura(factura=pedido.factura, usuario=pedido.comprador)


def compro_el_producto(usuario, producto):
    return DetalleFactura.objects.filter(
        producto=producto,
        factura__pedido__comprador=usuario,
        factura__pagos__estado=Pago.Estado.APROBADO,
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
