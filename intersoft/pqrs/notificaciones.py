"""Notificaciones por correo electrónico para eventos del ciclo de vida de PQRS."""
from core.notificaciones import _enviar, correos_del_negocio


def _destinatarios_empresa(pqrs) -> list[str]:
    if pqrs.empresa_id is None:
        return []
    return correos_del_negocio(pqrs.empresa)


def notificar_pqrs_radicada(pqrs) -> int:
    """Envía confirmación al autor de la PQRS y avisa al negocio si es flujo B."""
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
    enviados = _enviar(asunto=asunto, mensaje=mensaje, destinatarios=[pqrs.autor.email])

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
            enviados += _enviar(asunto=asunto_neg, mensaje=mensaje_neg, destinatarios=correos_neg)
    return enviados


def notificar_pqrs_estado(pqrs, estado_anterior: str = "") -> int:
    """Notifica por correo el cambio de estado de una PQRS."""
    asunto = f"[{pqrs.radicado}] Cambio de estado: {pqrs.get_estado_display()}"
    lineas = [
        "Hola,",
        "",
        f"Tu PQRS {pqrs.radicado} ({pqrs.asunto}) cambió de estado.",
    ]
    if estado_anterior:
        lineas.append(f"Estado anterior: {estado_anterior}")
    lineas.append(f"Estado actual: {pqrs.get_estado_display()}")
    if pqrs.estado == pqrs.Estado.ESCALADA:
        lineas.append(
            "La solicitud venció sin respuesta oportuna y fue escalada al equipo de Intersoft."
        )
    destinatarios = [pqrs.autor.email]
    if pqrs.estado == pqrs.Estado.ESCALADA and pqrs.empresa_id:
        destinatarios.extend(_destinatarios_empresa(pqrs))
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=destinatarios)


def notificar_pqrs_respuesta(pqrs, mensaje_pqrs) -> int:
    """Envía correo cuando hay una respuesta pública (nunca por notas internas)."""
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
    else:
        destinatarios = [pqrs.autor.email]
    return _enviar(asunto=asunto, mensaje=cuerpo, destinatarios=destinatarios)
