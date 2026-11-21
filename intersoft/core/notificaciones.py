"""Notificaciones transaccionales por correo para compradores del marketplace."""
from django.utils.translation import gettext
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
    factura_txt = gettext(" (Factura #{numero})").format(numero=pedido.factura.numero) if pedido.factura_id else ""
    asunto = gettext("Confirmación de pago · Pedido #{numero} en {nombre}").format(numero=pedido.numero, nombre=pedido.empresa.nombre)
    mensaje = (
        gettext("Hola {nombre},\n\nRecibimos tu pago para el pedido #{numero}{factura_txt} en {nombre2}.\nTotal pagado: $ {total}\nDirección de entrega: {direccion}, {ciudad} ({departamento}).\n\nTe avisaremos cuando tu pedido sea despachado.").format(nombre=pedido.nombre, numero=pedido.numero, factura_txt=factura_txt, nombre2=pedido.empresa.nombre, total=pedido.total, direccion=pedido.direccion, ciudad=pedido.ciudad, departamento=pedido.departamento)
    )
    return _enviar(asunto=asunto, mensaje=mensaje, destinatarios=[pedido.email])


def notificar_envio_actualizado(pedido):
    """Notifica al comprador cuando el pedido pasa a enviado o entregado."""
    if pedido.estado_envio not in ("enviado", "entregado"):
        return 0
    asunto = gettext("Actualización de envío · Pedido #{numero} ({get_estado_envio_display})").format(numero=pedido.numero, get_estado_envio_display=pedido.get_estado_envio_display())
    lineas = [
        gettext("Hola {nombre},").format(nombre=pedido.nombre),
        "",
        gettext("El estado de envío de tu pedido #{numero} en {nombre} ahora es: {get_estado_envio_display}.").format(numero=pedido.numero, nombre=pedido.empresa.nombre, get_estado_envio_display=pedido.get_estado_envio_display()),
    ]
    if pedido.transportadora:
        lineas.append(gettext("Transportadora: {transportadora}").format(transportadora=pedido.transportadora))
    if pedido.numero_guia:
        lineas.append(gettext("Número de guía: {numero_guia}").format(numero_guia=pedido.numero_guia))
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=[pedido.email])


def notificar_reembolso_registrado(pedido):
    """Notifica al comprador cuando se registra el reembolso de su pedido."""
    asunto = gettext("Reembolso procesado · Pedido #{numero} en {nombre}").format(numero=pedido.numero, nombre=pedido.empresa.nombre)
    lineas = [
        gettext("Hola {nombre},").format(nombre=pedido.nombre),
        "",
        gettext("Hemos procesado el reembolso correspondiente al pedido #{numero} en {nombre}.").format(numero=pedido.numero, nombre=pedido.empresa.nombre),
        gettext("Comprobante de reembolso: {reembolso_referencia}").format(reembolso_referencia=pedido.reembolso_referencia),
        gettext("Monto del pedido: $ {total}").format(total=pedido.total),
    ]
    if pedido.reembolso_nota:
        lineas.append(gettext("Nota: {reembolso_nota}").format(reembolso_nota=pedido.reembolso_nota))
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
    asunto = gettext("Alerta de stock mínimo ({total_alertas} registro(s)) · {nombre}").format(total_alertas=total_alertas, nombre=empresa.nombre)
    lineas = [
        gettext("Hola equipo de {nombre},").format(nombre=empresa.nombre),
        "",
        gettext("Los siguientes productos alcanzaron o están por debajo de su stock mínimo configurado:"),
        "",
    ]
    for prod in productos:
        lineas.append(gettext("- {codigo} · {nombre}: stock actual {stock} (mínimo {stock_minimo})").format(codigo=prod.codigo, nombre=prod.nombre, stock=prod.stock, stock_minimo=prod.stock_minimo))
    for ex in existencias:
        lineas.append(
            gettext("- {codigo} · {nombre} (bodega {nombre2}): stock actual {cantidad} (mínimo {stock_minimo})").format(codigo=ex.producto.codigo, nombre=ex.producto.nombre, nombre2=ex.bodega.nombre, cantidad=ex.cantidad, stock_minimo=ex.stock_minimo)
        )
    lineas.append("")
    lineas.append(gettext("Ingresa al panel de Inventario o Compras para reabastecerlos."))
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
        gettext("¡Tienes un pedido pagado en Intersoft!"),
        "",
        gettext("Pedido #{numero} · Total cobrado: $ {total}").format(numero=pedido.numero, total=pedido.total),
        gettext("Neto para tu negocio: $ {neto_vendedor}").format(neto_vendedor=pedido.neto_vendedor),
        gettext("Cliente: {nombre} · {telefono}").format(nombre=pedido.nombre, telefono=pedido.telefono),
        gettext("Entrega: {direccion}, {ciudad} ({departamento})").format(direccion=pedido.direccion, ciudad=pedido.ciudad, departamento=pedido.departamento),
    ]
    if pedido.indicaciones:
        lineas.append(gettext("Indicaciones: {indicaciones}").format(indicaciones=pedido.indicaciones))
    lineas += ["", gettext("Productos:")]
    lineas += [f"  · {linea.cantidad} × {linea.producto.nombre}" for linea in pedido.lineas.select_related("producto")]
    lineas += ["", gettext("Prepáralo y actualiza el envío desde tu panel, en Pedidos web.")]
    enviados = _enviar(
        asunto=gettext("Nuevo pedido pagado #{numero} · $ {total}").format(numero=pedido.numero, total=pedido.total),
        mensaje="\n".join(lineas),
        destinatarios=correos_del_negocio(pedido.empresa),
    )
    whatsapp = _enviar_whatsapp(pedido)
    return enviados, whatsapp
