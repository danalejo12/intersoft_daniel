"""Capa de servicios de negocio para planes, suscripciones, límites y comisiones.

Toda la lógica de dominio vive aquí (nunca en vistas ni serializers) para que
pueda invocarse por igual desde endpoints DRF, comandos de gestión, señales o tests.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import Empresa, Membresia, Producto

from .models import (
    ConfiguracionSuscripciones,
    HistorialSuscripcion,
    Plan,
    RecordatorioVencimiento,
    Suscripcion,
)

CENTAVOS = Decimal("0.01")
DIAS_TRIAL = 14
DIAS_CICLO_MENSUAL = 30
DIAS_CICLO_ANUAL = 365
CUPOS_FUNDADOR = 50
DESCUENTO_FUNDADOR = Decimal("50.00")


def cupos_fundador_actuales() -> int:
    """Devuelve el límite vigente de cupos de fundador desde la base de datos (con respaldo en 50)."""
    return ConfiguracionSuscripciones.obtener_cupos_fundador(CUPOS_FUNDADOR)


class CanalVenta:
    MARKETPLACE = "MARKETPLACE"
    POS = "POS"
    VALORES = (MARKETPLACE, POS)


class DowngradeNoPermitido(ValidationError):
    """Se lanza cuando una empresa intenta bajar a un plan cuyos límites son menores a su uso actual."""

    def __init__(self, mensaje, *, excesos=None):
        super().__init__(mensaje)
        self.excesos = excesos or {}


def _obtener_plan(plan_o_codigo) -> Plan:
    if isinstance(plan_o_codigo, Plan):
        return plan_o_codigo
    codigo = str(plan_o_codigo or "").strip().lower()
    try:
        return Plan.objects.get(codigo=codigo, activo=True)
    except Plan.DoesNotExist as exc:
        raise ValidationError(f"El plan '{codigo}' no existe o no está activo.") from exc


def uso_actual(empresa: Empresa) -> dict:
    """Calcula el consumo actual de recursos sujetos a límite de plan para una empresa.

    Punto de extensión:
    - Si en el futuro se agregan modelos como `Sede` (multisede), basta añadir aquí
      la clave `"sedes": Sede.objects.filter(empresa=empresa, activa=True).count()`.
    """
    return {
        "productos": Producto.objects.filter(empresa=empresa, activo=True).count(),
        "usuarios": Membresia.objects.filter(empresa=empresa, activa=True).count(),
    }


@transaction.atomic
def crear_suscripcion_inicial(empresa: Empresa) -> Suscripcion:
    """Crea de forma idempotente la suscripción inicial en TRIAL del plan 'negocio' por 14 días."""
    existente = (
        Suscripcion.objects.select_related("plan")
        .filter(empresa=empresa)
        .first()
    )
    if existente is not None:
        return existente

    # Bloqueamos la fila de la empresa para evitar condiciones de carrera si señal y servicio corren a la vez
    Empresa.objects.select_for_update().filter(pk=empresa.pk).first()
    existente = (
        Suscripcion.objects.select_related("plan")
        .filter(empresa=empresa)
        .first()
    )
    if existente is not None:
        return existente

    plan_negocio = Plan.objects.filter(codigo="negocio").first()
    if plan_negocio is None:
        # Respaldo defensivo por si se invoca antes de correr la migración de datos en un entorno parcial
        plan_negocio, _ = Plan.objects.get_or_create(
            codigo="negocio",
            defaults={
                "nombre": "Negocio",
                "precio_mensual": Decimal("69900.00"),
                "precio_anual": Decimal("699000.00"),
                "comision_porcentaje": Decimal("2.50"),
                "limites": {"productos": None, "usuarios": 5},
                "features": [
                    "marketplace",
                    "marketplace_destacado",
                    "pos",
                    "inventario",
                    "alertas_inventario",
                    "roles",
                    "reportes_basicos",
                    "reportes_avanzados",
                ],
                "orden": 3,
                "activo": True,
            },
        )

    ahora = timezone.now()
    suscripcion = Suscripcion.objects.create(
        empresa=empresa,
        plan=plan_negocio,
        estado=Suscripcion.Estado.TRIAL,
        ciclo=Suscripcion.Ciclo.MENSUAL,
        inicia_en=ahora,
        vence_en=ahora + timedelta(days=DIAS_TRIAL),
        es_fundador=False,
        descuento_porcentaje=Decimal("0.00"),
    )
    HistorialSuscripcion.objects.create(
        suscripcion=suscripcion,
        plan_anterior=None,
        plan_nuevo=plan_negocio,
        estado_anterior="",
        estado_nuevo=Suscripcion.Estado.TRIAL,
        motivo=f"Inicio de prueba gratis por {DIAS_TRIAL} días en plan {plan_negocio.nombre}",
        fecha=ahora,
    )
    return suscripcion


def validar_limites(empresa: Empresa, plan_destino: Plan) -> None:
    """Lanza DowngradeNoPermitido si el uso actual de la empresa no cabe en el plan destino."""
    consumo = uso_actual(empresa)
    limites_destino = plan_destino.limites or {}
    detalles_exceso = []
    excesos_dict = {}
    for recurso, cantidad_actual in consumo.items():
        limite_recurso = limites_destino.get(recurso)
        if limite_recurso is not None and int(cantidad_actual) > int(limite_recurso):
            sobrante = int(cantidad_actual) - int(limite_recurso)
            excesos_dict[recurso] = {
                "uso_actual": int(cantidad_actual),
                "limite": int(limite_recurso),
                "exceso": sobrante,
            }
            detalles_exceso.append(
                f"tienes {cantidad_actual} {recurso} y el plan {plan_destino.nombre} permite máximo {limite_recurso} "
                f"(debes reducir al menos {sobrante})"
            )

    if detalles_exceso:
        mensaje = (
            f"No puedes cambiar al plan {plan_destino.nombre} porque tu uso actual excede sus límites: "
            + "; ".join(detalles_exceso)
            + "."
        )
        raise DowngradeNoPermitido(mensaje, excesos=excesos_dict)


@transaction.atomic
def cambiar_plan(
    empresa: Empresa,
    plan,
    ciclo: str = Suscripcion.Ciclo.MENSUAL,
    motivo: str = "",
    forzar_fundador: bool = False,
) -> Suscripcion:
    """Cambia el plan de una empresa validando límites de downgrade, beneficio fundador y auditoría.

    Si se paga el mismo plan y ciclo que siguen vigentes (renovación), los días se suman al vencimiento
    actual: quien renueva antes de tiempo no pierde días. forzar_fundador respeta el descuento con el
    que ya se cobró, aunque los cupos se hayan llenado mientras la persona pagaba."""
    ciclo_normalizado = str(ciclo or Suscripcion.Ciclo.MENSUAL).strip().upper()
    if ciclo_normalizado not in Suscripcion.Ciclo.values:
        raise ValidationError(f"Ciclo de cobro no válido: '{ciclo}'. Usa MENSUAL o ANUAL.")

    plan_destino = _obtener_plan(plan)
    crear_suscripcion_inicial(empresa)
    suscripcion = (
        Suscripcion.objects.select_for_update()
        .select_related("plan")
        .get(empresa=empresa)
    )

    # 1. Validar que el uso actual quepa dentro de los límites del nuevo plan (protección en downgrade)
    validar_limites(empresa, plan_destino)

    plan_anterior = suscripcion.plan
    estado_anterior = suscripcion.estado
    ahora = timezone.now()

    # 2. Determinar estado, ciclo, fecha de vencimiento y beneficio de fundador (primeras 50 empresas con plan pago)
    es_plan_pago = plan_destino.precio_mensual > Decimal("0.00") or plan_destino.precio_anual > Decimal("0.00")
    if es_plan_pago:
        dias_vigencia = (
            DIAS_CICLO_ANUAL if ciclo_normalizado == Suscripcion.Ciclo.ANUAL else DIAS_CICLO_MENSUAL
        )
        es_renovacion = (
            suscripcion.plan_id == plan_destino.pk
            and suscripcion.estado == Suscripcion.Estado.ACTIVA
            and suscripcion.ciclo == ciclo_normalizado
            and suscripcion.vence_en is not None
            and suscripcion.vence_en > ahora
        )
        base_vigencia = suscripcion.vence_en if es_renovacion else ahora
        nuevo_vence_en = base_vigencia + timedelta(days=dias_vigencia)
        if forzar_fundador and not suscripcion.es_fundador:
            suscripcion.es_fundador = True
            suscripcion.descuento_porcentaje = DESCUENTO_FUNDADOR
        elif not suscripcion.es_fundador:
            total_fundadores = (
                Suscripcion.objects.select_for_update()
                .filter(es_fundador=True)
                .count()
            )
            if total_fundadores < cupos_fundador_actuales():
                suscripcion.es_fundador = True
                suscripcion.descuento_porcentaje = DESCUENTO_FUNDADOR
    else:
        es_renovacion = False
        nuevo_vence_en = None

    nuevo_estado = Suscripcion.Estado.ACTIVA
    suscripcion.plan = plan_destino
    suscripcion.estado = nuevo_estado
    suscripcion.ciclo = ciclo_normalizado
    if not es_renovacion:
        suscripcion.inicia_en = ahora
    suscripcion.vence_en = nuevo_vence_en
    suscripcion.save(
        update_fields=[
            "plan",
            "estado",
            "ciclo",
            "inicia_en",
            "vence_en",
            "es_fundador",
            "descuento_porcentaje",
            "actualizado_en",
        ]
    )

    HistorialSuscripcion.objects.create(
        suscripcion=suscripcion,
        plan_anterior=plan_anterior,
        plan_nuevo=plan_destino,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        motivo=(motivo or f"Cambio manual a plan {plan_destino.nombre} ({ciclo_normalizado})")[:255],
        fecha=ahora,
    )
    empresa.suscripcion = suscripcion
    return suscripcion


def calcular_comision(empresa: Empresa, monto, canal: str) -> Decimal:
    """Calcula la comisión en COP según el canal de venta y el plan vigente de la empresa.

    Reglas:
    - Canal POS: comisión 0.00 siempre.
    - Canal MARKETPLACE: aplica el porcentaje del plan vigente de la empresa con redondeo ROUND_HALF_UP.
    - Rechaza valores tipo float para garantizar exactitud financiera.
    """
    if isinstance(monto, float):
        raise TypeError("El monto debe ser Decimal, int o cadena numérica, nunca float.")
    monto_dec = Decimal(str(monto))
    if monto_dec < Decimal("0.00"):
        raise ValueError("El monto no puede ser negativo.")

    canal_norm = str(canal or "").strip().upper()
    if canal_norm not in CanalVenta.VALORES:
        raise ValueError(f"Canal de venta no válido: '{canal}'. Usa MARKETPLACE o POS.")

    if canal_norm == CanalVenta.POS or monto_dec == Decimal("0.00"):
        return Decimal("0.00")

    suscripcion = (
        Suscripcion.objects.select_related("plan").filter(empresa=empresa).first()
        or crear_suscripcion_inicial(empresa)
    )
    porcentaje = suscripcion.plan.comision_porcentaje
    comision = (monto_dec * porcentaje) / Decimal("100")
    return comision.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def verificar_vencimientos() -> dict:
    """Pasa al plan 'gratis' todas las suscripciones TRIAL o ACTIVAS cuyo vence_en ya expiró.

    Nunca bloquea la cuenta: la empresa pasa a estado ACTIVA en el plan 'gratis'.
    Es 100% idempotente para ejecutarse periódicamente desde cron.
    """
    ahora = timezone.now()
    plan_gratis = _obtener_plan("gratis")

    vencidas_ids = list(
        Suscripcion.objects.filter(
            estado__in=[Suscripcion.Estado.TRIAL, Suscripcion.Estado.ACTIVA],
            vence_en__isnull=False,
            vence_en__lte=ahora,
        )
        .exclude(plan=plan_gratis, estado=Suscripcion.Estado.ACTIVA, vence_en__isnull=True)
        .values_list("pk", flat=True)
    )

    trials_vencidos = 0
    activas_vencidas = 0

    for sub_id in vencidas_ids:
        with transaction.atomic():
            sub = (
                Suscripcion.objects.select_for_update()
                .select_related("plan")
                .filter(pk=sub_id)
                .first()
            )
            if sub is None or sub.vence_en is None or sub.vence_en > ahora:
                continue
            if sub.estado not in (Suscripcion.Estado.TRIAL, Suscripcion.Estado.ACTIVA):
                continue

            plan_anterior = sub.plan
            estado_anterior = sub.estado
            if estado_anterior == Suscripcion.Estado.TRIAL:
                trials_vencidos += 1
                motivo = "Fin del periodo de prueba gratis: paso automático al plan Gratis"
            else:
                activas_vencidas += 1
                motivo = f"Suscripción vencida en plan {plan_anterior.nombre}: paso automático al plan Gratis"

            sub.plan = plan_gratis
            sub.estado = Suscripcion.Estado.ACTIVA
            sub.vence_en = None
            sub.save(update_fields=["plan", "estado", "vence_en", "actualizado_en"])

            HistorialSuscripcion.objects.create(
                suscripcion=sub,
                plan_anterior=plan_anterior,
                plan_nuevo=plan_gratis,
                estado_anterior=estado_anterior,
                estado_nuevo=Suscripcion.Estado.ACTIVA,
                motivo=motivo,
                fecha=ahora,
            )

    return {
        "procesadas": trials_vencidos + activas_vencidas,
        "trials_vencidos": trials_vencidos,
        "activas_vencidas": activas_vencidas,
    }


@transaction.atomic
def otorgar_cortesia(
    empresa: Empresa,
    *,
    motivo: str,
    dias: int | None = None,
    plan=None,
) -> Suscripcion:
    """Otorga días gratis o un plan de cortesía a una empresa dejando rastro en HistorialSuscripcion."""
    motivo_limpio = str(motivo or "").strip()
    if not motivo_limpio:
        raise ValidationError("El motivo de la cortesía es obligatorio.")

    dias_num = int(dias) if dias not in (None, "") else None
    if dias_num is not None and dias_num <= 0:
        raise ValidationError("Los días de cortesía deben ser mayores a 0.")
    if dias_num is None and plan is None:
        raise ValidationError("Debes indicar días gratis o un plan de cortesía.")

    plan_destino = _obtener_plan(plan) if plan is not None else None

    crear_suscripcion_inicial(empresa)
    suscripcion = (
        Suscripcion.objects.select_for_update()
        .select_related("plan")
        .get(empresa=empresa)
    )

    ahora = timezone.now()
    plan_anterior = suscripcion.plan
    estado_anterior = suscripcion.estado

    if plan_destino is not None:
        es_pago = plan_destino.precio_mensual > Decimal("0.00") or plan_destino.precio_anual > Decimal("0.00")
        suscripcion.plan = plan_destino
        suscripcion.estado = Suscripcion.Estado.ACTIVA
        if dias_num is not None:
            base = (
                suscripcion.vence_en
                if suscripcion.plan_id == plan_anterior.pk
                and suscripcion.vence_en is not None
                and suscripcion.vence_en > ahora
                else ahora
            )
            suscripcion.vence_en = base + timedelta(days=dias_num)
        elif es_pago:
            suscripcion.vence_en = ahora + timedelta(days=DIAS_CICLO_MENSUAL)
        else:
            suscripcion.vence_en = None
        if suscripcion.plan_id != plan_anterior.pk or estado_anterior in (
            Suscripcion.Estado.VENCIDA,
            Suscripcion.Estado.CANCELADA,
        ):
            suscripcion.inicia_en = ahora
    else:
        base = (
            suscripcion.vence_en
            if suscripcion.vence_en is not None and suscripcion.vence_en > ahora
            else ahora
        )
        suscripcion.vence_en = base + timedelta(days=dias_num)
        if suscripcion.estado in (Suscripcion.Estado.VENCIDA, Suscripcion.Estado.CANCELADA):
            suscripcion.estado = Suscripcion.Estado.ACTIVA
            suscripcion.inicia_en = ahora

    suscripcion.save(
        update_fields=["plan", "estado", "inicia_en", "vence_en", "actualizado_en"]
    )

    prefijo = "Cortesía"
    if plan_destino is not None and dias_num is not None:
        prefijo = f"Cortesía ({plan_destino.nombre}, {dias_num} días)"
    elif plan_destino is not None:
        prefijo = f"Cortesía (plan {plan_destino.nombre})"
    elif dias_num is not None:
        prefijo = f"Cortesía (+{dias_num} días)"

    HistorialSuscripcion.objects.create(
        suscripcion=suscripcion,
        plan_anterior=plan_anterior,
        plan_nuevo=suscripcion.plan,
        estado_anterior=estado_anterior,
        estado_nuevo=suscripcion.estado,
        motivo=f"{prefijo}: {motivo_limpio}"[:255],
        fecha=ahora,
    )
    empresa.suscripcion = suscripcion
    return suscripcion


DIAS_RECORDATORIO_VENCIMIENTO = (7, 3, 1)


def enviar_recordatorios_vencimiento(ahora=None, base_url: str = "") -> int:
    """Envía recordatorios por correo 7, 3 y 1 día antes de vencer Trial o suscripción paga (idempotente)."""
    from core.notificaciones import _enviar, correos_del_negocio

    ahora = ahora or timezone.now()
    hoy = timezone.localdate(ahora)
    enviados = 0

    candidatas = (
        Suscripcion.objects.select_related("empresa", "plan")
        .filter(
            empresa__activa=True,
            estado__in=[Suscripcion.Estado.TRIAL, Suscripcion.Estado.ACTIVA],
            vence_en__isnull=False,
            vence_en__gt=ahora,
        )
    )
    ruta_pago = f"{base_url.rstrip('/')}/panel/suscripcion/"

    for sub in candidatas:
        fecha_vence = timezone.localdate(sub.vence_en)
        dias_restantes = (fecha_vence - hoy).days
        if dias_restantes not in DIAS_RECORDATORIO_VENCIMIENTO:
            continue

        _, creado = RecordatorioVencimiento.objects.get_or_create(
            suscripcion=sub,
            dias_antes=dias_restantes,
            fecha_objetivo=fecha_vence,
        )
        if not creado:
            continue

        destinatarios = correos_del_negocio(sub.empresa)
        if not destinatarios:
            continue

        asunto = (
            f"Tu plan {sub.plan.nombre} vence en {dias_restantes} "
            f"día{'s' if dias_restantes != 1 else ''} · {sub.empresa.nombre}"
        )
        cuerpo = (
            f"Hola equipo de {sub.empresa.nombre},\n\n"
            f"Te recordamos que tu suscripción ({sub.get_estado_display()} - plan {sub.plan.nombre}) "
            f"vence el {fecha_vence.strftime('%d/%m/%Y')} (en {dias_restantes} día(s)).\n\n"
            f"Renueva o paga tu plan directamente aquí:\n{ruta_pago}\n"
        )
        if _enviar(asunto=asunto, mensaje=cuerpo, destinatarios=destinatarios) > 0:
            enviados += 1

    return enviados


