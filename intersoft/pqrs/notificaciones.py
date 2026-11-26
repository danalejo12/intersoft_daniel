"""Notificaciones por correo electrónico (HTML + texto y Reply-To) para el ciclo de vida de PQRS."""
from core.notificaciones import _correo_html, _enviar, correos_del_negocio


def _destinatarios_empresa(pqrs) -> list[str]:
    """Correos del negocio de la PQRS (vacío si es una PQRS hacia Intersoft sin empresa)."""
    if pqrs.empresa_id is None:
        return []
    return correos_del_negocio(pqrs.empresa)


def notificar_pqrs_radicada(pqrs) -> int:
    """Envía confirmación HTML+texto al autor de la PQRS y avisa al negocio si es flujo B."""
    asunto = f"[{pqrs.radicado}] PQRS radicada: {pqrs.asunto}"
    fecha_txt = pqrs.fecha_limite.strftime("%d/%m/%Y %H:%M")
    mensaje = (
        f"Hola,\n\n"
        f"Tu solicitud ha sido radicada con éxito.\n"
        f"Radicado: {pqrs.radicado}\n"
        f"Tipo: {pqrs.get_tipo_display()}\n"
        f"Asunto: {pqrs.asunto}\n"
        f"Estado actual: {pqrs.get_estado_display()}\n"
        f"Fecha límite estimada de respuesta: {fecha_txt}\n"
    )
    reply_autor = (
        [pqrs.empresa.email]
        if pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO and pqrs.empresa_id and pqrs.empresa.email
        else None
    )
    html_autor = _correo_html(
        titulo=f"PQRS radicada · {pqrs.radicado}",
        saludo=f"Hola {pqrs.autor.first_name or pqrs.autor.email},",
        parrafos=[
            "Tu solicitud fue registrada correctamente y ya está en seguimiento.",
        ],
        detalles=[
            ("Radicado", pqrs.radicado),
            ("Tipo", pqrs.get_tipo_display()),
            ("Asunto", pqrs.asunto),
            ("Estado actual", pqrs.get_estado_display()),
            ("Fecha límite de respuesta", fecha_txt),
        ],
    )
    enviados = _enviar(
        asunto=asunto,
        mensaje=mensaje,
        destinatarios=[pqrs.autor.email],
        html=html_autor,
        reply_to=reply_autor,
    )

    if pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO:
        correos_neg = _destinatarios_empresa(pqrs)
        if correos_neg:
            asunto_neg = f"[{pqrs.radicado}] Nueva PQRS de comprador · {pqrs.empresa.nombre}"
            mensaje_neg = (
                f"Hola equipo de {pqrs.empresa.nombre},\n\n"
                f"Un comprador radicó una nueva PQRS.\n"
                f"Radicado: {pqrs.radicado}\n"
                f"Asunto: {pqrs.asunto}\n"
                f"Fecha límite para responder antes de escalar a Intersoft: {fecha_txt}\n"
                f"Ingresa a /panel/pqrs/ para gestionarla.\n"
            )
            html_neg = _correo_html(
                titulo=f"Nueva PQRS recibida · {pqrs.radicado}",
                saludo=f"Hola equipo de {pqrs.empresa.nombre},",
                parrafos=[
                    "Un comprador radicó una nueva PQRS. Responde desde /panel/pqrs/ antes de la fecha límite para evitar escalamiento.",
                ],
                detalles=[
                    ("Radicado", pqrs.radicado),
                    ("Tipo", pqrs.get_tipo_display()),
                    ("Asunto", pqrs.asunto),
                    ("Comprador", pqrs.autor.get_full_name() or pqrs.autor.email),
                    ("Fecha límite", fecha_txt),
                ],
                nota_pie="Puedes gestionar la respuesta en /panel/pqrs/ o responder directamente a este correo.",
            )
            enviados += _enviar(
                asunto=asunto_neg,
                mensaje=mensaje_neg,
                destinatarios=correos_neg,
                html=html_neg,
                reply_to=[pqrs.autor.email],
            )
    return enviados


def notificar_pqrs_estado(pqrs, estado_anterior: str = "") -> int:
    """Notifica por correo HTML+texto el cambio de estado de una PQRS."""
    asunto = f"[{pqrs.radicado}] Cambio de estado: {pqrs.get_estado_display()}"
    lineas = [
        "Hola,",
        "",
        f"Tu PQRS {pqrs.radicado} ({pqrs.asunto}) cambió de estado.",
    ]
    detalles = [
        ("Radicado", pqrs.radicado),
        ("Asunto", pqrs.asunto),
    ]
    if estado_anterior:
        lineas.append(f"Estado anterior: {estado_anterior}")
        detalles.append(("Estado anterior", estado_anterior))
    lineas.append(f"Estado actual: {pqrs.get_estado_display()}")
    detalles.append(("Estado actual", pqrs.get_estado_display()))
    parrafos = [f"El estado de la PQRS {pqrs.radicado} se actualizó a {pqrs.get_estado_display()}."]
    if pqrs.estado == pqrs.Estado.ESCALADA:
        aviso = "La solicitud venció sin respuesta oportuna y fue escalada al equipo de Intersoft."
        lineas.append(aviso)
        parrafos.append(aviso)
    destinatarios = [pqrs.autor.email]
    if pqrs.estado == pqrs.Estado.ESCALADA and pqrs.empresa_id:
        destinatarios.extend(_destinatarios_empresa(pqrs))
    html = _correo_html(
        titulo=f"Actualización de PQRS · {pqrs.radicado}",
        saludo="Hola,",
        parrafos=parrafos,
        detalles=detalles,
    )
    reply_a = (
        [pqrs.empresa.email]
        if pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO and pqrs.empresa_id and pqrs.empresa.email
        else None
    )
    return _enviar(
        asunto=asunto,
        mensaje="\n".join(lineas),
        destinatarios=destinatarios,
        html=html,
        reply_to=reply_a,
    )


def notificar_pqrs_respuesta(pqrs, mensaje_pqrs) -> int:
    """Envía correo HTML+texto con Reply-To cuando hay una respuesta pública (nunca por notas internas)."""
    if mensaje_pqrs.interno:
        return 0

    asunto = f"[{pqrs.radicado}] Nueva respuesta en tu PQRS"
    cuerpo = (
        f"Hola,\n\n"
        f"Hay un nuevo mensaje en la PQRS {pqrs.radicado} ({pqrs.asunto}):\n\n"
        f"{mensaje_pqrs.texto}\n\n"
        f"Estado actual: {pqrs.get_estado_display()}\n"
    )
    if mensaje_pqrs.autor_id == pqrs.autor_id and pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO:
        destinatarios = _destinatarios_empresa(pqrs)
        reply_a = [pqrs.autor.email]
    else:
        destinatarios = [pqrs.autor.email]
        reply_a = (
            [pqrs.empresa.email]
            if pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO and pqrs.empresa_id and pqrs.empresa.email
            else None
        )
    html = _correo_html(
        titulo=f"Nueva respuesta en PQRS · {pqrs.radicado}",
        saludo="Hola,",
        parrafos=[
            f"Hay una nueva respuesta en la solicitud {pqrs.radicado} ({pqrs.asunto}):",
            mensaje_pqrs.texto,
        ],
        detalles=[
            ("Radicado", pqrs.radicado),
            ("Estado actual", pqrs.get_estado_display()),
        ],
    )
    return _enviar(
        asunto=asunto,
        mensaje=cuerpo,
        destinatarios=destinatarios,
        html=html,
        reply_to=reply_a,
    )
