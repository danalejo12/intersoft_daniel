"""Cobro de los planes con la cuenta de Wompi de Intersoft.

Flujo: el administrador elige un plan pago -> se crea un CobroSuscripcion con monto congelado ->
paga en el checkout de Wompi -> el plan se activa SOLO cuando el servidor confirma con Wompi el pago
(al volver, por el webhook firmado o por la conciliación periódica). Reutiliza la firma, la consulta
y la verificación de eventos de core.pagos: la misma lógica ya probada con los pedidos.
"""
import logging
import uuid
from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.pagos import (
    WompiNoResponde,
    buscar_transaccion_por_referencia,
    calcular_firma_integridad,
    consultar_transaccion,
    es_direccion_local,
)
from core.pasarelas import CredencialesWompi

from .models import CobroSuscripcion, Plan, Suscripcion
from .services import (
    CUPOS_FUNDADOR,
    DESCUENTO_FUNDADOR,
    DowngradeNoPermitido,
    _obtener_plan,
    cambiar_plan,
    crear_suscripcion_inicial,
    validar_limites,
)

logger = logging.getLogger(__name__)

Estado = CobroSuscripcion.Estado
ESPERA_ENTRE_CONSULTAS = timedelta(seconds=10)
# Un cobro sin transacción en Wompi después de este tiempo se anula (la persona no pagó)
VIGENCIA_COBRO_PENDIENTE = timedelta(hours=48)
ESTADOS_RECHAZO = {"DECLINED", "ERROR", "VOIDED"}


class CobroNoDisponible(Exception):
    """El mensaje se le muestra al administrador del negocio."""


def credenciales_intersoft() -> CredencialesWompi:
    publica = settings.SUSCRIPCIONES_WOMPI_PUBLIC_KEY
    integridad = settings.SUSCRIPCIONES_WOMPI_INTEGRITY_SECRET
    if not publica or not integridad:
        raise CobroNoDisponible(
            "El pago de planes en línea todavía no está habilitado. Escríbenos y activamos tu plan."
        )
    return CredencialesWompi(
        publica=publica,
        modo="pruebas" if publica.startswith("pub_test_") else "produccion",
        privada=settings.SUSCRIPCIONES_WOMPI_PRIVATE_KEY,
        integridad=integridad,
        eventos=settings.SUSCRIPCIONES_WOMPI_EVENTS_SECRET,
    )


def es_plan_pago(plan: Plan) -> bool:
    return plan.precio_mensual > 0 or plan.precio_anual > 0


def _normalizar_ciclo(ciclo) -> str:
    ciclo = str(ciclo or Suscripcion.Ciclo.MENSUAL).strip().upper()
    if ciclo not in Suscripcion.Ciclo.values:
        raise ValidationError(f"Ciclo de cobro no válido: '{ciclo}'. Usa MENSUAL o ANUAL.")
    return ciclo


