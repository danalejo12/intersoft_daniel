"""Notificaciones transaccionales por correo para compradores del marketplace."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)


def _limpiar_correos(correos):
    """Devuelve una lista de correos sin vacíos ni duplicados."""
    limpios = []
    for correo in correos or ():
        valor = (correo or "").strip()
        if valor and valor not in limpios:
            limpios.append(valor)
    return limpios


def _enviar(*, asunto, mensaje, destinatarios, html=None, reply_to=None, adjuntos=None):
    """Envía un correo (texto + HTML opcional, Reply-To y adjuntos) sin repetir destinatarios."""
    limpios = _limpiar_correos(destinatarios)
    if not limpios:
        return 0
    responder_a = _limpiar_correos(reply_to)
    if not responder_a and settings.DEFAULT_FROM_EMAIL:
        responder_a = [settings.DEFAULT_FROM_EMAIL]
    try:
        correo = EmailMultiAlternatives(
            subject=asunto,
            body=mensaje,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=limpios,
            reply_to=responder_a or None,
        )
        if html:
            correo.attach_alternative(html, "text/html")
        for nombre_archivo, contenido, tipo_mime in adjuntos or ():
            correo.attach(nombre_archivo, contenido, tipo_mime)
        return correo.send(fail_silently=False)
    except Exception:
        logger.warning("No se pudo enviar correo transaccional: %s", asunto, exc_info=True)
        return 0


def _correo_html(*, titulo, saludo, parrafos, detalles=None, boton_texto="", boton_url="", nota_pie=""):
    """Plantilla HTML limpia y segura (todo escapado) para correos transaccionales de InterSoft."""
    bloques_p = "".join(
        f'<p style="margin:0 0 12px;color:#334155;font-size:15px;line-height:1.55;">{escape(p)}</p>'
        for p in parrafos
    )
    bloque_detalles = ""
    if detalles:
        filas = "".join(
            f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">{escape(k)}</td>'
            f'<td style="padding:6px 0;color:#0f172a;font-size:13px;font-weight:600;text-align:right;">{escape(v)}</td></tr>'
            for k, v in detalles
        )
        bloque_detalles = (
            '<table role="presentation" style="width:100%;border-collapse:collapse;'
            'margin:16px 0;padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;">'
            f"{filas}</table>"
        )
    bloque_boton = ""
    if boton_texto and boton_url and boton_url.startswith(("http://", "https://")):
        bloque_boton = (
            '<p style="margin:20px 0 6px;">'
            f'<a href="{escape(boton_url)}" style="display:inline-block;padding:11px 20px;'
            'background:#2563eb;color:#ffffff;text-decoration:none;font-weight:600;'
            f'font-size:14px;border-radius:8px;">{escape(boton_texto)}</a></p>'
        )
    pie = nota_pie or "Correo enviado por InterSoft · Puedes responder directamente a este mensaje si necesitas ayuda."
    return (
        '<!doctype html><html lang="es"><body style="margin:0;padding:24px;background:#f1f5f9;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;'
        'border-radius:14px;padding:28px;">'
        '<p style="margin:0 0 10px;font-size:12px;font-weight:700;letter-spacing:0.06em;'
        'text-transform:uppercase;color:#2563eb;">InterSoft</p>'
        f'<h1 style="margin:0 0 14px;font-size:20px;color:#0f172a;">{escape(titulo)}</h1>'
        f'<p style="margin:0 0 12px;color:#0f172a;font-size:15px;">{escape(saludo)}</p>'
        f"{bloques_p}{bloque_detalles}{bloque_boton}"
        '<p style="margin:22px 0 0;padding-top:14px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:12px;">'
        f"{escape(pie)}"
        "</p></div></body></html>"
    )


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
    html = _correo_html(
        titulo=f"Pago confirmado · Pedido #{pedido.numero}",
        saludo=f"Hola {pedido.nombre},",
        parrafos=[
            f"Recibimos tu pago para el pedido #{pedido.numero}{factura_txt} en {pedido.empresa.nombre}.",
            "Te avisaremos por correo en cuanto el negocio despache tu envío.",
        ],
        detalles=[
            ("Negocio", pedido.empresa.nombre),
            ("Total pagado", f"$ {pedido.total}"),
            ("Entrega", f"{pedido.direccion}, {pedido.ciudad} ({pedido.departamento})"),
        ],
    )
    adjuntos = []
    if pedido.factura_id:
        try:
            from .exportaciones import generar_factura_pdf

            pdf_bytes = generar_factura_pdf(pedido.factura)
            adjuntos.append((f"factura-{pedido.factura.numero}.pdf", pdf_bytes, "application/pdf"))
        except Exception:
            logger.warning("No se pudo adjuntar PDF de factura del pedido %s", pedido.numero, exc_info=True)

    return _enviar(
        asunto=asunto,
        mensaje=mensaje,
        destinatarios=[pedido.email],
        html=html,
        reply_to=[pedido.empresa.email] if pedido.empresa.email else None,
        adjuntos=adjuntos,
    )


def notificar_bienvenida_usuario(usuario):
    """Envía correo de bienvenida HTML+texto al crear una cuenta nueva en InterSoft."""
    nombre = (usuario.first_name or "").strip() or usuario.email
    asunto = "¡Bienvenido a InterSoft! Tu cuenta ya está activa"
    mensaje = (
        f"Hola {nombre},\n\n"
        f"Gracias por registrarte en InterSoft con el correo {usuario.email}.\n"
        f"Ya puedes comprar en el marketplace, guardar favoritos, hacer seguimiento a tus pedidos "
        f"o registrar tu propio negocio cuando quieras.\n\n"
        f"Equipo InterSoft"
    )
    html = _correo_html(
        titulo="¡Bienvenido a InterSoft!",
        saludo=f"Hola {nombre},",
        parrafos=[
            f"Tu cuenta con el correo {usuario.email} fue creada con éxito.",
            "Ya puedes explorar tiendas, guardar favoritos, seguir tus pedidos en tiempo real o registrar tu propio negocio.",
        ],
        detalles=[
            ("Correo registrado", usuario.email),
            ("Estado", "Cuenta activa"),
        ],
    )
    return _enviar(asunto=asunto, mensaje=mensaje, destinatarios=[usuario.email], html=html)


def notificar_stock_disponible(producto):
    """Avisa por correo a todos los suscritos en AvisoStock cuando un producto vuelve a tener existencias."""
    from django.utils import timezone

    from .models import AvisoStock

    pendientes = list(AvisoStock.objects.filter(producto=producto, notificado=False))
    if not pendientes:
        return 0
    enviados = 0
    ahora = timezone.now()
    asunto = f"¡Volvió el stock! {producto.nombre} ya está disponible"
    precio_txt = f"$ {producto.precio_marketplace:,.0f}".replace(",", ".")
    for aviso in pendientes:
        mensaje = (
            f"Hola,\n\n"
            f"El producto «{producto.nombre}» de {producto.empresa.nombre} volvió a estar disponible.\n"
            f"Precio actual: {precio_txt}\n\n"
            f"Ingresa a InterSoft antes de que se agote nuevamente."
        )
        html = _correo_html(
            titulo=f"¡Volvió el stock de {producto.nombre}!",
            saludo="Hola,",
            parrafos=[
                f"El producto «{producto.nombre}» vendido por {producto.empresa.nombre} ya tiene unidades disponibles nuevamente.",
            ],
            detalles=[
                ("Producto", producto.nombre),
                ("Negocio", producto.empresa.nombre),
                ("Precio", precio_txt),
            ],
        )
        enviados += _enviar(
            asunto=asunto,
            mensaje=mensaje,
            destinatarios=[aviso.email],
            html=html,
            reply_to=[producto.empresa.email] if producto.empresa.email else None,
        )
    AvisoStock.objects.filter(pk__in=[a.pk for a in pendientes]).update(notificado=True, notificado_en=ahora)
    return enviados


def notificar_envio_actualizado(pedido):
    """Notifica al comprador cuando el pedido pasa a enviado o entregado, incluyendo enlace de rastreo."""
    if pedido.estado_envio not in ("enviado", "entregado"):
        return 0
    estado_txt = pedido.get_estado_envio_display()
    asunto = f"Actualización de envío · Pedido #{pedido.numero} ({estado_txt})"
    lineas = [
        f"Hola {pedido.nombre},",
        "",
        f"El estado de envío de tu pedido #{pedido.numero} en {pedido.empresa.nombre} ahora es: {estado_txt}.",
    ]
    detalles = [
        ("Pedido", f"#{pedido.numero}"),
        ("Negocio", pedido.empresa.nombre),
        ("Estado del envío", estado_txt),
    ]
    if pedido.transportadora:
        lineas.append(f"Transportadora: {pedido.transportadora}")
        detalles.append(("Transportadora", pedido.transportadora))
    if pedido.numero_guia:
        lineas.append(f"Número de guía: {pedido.numero_guia}")
        detalles.append(("Número de guía", pedido.numero_guia))
    rastreo = pedido.enlace_rastreo
    if rastreo:
        lineas.append(f"Rastrear envío: {rastreo}")
    html = _correo_html(
        titulo=f"Tu pedido #{pedido.numero}: {estado_txt}",
        saludo=f"Hola {pedido.nombre},",
        parrafos=[
            f"El estado de envío de tu pedido #{pedido.numero} en {pedido.empresa.nombre} cambió a {estado_txt}.",
        ],
        detalles=detalles,
        boton_texto="Rastrear envío" if rastreo else "",
        boton_url=rastreo,
    )
    return _enviar(
        asunto=asunto,
        mensaje="\n".join(lineas),
        destinatarios=[pedido.email],
        html=html,
        reply_to=[pedido.empresa.email] if pedido.empresa.email else None,
    )


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
    detalles = [
        ("Negocio", pedido.empresa.nombre),
        ("Comprobante", str(pedido.reembolso_referencia)),
        ("Monto reembolsado", f"$ {pedido.total}"),
    ]
    if pedido.reembolso_nota:
        lineas.append(f"Nota: {pedido.reembolso_nota}")
        detalles.append(("Nota", pedido.reembolso_nota))
    html = _correo_html(
        titulo=f"Reembolso procesado · Pedido #{pedido.numero}",
        saludo=f"Hola {pedido.nombre},",
        parrafos=[
            f"Hemos procesado el reembolso correspondiente a tu pedido #{pedido.numero} en {pedido.empresa.nombre}.",
        ],
        detalles=detalles,
    )
    return _enviar(
        asunto=asunto,
        mensaje="\n".join(lineas),
        destinatarios=[pedido.email],
        html=html,
        reply_to=[pedido.empresa.email] if pedido.empresa.email else None,
    )


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
    items = list(pedido.lineas.select_related("producto"))
    lineas += ["", "Productos:"]
    lineas += [f"  · {linea.cantidad} × {linea.producto.nombre}" for linea in items]
    lineas += ["", "Prepáralo y actualiza el envío desde tu panel, en Pedidos web."]
    detalles = [
        ("Pedido", f"#{pedido.numero}"),
        ("Total cobrado", f"$ {pedido.total}"),
        ("Neto para tu negocio", f"$ {pedido.neto_vendedor}"),
        ("Cliente", f"{pedido.nombre} · {pedido.telefono}"),
        ("Entrega", f"{pedido.direccion}, {pedido.ciudad} ({pedido.departamento})"),
    ]
    if pedido.indicaciones:
        detalles.append(("Indicaciones", pedido.indicaciones))
    parrafos = [
        "Tienes un nuevo pedido pagado listo para preparar desde tu panel en Pedidos web.",
        "Productos: " + ", ".join(f"{linea.cantidad} × {linea.producto.nombre}" for linea in items),
    ]
    html = _correo_html(
        titulo=f"Nuevo pedido pagado #{pedido.numero}",
        saludo=f"Hola equipo de {pedido.empresa.nombre},",
        parrafos=parrafos,
        detalles=detalles,
        nota_pie="Puedes responder directamente a este correo para escribirle al comprador.",
    )
    enviados = _enviar(
        asunto=f"Nuevo pedido pagado #{pedido.numero} · $ {pedido.total}",
        mensaje="\n".join(lineas),
        destinatarios=correos_del_negocio(pedido.empresa),
        html=html,
        reply_to=[pedido.email] if pedido.email else None,
    )
    whatsapp = _enviar_whatsapp(pedido)
    return enviados, whatsapp
