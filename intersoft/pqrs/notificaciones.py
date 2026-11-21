"""Notificaciones por correo electrónico para eventos del ciclo de vida de PQRS."""
from django.utils.translation import gettext
from core.notificaciones import _enviar, correos_del_negocio


def _destinatarios_empresa(pqrs) -> list[str]:
    if pqrs.empresa_id is None:
        return []
    return correos_del_negocio(pqrs.empresa)


def notificar_pqrs_radicada(pqrs) -> int:
    """Envía confirmación al autor de la PQRS y avisa al negocio si es flujo B."""
    asunto = gettext("[{radicado}] PQRS radicada: {asunto}").format(radicado=pqrs.radicado, asunto=pqrs.asunto)
    fecha_txt = pqrs.fecha_limite.strftime("%d/%m/%Y %H:%M")
    mensaje = (
        gettext("Hola,\n\nTu solicitud ha sido radicada con éxito.\nRadicado: {radicado}\nTipo: {get_tipo_display}\nAsunto: {asunto}\nEstado actual: {get_estado_display}\nFecha límite estimada de respuesta: {fecha_txt}\n").format(radicado=pqrs.radicado, get_tipo_display=pqrs.get_tipo_display(), asunto=pqrs.asunto, get_estado_display=pqrs.get_estado_display(), fecha_txt=fecha_txt)
    )
    enviados = _enviar(asunto=asunto, mensaje=mensaje, destinatarios=[pqrs.autor.email])

    if pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO:
        correos_neg = _destinatarios_empresa(pqrs)
        if correos_neg:
            asunto_neg = gettext("[{radicado}] Nueva PQRS de comprador · {nombre}").format(radicado=pqrs.radicado, nombre=pqrs.empresa.nombre)
            mensaje_neg = (
                gettext("Hola equipo de {nombre},\n\nUn comprador radicó una nueva PQRS.\nRadicado: {radicado}\nAsunto: {asunto}\nFecha límite para responder antes de escalar a Intersoft: {fecha_txt}\nIngresa a /panel/pqrs/ para gestionarla.\n").format(nombre=pqrs.empresa.nombre, radicado=pqrs.radicado, asunto=pqrs.asunto, fecha_txt=fecha_txt)
            )
            enviados += _enviar(asunto=asunto_neg, mensaje=mensaje_neg, destinatarios=correos_neg)
    return enviados


def notificar_pqrs_estado(pqrs, estado_anterior: str = "") -> int:
    """Notifica por correo el cambio de estado de una PQRS."""
    asunto = gettext("[{radicado}] Cambio de estado: {get_estado_display}").format(radicado=pqrs.radicado, get_estado_display=pqrs.get_estado_display())
    lineas = [
        gettext("Hola,"),
        "",
        gettext("Tu PQRS {radicado} ({asunto}) cambió de estado.").format(radicado=pqrs.radicado, asunto=pqrs.asunto),
    ]
    if estado_anterior:
        lineas.append(gettext("Estado anterior: {estado_anterior}").format(estado_anterior=estado_anterior))
    lineas.append(gettext("Estado actual: {get_estado_display}").format(get_estado_display=pqrs.get_estado_display()))
    if pqrs.estado == pqrs.Estado.ESCALADA:
        lineas.append(
            gettext("La solicitud venció sin respuesta oportuna y fue escalada al equipo de Intersoft.")
        )
    destinatarios = [pqrs.autor.email]
    if pqrs.estado == pqrs.Estado.ESCALADA and pqrs.empresa_id:
        destinatarios.extend(_destinatarios_empresa(pqrs))
    return _enviar(asunto=asunto, mensaje="\n".join(lineas), destinatarios=destinatarios)


def notificar_pqrs_respuesta(pqrs, mensaje_pqrs) -> int:
    """Envía correo cuando hay una respuesta pública (nunca por notas internas)."""
    if mensaje_pqrs.interno:
        return 0

    asunto = gettext("[{radicado}] Nueva respuesta en tu PQRS").format(radicado=pqrs.radicado)
    cuerpo = (
        gettext("Hola,\n\nHay un nuevo mensaje en la PQRS {radicado} ({asunto}):\n\n{texto}\n\nEstado actual: {get_estado_display}\n").format(radicado=pqrs.radicado, asunto=pqrs.asunto, texto=mensaje_pqrs.texto, get_estado_display=pqrs.get_estado_display())
    )
    if mensaje_pqrs.autor_id == pqrs.autor_id and pqrs.flujo == pqrs.Flujo.COMPRADOR_NEGOCIO:
        destinatarios = _destinatarios_empresa(pqrs)
    else:
        destinatarios = [pqrs.autor.email]
    return _enviar(asunto=asunto, mensaje=cuerpo, destinatarios=destinatarios)