def cotizar(suscripcion: Suscripcion, plan: Plan, ciclo: str) -> tuple[Decimal, Decimal, Decimal]:
    """(precio de lista, % de descuento, monto a cobrar). El descuento de fundador aplica a quien ya lo
    tiene y a quien todavía alcanza cupo; se congela en el cobro."""
    precio = plan.precio_anual if ciclo == Suscripcion.Ciclo.ANUAL else plan.precio_mensual
    if suscripcion.es_fundador:
        descuento = suscripcion.descuento_porcentaje
    elif Suscripcion.objects.filter(es_fundador=True).count() < CUPOS_FUNDADOR:
        descuento = DESCUENTO_FUNDADOR
    else:
        descuento = Decimal("0.00")
    monto = (precio * (Decimal("100") - descuento) / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return precio, descuento, monto


def iniciar_cobro(*, empresa, plan, ciclo, usuario) -> CobroSuscripcion:
    """Crea el cobro de un plan pago. No cambia la suscripción: eso pasa al confirmarse el pago."""
    plan = _obtener_plan(plan)
    ciclo = _normalizar_ciclo(ciclo)
    precio_ciclo = plan.precio_anual if ciclo == Suscripcion.Ciclo.ANUAL else plan.precio_mensual
    if precio_ciclo <= 0:
        raise ValidationError(f"El plan {plan.nombre} no tiene precio para el ciclo {ciclo.lower()}.")
    validar_limites(empresa, plan)  # antes de cobrar: no se cobra un plan al que no se puede pasar
    credenciales_intersoft()  # sin llaves no se crea un cobro que nadie podría pagar
    suscripcion = crear_suscripcion_inicial(empresa)
    precio, descuento, monto = cotizar(suscripcion, plan, ciclo)
    return CobroSuscripcion.objects.create(
        empresa=empresa,
        plan=plan,
        ciclo=ciclo,
        referencia=f"SUS-{uuid.uuid4().hex}",
        precio_lista=precio,
        descuento_porcentaje=descuento,
        monto=monto,
        creado_por=usuario,
    )


def url_pago(cobro: CobroSuscripcion, *, redirect_url: str) -> str:
    llaves = credenciales_intersoft()
    parametros = {
        "public-key": llaves.publica,
        "currency": cobro.moneda,
        "amount-in-cents": cobro.monto_centavos,
        "reference": cobro.referencia,
        "signature:integrity": calcular_firma_integridad(
            referencia=cobro.referencia, monto_centavos=cobro.monto_centavos,
            moneda=cobro.moneda, secreto=llaves.integridad,
        ),
    }
    if not es_direccion_local(redirect_url):
        parametros["redirect-url"] = redirect_url
    return f"{settings.WOMPI_CHECKOUT_URL}?{urlencode(parametros)}"


@transaction.atomic
def aplicar_transaccion(transaccion: dict) -> CobroSuscripcion | None:
    """Aplica lo que Wompi dice de una transacción (ya consultada desde el servidor). Idempotente."""
    referencia = transaccion.get("reference")
    if not isinstance(referencia, str):
        return None
    cobro = (CobroSuscripcion.objects.select_for_update().select_related("empresa", "plan")
             .filter(referencia=referencia).first())
    if cobro is None or cobro.estado in (Estado.APROBADO, Estado.REQUIERE_REVISION):
        return cobro

    estado_wompi = transaccion.get("status")
    ahora = timezone.now()
    if estado_wompi == "APPROVED":
        cobro.transaccion_id = str(transaccion.get("id") or "")[:60]
        cobro.metodo_pago = str(transaccion.get("payment_method_type") or "")[:30]
        cobro.resuelto_en = ahora
        if transaccion.get("amount_in_cents") != cobro.monto_centavos or transaccion.get("currency") != cobro.moneda:
            cobro.estado = Estado.REQUIERE_REVISION
            cobro.detalle = "Monto o moneda distintos a los del cobro"
            logger.critical("Cobro de plan %s: monto o moneda no coinciden; requiere revisión", cobro.referencia)
        else:
            try:
                with transaction.atomic():
                    cambiar_plan(
                        cobro.empresa, cobro.plan, cobro.ciclo,
                        motivo=f"Pago Wompi {cobro.referencia} ({cobro.get_ciclo_display()})",
                        forzar_fundador=cobro.descuento_porcentaje > 0,
                    )
            except (DowngradeNoPermitido, ValidationError) as error:
                cobro.estado = Estado.REQUIERE_REVISION
                cobro.detalle = f"Pago recibido sin activar: {error.messages[0] if error.messages else error}"[:255]
                logger.critical("Cobro de plan %s pagado pero no se pudo activar: %s", cobro.referencia, cobro.detalle)
            else:
                cobro.estado = Estado.APROBADO
                cobro.detalle = "Plan activado"
    elif estado_wompi in ESTADOS_RECHAZO:
        cobro.estado = Estado.RECHAZADO
        cobro.transaccion_id = str(transaccion.get("id") or "")[:60]
        cobro.detalle = str(transaccion.get("status_message") or estado_wompi)[:255]
        cobro.resuelto_en = ahora
    else:
        return cobro  # PENDING: Wompi todavía no decide
    cobro.save()
    return cobro


def sincronizar_cobro(cobro: CobroSuscripcion, *, transaccion_id: str = "", forzar: bool = False):
    """Le pregunta a Wompi por el cobro. Como mucho una consulta cada 10 s, salvo forzar."""
    if cobro.estado in (Estado.APROBADO, Estado.REQUIERE_REVISION):
        return cobro
    ahora = timezone.now()
    if not forzar and cobro.ultima_consulta_en and ahora - cobro.ultima_consulta_en < ESPERA_ENTRE_CONSULTAS:
        return cobro
    CobroSuscripcion.objects.filter(pk=cobro.pk).update(ultima_consulta_en=ahora)
    try:
        llaves = credenciales_intersoft()
    except CobroNoDisponible:
        return cobro
    transaccion = None
    if transaccion_id:
        transaccion = consultar_transaccion(transaccion_id, llaves=llaves)
        if transaccion and transaccion.get("reference") != cobro.referencia:
            transaccion = None  # un id de otra transacción no aprueba este cobro
    if transaccion is None:
        try:
            transaccion = buscar_transaccion_por_referencia(cobro.referencia, llaves=llaves)
        except WompiNoResponde:
            return cobro
    if transaccion:
        return aplicar_transaccion(transaccion) or cobro
    return cobro


def conciliar_pendientes() -> Counter:
    """Para la tarea periódica: consulta los cobros pendientes y anula los abandonados."""
    resultados = Counter()
    limite = timezone.now() - VIGENCIA_COBRO_PENDIENTE
    for cobro in CobroSuscripcion.objects.filter(estado=Estado.PENDIENTE).order_by("creado_en"):
        cobro = sincronizar_cobro(cobro, forzar=True)
        if cobro.estado == Estado.PENDIENTE and cobro.creado_en <= limite:
            CobroSuscripcion.objects.filter(pk=cobro.pk, estado=Estado.PENDIENTE).update(
                estado=Estado.ANULADO, resuelto_en=timezone.now(), detalle="Sin pago en Wompi")
            resultados["anulado"] += 1
        else:
            resultados[cobro.estado] += 1
    return resultados
