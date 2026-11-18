"""Cálculo de métricas SaaS para la consola de plataforma."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from suscripciones.models import CobroSuscripcion, HistorialSuscripcion, Suscripcion

CENTAVOS = Decimal("0.01")
MESES_ES = (
    "",
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)


def _ultimos_meses(ahora, cantidad: int = 6) -> list[tuple[int, int]]:
    anio = ahora.year
    mes = ahora.month
    resultado = []
    for _ in range(cantidad):
        resultado.append((anio, mes))
        mes -= 1
        if mes == 0:
            mes = 12
            anio -= 1
    resultado.reverse()
    return resultado


def calcular_metricas_saas(ahora=None) -> dict:
    """Calcula MRR, ARR, prueba, conversión 30d, vencimientos 7d e ingresos de los últimos 6 meses."""
    ahora = ahora or timezone.now()
    hace_30d = ahora - timedelta(days=30)
    en_7d = ahora + timedelta(days=7)

    suscripciones_pagas = (
        Suscripcion.objects.select_related("plan")
        .filter(empresa__activa=True, estado=Suscripcion.Estado.ACTIVA)
        .exclude(plan__codigo="gratis")
    )
    mrr = Decimal("0.00")
    for sub in suscripciones_pagas:
        plan = sub.plan
        if plan.precio_mensual <= Decimal("0.00") and plan.precio_anual <= Decimal("0.00"):
            continue
        base_mensual = (
            plan.precio_anual / Decimal("12")
            if sub.ciclo == Suscripcion.Ciclo.ANUAL
            else plan.precio_mensual
        )
        factor = (Decimal("100") - sub.descuento_porcentaje) / Decimal("100")
        mrr += base_mensual * factor

    mrr = mrr.quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    arr = (mrr * Decimal("12")).quantize(CENTAVOS, rounding=ROUND_HALF_UP)

    negocios_prueba = Suscripcion.objects.filter(
        empresa__activa=True,
        estado=Suscripcion.Estado.TRIAL,
    ).count()

    convertidos_ids = set(
        HistorialSuscripcion.objects.filter(
            fecha__gte=hace_30d,
            estado_anterior=Suscripcion.Estado.TRIAL,
            estado_nuevo=Suscripcion.Estado.ACTIVA,
        )
        .filter(Q(plan_nuevo__precio_mensual__gt=0) | Q(plan_nuevo__precio_anual__gt=0))
        .values_list("suscripcion_id", flat=True)
    )
    trials_iniciados_ids = set(
        HistorialSuscripcion.objects.filter(
            fecha__gte=hace_30d,
            estado_nuevo=Suscripcion.Estado.TRIAL,
        ).values_list("suscripcion_id", flat=True)
    )
    trials_activos_ids = set(
        Suscripcion.objects.filter(
            empresa__activa=True,
            estado=Suscripcion.Estado.TRIAL,
        ).values_list("id", flat=True)
    )
    universo_trial = convertidos_ids | trials_iniciados_ids | trials_activos_ids
    convertidos_30d = len(convertidos_ids)
    base_trial_30d = len(universo_trial)
    tasa_conversion_30d = (
        ((Decimal(convertidos_30d) * Decimal("100")) / Decimal(base_trial_30d)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if base_trial_30d > 0
        else Decimal("0.0")
    )

    vencimientos_qs = (
        Suscripcion.objects.select_related("empresa", "plan")
        .filter(
            empresa__activa=True,
            estado__in=[Suscripcion.Estado.TRIAL, Suscripcion.Estado.ACTIVA],
            vence_en__gte=ahora,
            vence_en__lte=en_7d,
        )
        .order_by("vence_en")
    )
    total_vencimientos_7d = vencimientos_qs.count()
    vencimientos_7d = list(vencimientos_qs[:20])

    meses = _ultimos_meses(ahora, 6)
    primer_anio, primer_mes = meses[0]
    inicio_ventana = timezone.make_aware(
        datetime(primer_anio, primer_mes, 1),
        timezone.get_current_timezone(),
    )

    agregados = (
        CobroSuscripcion.objects.filter(estado=CobroSuscripcion.Estado.APROBADO)
        .annotate(fecha_cobro=Coalesce("resuelto_en", "creado_en"))
        .filter(fecha_cobro__gte=inicio_ventana)
        .annotate(mes=TruncMonth("fecha_cobro"))
        .values("mes")
        .annotate(total=Sum("monto"), cantidad=Count("id"))
    )
    por_mes = {}
    for fila in agregados:
        mes_dt = fila["mes"]
        if mes_dt is not None:
            por_mes[(mes_dt.year, mes_dt.month)] = {
                "total": fila["total"] or Decimal("0.00"),
                "cantidad": fila["cantidad"] or 0,
            }

    ingresos_por_mes = []
    max_ingreso = Decimal("0.00")
    for anio, mes in meses:
        datos = por_mes.get((anio, mes), {"total": Decimal("0.00"), "cantidad": 0})
        if datos["total"] > max_ingreso:
            max_ingreso = datos["total"]
        ingresos_por_mes.append(
            {
                "clave": f"{anio}-{mes:02d}",
                "etiqueta": f"{MESES_ES[mes]} {anio}",
                "total": datos["total"],
                "cantidad": datos["cantidad"],
                "porcentaje_altura": 0,
            }
        )

    if max_ingreso > Decimal("0.00"):
        for item in ingresos_por_mes:
            if item["total"] > Decimal("0.00"):
                pct = int(((item["total"] / max_ingreso) * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                item["porcentaje_altura"] = max(pct, 6)

    total_ingresos_6m = sum((item["total"] for item in ingresos_por_mes), Decimal("0.00"))

    return {
        "mrr": mrr,
        "arr": arr,
        "negocios_prueba": negocios_prueba,
        "convertidos_30d": convertidos_30d,
        "base_trial_30d": base_trial_30d,
        "tasa_conversion_30d": tasa_conversion_30d,
        "total_vencimientos_7d": total_vencimientos_7d,
        "vencimientos_7d": vencimientos_7d,
        "ingresos_por_mes": ingresos_por_mes,
        "total_ingresos_6m": total_ingresos_6m,
    }
