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


def notificar_alerta_stock_minimo(*, empresa, productos_criticos, existencias_criticas=None):
    """Notifica a los miembros con rol Administrador o Bodega sobre stock crítico global y por bodega."""
    from .models import Membresia

    productos = list(productos_criticos)
    existencias = list(existencias_criticas or [])
    if not productos and not existencias:
        return 0

    membresias = (
        Membresia.objects.filter(empresa=empresa, activa=True, usuario__is_active=True)
        .select_related("usuario", "rol")
        .prefetch_related("rol__permisos")
    )
    destinatarios = [empresa.email] if empresa.email else []
    for m in membresias:
        if (
            m.rol.es_admin
            or m.tiene_permiso("inventario.movimientos")
            or m.tiene_permiso("compras.gestionar")
        ):
            destinatarios.append(m.usuario.email)

    total_alertas = len(productos) + len(existencias)
    asunto = f"Alerta de stock mínimo ({total_alertas} registro(s)) · {empresa.nombre}"
    lineas = [
        f"Hola equipo de {empresa.nombre},",
        "",
        "Los siguientes productos alcanzaron o están por debajo de su stock mínimo configurado:",
        "",
    ]
    for prod in productos:
        lineas.append(f"- {prod.codigo} · {prod.nombre}: stock actual {prod.stock} (mínimo {prod.stock_minimo})")
    for ex in existencias:
        lineas.append(
            f"- {ex.producto.codigo} · {ex.producto.nombre} (bodega {ex.bodega.nombre}): "
            f"stock actual {ex.cantidad} (mínimo {ex.stock_minimo})"
        )
    lineas.append("")
    lineas.append("Ingresa al panel de Inventario o Compras para reabastecerlos.")
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=destinatarios)


# ---------------------------------------------------------------------------
# Aviso al negocio: entró un pedido pagado
# ---------------------------------------------------------------------------
WHATSAPP_API = "https://graph.facebook.com/v21.0/{telefono_id}/messages"
WHATSAPP_TIMEOUT_S = 8


def correos_del_negocio(empresa):
    """Correo del negocio y de quienes pueden ver ventas en su equipo."""
    from .models import Membresia  # evita import circular con models

    correos = [empresa.email]
    miembros = (
        Membresia.objects.filter(empresa=empresa, activa=True, usuario__is_active=True)
        .select_related("usuario", "rol")
    )
    correos += [m.usuario.email for m in miembros if m.tiene_permiso("ventas.ver")]
    return correos


def telefono_whatsapp(telefono):
    """Celular colombiano en formato internacional (573001234567); None si no es celular."""
    digitos = "".join(c for c in (telefono or "") if c.isdigit())
    if len(digitos) == 12 and digitos.startswith("573"):
        return digitos
    if len(digitos) == 10 and digitos.startswith("3"):
        return "57" + digitos
    return None


def _enviar_whatsapp(pedido):
    """WhatsApp Cloud API con una plantilla aprobada por Meta. Si no está configurado, no hace nada."""
    import json
    import urllib.request

    token = settings.WHATSAPP_TOKEN
    telefono_id = settings.WHATSAPP_TELEFONO_ID
    plantilla = settings.WHATSAPP_PLANTILLA_PEDIDO
    destino = telefono_whatsapp(pedido.empresa.telefono)
    if not (token and telefono_id and plantilla and destino):
        return False
    cuerpo = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "template",
        "template": {
            "name": plantilla,
            "language": {"code": "es"},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(pedido.numero)},
                    {"type": "text", "text": f"$ {pedido.total:,.0f}".replace(",", ".")},
                    {"type": "text", "text": pedido.nombre[:60]},
                ],
            }],
        },
    }
    solicitud = urllib.request.Request(
        WHATSAPP_API.format(telefono_id=telefono_id),
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(solicitud, timeout=WHATSAPP_TIMEOUT_S) as respuesta:
            return 200 <= respuesta.status < 300
    except Exception:
        logger.warning("No se pudo enviar WhatsApp del pedido %s", pedido.numero, exc_info=True)
        return False


def notificar_negocio_pedido_pagado(pedido):
    """Avisa al negocio por correo (y WhatsApp si está configurado) que tiene un pedido pagado."""
    lineas = [
        "¡Tienes un pedido pagado en Intersoft!",
        "",
        f"Pedido #{pedido.numero} · Total cobrado: $ {pedido.total}",
        f"Neto para tu negocio: $ {pedido.neto_vendedor}",
        f"Cliente: {pedido.nombre} · {pedido.telefono}",
        f"Entrega: {pedido.direccion}, {pedido.ciudad} ({pedido.departamento})",
    ]
    if pedido.indicaciones:
        lineas.append(f"Indicaciones: {pedido.indicaciones}")
    lineas += ["", "Productos:"]
    lineas += [f"  · {linea.cantidad} × {linea.producto.nombre}" for linea in pedido.lineas.select_related("producto")]
    lineas += ["", "Prepáralo y actualiza el envío desde tu panel, en Pedidos web."]
    enviados = _enviar(
        asunto=f"Nuevo pedido pagado #{pedido.numero} · $ {pedido.total}",
        mensaje="\n".join(lineas),
        destinatarios=correos_del_negocio(pedido.empresa),
    )
    whatsapp = _enviar_whatsapp(pedido)
    return enviados, whatsapp
