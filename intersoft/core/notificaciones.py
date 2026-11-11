"""Notificaciones transaccionales por correo para compradores del marketplace."""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _enviar(*, asunto, mensaje, destinatarios):
    limpios = []
    for correo in destinatarios:
        valor = (correo or "").strip()
        if valor and valor not in limpios:
            limpios.append(valor)
    if not limpios:
        return 0
    try:
        return send_mail(
            subject=asunto,
            message=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=limpios,
            fail_silently=False,
        )
    except Exception:
        logger.warning("No se pudo enviar correo transaccional: %s", asunto, exc_info=True)
        return 0


def notificar_pedido_pagado(pedido):
    """Envía confirmación al comprador cuando el pago del pedido queda aprobado."""
    factura_txt = f" (Factura #{pedido.factura.numero})" if pedido.factura_id else ""
    asunto = f"Confirmación de pago · Pedido #{pedido.numero} en {pedido.empresa.nombre}"
    mensaje = (
        f"Hola {pedido.nombre},\n\n"
        f"Recibimos tu pago para el pedido #{pedido.numero}{factura_txt} en {pedido.empresa.nombre}.\n"
        f"Total pagado: $ {pedido.total}\n"
        f"Dirección de entrega: {pedido.direccion}, {pedido.ciudad} ({pedido.departamento}).\n\n"
        f"Te avisaremos cuando tu pedido sea despachado."
    )
    return _enviar(asunto=asunto, mensaje=mensaje, destinatarios=[pedido.email])


def notificar_envio_actualizado(pedido):
    """Notifica al comprador cuando el pedido pasa a enviado o entregado."""
    if pedido.estado_envio not in ("enviado", "entregado"):
        return 0
    asunto = f"Actualización de envío · Pedido #{pedido.numero} ({pedido.get_estado_envio_display()})"
    lineas = [
        f"Hola {pedido.nombre},",
        "",
        f"El estado de envío de tu pedido #{pedido.numero} en {pedido.empresa.nombre} ahora es: {pedido.get_estado_envio_display()}.",
    ]
    if pedido.transportadora:
        lineas.append(f"Transportadora: {pedido.transportadora}")
    if pedido.numero_guia:
        lineas.append(f"Número de guía: {pedido.numero_guia}")
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=[pedido.email])


def notificar_reembolso_registrado(pedido):
    """Notifica al comprador cuando se registra el reembolso de su pedido."""
    asunto = f"Reembolso procesado · Pedido #{pedido.numero} en {pedido.empresa.nombre}"
    lineas = [
        f"Hola {pedido.nombre},",
        "",
        f"Hemos procesado el reembolso correspondiente al pedido #{pedido.numero} en {pedido.empresa.nombre}.",
        f"Comprobante de reembolso: {pedido.reembolso_referencia}",
        f"Monto del pedido: $ {pedido.total}",
    ]
    if pedido.reembolso_nota:
        lineas.append(f"Nota: {pedido.reembolso_nota}")
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=[pedido.email])
