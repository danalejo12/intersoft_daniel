"""Servicios de dominio para radicación, conversación, estados, encuesta y escalamiento de PQRS."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .dias_habiles import sumar_dias_habiles
from .models import PQRS, MensajePQRS
from .notificaciones import (
    notificar_pqrs_estado,
    notificar_pqrs_radicada,
    notificar_pqrs_respuesta,
)


@transaction.atomic
def radicar_pqrs(
    *,
    autor,
    tipo: str,
    flujo: str,
    asunto: str,
    descripcion: str,
    empresa=None,
    pedido=None,
    adjunto=None,
    prioridad: str = PQRS.Prioridad.MEDIA,
) -> PQRS:
    """Radica una nueva PQRS generando radicado único y fecha límite en días hábiles."""
    if flujo == PQRS.Flujo.COMPRADOR_NEGOCIO:
        if pedido is not None:
            if pedido.comprador_id != autor.pk:
                raise ValidationError("Solo puedes radicar PQRS sobre tus propios pedidos.")
            empresa = pedido.empresa
        if empresa is None:
            raise ValidationError("Debes seleccionar el negocio o pedido para la PQRS.")
    elif flujo == PQRS.Flujo.NEGOCIO_INTERSOFT:
        if empresa is None:
            raise ValidationError("Toda PQRS del flujo Negocio → Intersoft requiere empresa.")

    dias_respuesta = getattr(settings, "PQRS_DIAS_RESPUESTA", 15)
    pqrs = PQRS(
        autor=autor,
        tipo=tipo,
        flujo=flujo,
        empresa=empresa,
        pedido=pedido,
        asunto=asunto.strip(),
        descripcion=descripcion.strip(),
        adjunto=adjunto,
        prioridad=prioridad,
        fecha_limite=sumar_dias_habiles(timezone.now(), dias_respuesta),
    )
    pqrs.full_clean()
    pqrs.save()
    notificar_pqrs_radicada(pqrs)
    return pqrs


@transaction.atomic
def agregar_mensaje_pqrs(
    pqrs: PQRS,
    *,
    autor,
    texto: str,
    adjunto=None,
    interno: bool = False,
    nuevo_estado: str | None = None,
) -> MensajePQRS:
    """Agrega un mensaje o nota interna a una PQRS y notifica por correo si es público."""
    texto_limpio = (texto or "").strip()
    if not texto_limpio:
        raise ValidationError("El texto del mensaje no puede estar vacío.")

    mensaje = MensajePQRS(
        pqrs=pqrs,
        autor=autor,
        texto=texto_limpio,
        adjunto=adjunto,
        interno=bool(interno),
    )
    mensaje.full_clean()
    mensaje.save()

    estado_anterior = pqrs.estado
    if nuevo_estado and nuevo_estado != pqrs.estado:
        ahora = timezone.now()
        pqrs.estado = nuevo_estado
        campos = ["estado", "actualizado_en"]
        if nuevo_estado == PQRS.Estado.RESPONDIDA and pqrs.respondida_en is None:
            pqrs.respondida_en = ahora
            campos.append("respondida_en")
        elif nuevo_estado == PQRS.Estado.CERRADA and pqrs.cerrada_en is None:
            pqrs.cerrada_en = ahora
            campos.append("cerrada_en")
        elif nuevo_estado == PQRS.Estado.ESCALADA and pqrs.escalada_en is None:
            pqrs.escalada_en = ahora
            campos.append("escalada_en")
        pqrs.save(update_fields=campos)
        notificar_pqrs_estado(pqrs, estado_anterior)

    if not mensaje.interno:
        notificar_pqrs_respuesta(pqrs, mensaje)

    return mensaje


@transaction.atomic
def cambiar_estado_pqrs(
    pqrs: PQRS,
    *,
    nuevo_estado: str,
    asignado_a=...,
    prioridad: str | None = None,
) -> PQRS:
    """Actualiza estado, prioridad o asignación de una PQRS y envía notificación si cambió de estado."""
    estado_anterior = pqrs.estado
    ahora = timezone.now()
    campos = []

    if nuevo_estado and nuevo_estado != pqrs.estado:
        pqrs.estado = nuevo_estado
        campos.append("estado")
        if nuevo_estado == PQRS.Estado.RESPONDIDA and pqrs.respondida_en is None:
            pqrs.respondida_en = ahora
            campos.append("respondida_en")
        elif nuevo_estado == PQRS.Estado.CERRADA and pqrs.cerrada_en is None:
            pqrs.cerrada_en = ahora
            campos.append("cerrada_en")
        elif nuevo_estado == PQRS.Estado.ESCALADA and pqrs.escalada_en is None:
            pqrs.escalada_en = ahora
            campos.append("escalada_en")

    if asignado_a is not ... and pqrs.asignado_a != asignado_a:
        pqrs.asignado_a = asignado_a
        campos.append("asignado_a")

    if prioridad and prioridad != pqrs.prioridad:
        pqrs.prioridad = prioridad
        campos.append("prioridad")

    if campos:
        campos.append("actualizado_en")
        pqrs.save(update_fields=campos)
        if "estado" in campos:
            notificar_pqrs_estado(pqrs, estado_anterior)

    return pqrs


@transaction.atomic
def registrar_encuesta_satisfaccion(
    pqrs: PQRS,
    *,
    calificacion: int,
    comentario: str = "",
) -> PQRS:
    """Cierra la PQRS (si aún no está cerrada) y guarda la calificación de satisfacción (1 a 5)."""
    try:
        puntaje = int(calificacion)
    except (TypeError, ValueError) as exc:
        raise ValidationError("La calificación debe ser un número entero entre 1 y 5.") from exc
    if puntaje < 1 or puntaje > 5:
        raise ValidationError("La calificación debe estar entre 1 y 5.")

    estado_anterior = pqrs.estado
    ahora = timezone.now()
    pqrs.calificacion = puntaje
    pqrs.comentario_satisfaccion = (comentario or "").strip()[:255]
    campos = ["calificacion", "comentario_satisfaccion", "actualizado_en"]
    if pqrs.estado != PQRS.Estado.CERRADA:
        pqrs.estado = PQRS.Estado.CERRADA
        pqrs.cerrada_en = ahora
        campos.extend(["estado", "cerrada_en"])
    pqrs.save(update_fields=campos)
    if estado_anterior != PQRS.Estado.CERRADA:
        notificar_pqrs_estado(pqrs, estado_anterior)
    return pqrs


def escalar_pqrs_vencidas(ahora=None) -> int:
    """Escala a Intersoft las PQRS de flujo B vencidas sin respuesta oportuna."""
    ahora = ahora or timezone.now()
    candidatas_ids = list(
        PQRS.objects.filter(
            flujo=PQRS.Flujo.COMPRADOR_NEGOCIO,
            estado__in=[PQRS.Estado.RADICADA, PQRS.Estado.EN_TRAMITE],
            fecha_limite__lt=ahora,
        ).values_list("pk", flat=True)
    )
    escaladas = 0
    for pqrs_id in candidatas_ids:
        with transaction.atomic():
            pqrs = PQRS.objects.select_for_update().filter(pk=pqrs_id).first()
            if (
                pqrs is None
                or pqrs.flujo != PQRS.Flujo.COMPRADOR_NEGOCIO
                or pqrs.estado not in (PQRS.Estado.RADICADA, PQRS.Estado.EN_TRAMITE)
                or pqrs.fecha_limite >= ahora
            ):
                continue
            estado_anterior = pqrs.estado
            pqrs.estado = PQRS.Estado.ESCALADA
            pqrs.escalada_en = ahora
            pqrs.save(update_fields=["estado", "escalada_en", "actualizado_en"])
            notificar_pqrs_estado(pqrs, estado_anterior)
            escaladas += 1
    return escaladas
