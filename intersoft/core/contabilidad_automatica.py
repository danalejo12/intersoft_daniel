"""Automatización contable (asientos por evento con PUC base) y calculadora de aportes de nómina."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .erp_services import confirmar_asiento
from .impuestos import CENTAVOS, calcular_iva
from .models import AsientoContable, CuentaContable, LineaAsiento

CUENTAS_PUC_BASE = (
    ("1105", "Caja y bancos", "debito"),
    ("1305", "Clientes nacionales (Cuentas por cobrar)", "debito"),
    ("1435", "Inventario de mercancías", "debito"),
    ("2205", "Proveedores nacionales", "credito"),
    ("2408", "Impuesto sobre las ventas por pagar (IVA)", "credito"),
    ("2505", "Salarios y prestaciones por pagar", "credito"),
    ("4135", "Ingresos por comercio y ventas", "credito"),
    ("5105", "Gastos de personal (Nómina)", "debito"),
)


@transaction.atomic
def asegurar_cuentas_puc(empresa):
    """Garantiza que la empresa tenga creadas las cuentas contables base para contabilización automática."""
    cuentas = {}
    for codigo, nombre, naturaleza in CUENTAS_PUC_BASE:
        cuenta, _ = CuentaContable.objects.get_or_create(
            empresa=empresa,
            codigo=codigo,
            defaults={"nombre": nombre, "naturaleza": naturaleza},
        )
        cuentas[codigo] = cuenta
    return cuentas


def _crear_asiento_idempotente(*, empresa, usuario, referencia, concepto, fecha, movimientos):
    """Crea y confirma un asiento contable en partida doble si no existe uno con la misma referencia."""
    existente = AsientoContable.objects.filter(empresa=empresa, referencia=referencia).first()
    if existente is not None:
        return existente

    asiento = AsientoContable.objects.create(
        empresa=empresa,
        usuario=usuario,
        fecha=fecha or timezone.localdate(),
        concepto=concepto[:200],
        referencia=referencia[:100],
    )
    for cuenta, debito, credito in movimientos:
        if debito <= 0 and credito <= 0:
            continue
        LineaAsiento.objects.create(
            empresa=empresa,
            asiento=asiento,
            cuenta=cuenta,
            debito=debito.quantize(CENTAVOS),
            credito=credito.quantize(CENTAVOS),
        )
    return confirmar_asiento(empresa=empresa, pk=asiento.pk)


@transaction.atomic
def contabilizar_factura(*, factura, usuario=None):
    """Genera el asiento contable de causación de una factura emitida (1305 vs 4135 + 2408)."""
    if factura.estado == "anulada" or factura.total <= 0:
        raise ValueError("Solo se pueden contabilizar facturas vigentes con total positivo.")
    cuentas = asegurar_cuentas_puc(factura.empresa)
    ingreso_neto = (factura.total - factura.iva).quantize(CENTAVOS)
    movimientos = [
        (cuentas["1305"], factura.total, Decimal("0")),
        (cuentas["4135"], Decimal("0"), ingreso_neto),
    ]
    if factura.iva > 0:
        movimientos.append((cuentas["2408"], Decimal("0"), factura.iva))
    return _crear_asiento_idempotente(
        empresa=factura.empresa,
        usuario=usuario or factura.creada_por,
        referencia=f"FACT-{factura.numero}",
        concepto=f"Causación Factura #{factura.numero} · {factura.cliente.nombre}",
        fecha=timezone.localdate(),
        movimientos=movimientos,
    )


@transaction.atomic
def contabilizar_recaudo_factura(*, factura, monto=None, referencia_pago="PAGO", usuario=None):
    """Genera el asiento de recaudo (1105 Caja y bancos vs 1305 Clientes) causando primero la factura si falta."""
    if factura.estado == "anulada" or factura.total <= 0:
        raise ValueError("Solo se puede contabilizar el recaudo de facturas vigentes con total positivo.")
    contabilizar_factura(factura=factura, usuario=usuario)
    monto_recaudo = Decimal(str(monto if monto is not None else factura.total)).quantize(CENTAVOS)
    if monto_recaudo <= 0 or monto_recaudo > factura.total:
        raise ValueError("El monto del recaudo debe ser mayor que cero y no superar el total de la factura.")
    cuentas = asegurar_cuentas_puc(factura.empresa)
    sufijo = (str(referencia_pago or "PAGO").strip() or "PAGO")[:60]
    return _crear_asiento_idempotente(
        empresa=factura.empresa,
        usuario=usuario or factura.creada_por,
        referencia=f"REC-FACT-{factura.numero}-{sufijo}"[:100],
        concepto=f"Recaudo Factura #{factura.numero} ({sufijo}) · {factura.cliente.nombre}",
        fecha=timezone.localdate(),
        movimientos=[
            (cuentas["1105"], monto_recaudo, Decimal("0")),
            (cuentas["1305"], Decimal("0"), monto_recaudo),
        ],
    )


def saldo_contable_cliente_factura(*, factura):
    """Devuelve el saldo neto en la cuenta 1305 (Clientes) asociado a una factura (causación - recaudos - anulación)."""
    refs_exactas = [f"FACT-{factura.numero}", f"ANUL-FACT-{factura.numero}"]
    lineas_1305 = LineaAsiento.objects.filter(
        empresa=factura.empresa,
        cuenta__codigo="1305",
        asiento__confirmado=True,
    ).filter(
        asiento__referencia__in=refs_exactas
    ) | LineaAsiento.objects.filter(
        empresa=factura.empresa,
        cuenta__codigo="1305",
        asiento__confirmado=True,
        asiento__referencia__startswith=f"REC-FACT-{factura.numero}-",
    )
    totales = lineas_1305.aggregate(debito=Sum("debito"), credito=Sum("credito"))
    debito = totales["debito"] or Decimal("0.00")
    credito = totales["credito"] or Decimal("0.00")
    return (debito - credito).quantize(CENTAVOS)


@transaction.atomic
def reversar_asiento_factura(*, factura, usuario=None):
    """Si la factura tenía un asiento contable confirmado (FACT-n), genera su asiento inverso (ANUL-FACT-n)."""
    asiento_original = (
        AsientoContable.objects.filter(empresa=factura.empresa, referencia=f"FACT-{factura.numero}", confirmado=True)
        .prefetch_related("lineas__cuenta")
        .first()
    )
    if asiento_original is None:
        return None
    movimientos_inversos = [
        (linea.cuenta, linea.credito, linea.debito)
        for linea in asiento_original.lineas.all()
    ]
    return _crear_asiento_idempotente(
        empresa=factura.empresa,
        usuario=usuario or factura.creada_por,
        referencia=f"ANUL-FACT-{factura.numero}",
        concepto=f"Reversión por anulación Factura #{factura.numero} · {factura.cliente.nombre}",
        fecha=timezone.localdate(),
        movimientos=movimientos_inversos,
    )


@transaction.atomic
def contabilizar_compra(*, compra, usuario):
    """Genera el asiento contable de una compra recibida (1435 + 2408 vs 2205)."""
    if not compra.recibida or compra.total <= 0:
        raise ValueError("Solo se pueden contabilizar compras recibidas con total positivo.")
    cuentas = asegurar_cuentas_puc(compra.empresa)
    movimientos = [
        (cuentas["1435"], compra.subtotal, Decimal("0")),
    ]
    if compra.iva > 0:
        movimientos.append((cuentas["2408"], compra.iva, Decimal("0")))
    movimientos.append((cuentas["2205"], Decimal("0"), compra.total))
    return _crear_asiento_idempotente(
        empresa=compra.empresa,
        usuario=usuario,
        referencia=f"COMP-{compra.pk}",
        concepto=f"Compra {compra.referencia} · {compra.proveedor.nombre}",
        fecha=compra.fecha,
        movimientos=movimientos,
    )


@transaction.atomic
def contabilizar_movimiento_tesoreria(*, movimiento, usuario=None):
    """Genera el asiento contable de un ingreso o egreso de tesorería."""
    cuentas = asegurar_cuentas_puc(movimiento.empresa)
    monto = movimiento.monto
    if movimiento.tipo == "ingreso":
        contrapartida = cuentas["1305"] if movimiento.cartera_id else cuentas["4135"]
        lineas = [
            (cuentas["1105"], monto, Decimal("0")),
            (contrapartida, Decimal("0"), monto),
        ]
    else:
        contrapartida = cuentas["2205"] if movimiento.cartera_id else cuentas["5105"]
        lineas = [
            (contrapartida, monto, Decimal("0")),
            (cuentas["1105"], Decimal("0"), monto),
        ]
    return _crear_asiento_idempotente(
        empresa=movimiento.empresa,
        usuario=usuario or movimiento.usuario,
        referencia=f"TES-{movimiento.operacion}",
        concepto=f"Tesorería ({movimiento.tipo}): {movimiento.concepto}",
        fecha=movimiento.fecha,
        movimientos=lineas,
    )


@transaction.atomic
def contabilizar_nomina(*, nomina, usuario):
    """Genera el asiento contable de causación de una nómina aprobada (5105 vs 2505)."""
    if not nomina.aprobada or nomina.neto <= 0:
        raise ValueError("Solo se pueden contabilizar liquidaciones de nómina aprobadas.")
    cuentas = asegurar_cuentas_puc(nomina.empresa)
    return _crear_asiento_idempotente(
        empresa=nomina.empresa,
        usuario=usuario,
        referencia=f"NOM-{nomina.pk}",
        concepto=f"Nómina {nomina.empleado.nombre} ({nomina.desde} a {nomina.hasta})",
        fecha=nomina.hasta,
        movimientos=[
            (cuentas["5105"], nomina.neto, Decimal("0")),
            (cuentas["2505"], Decimal("0"), nomina.neto),
        ],
    )


def calcular_aportes_nomina_colombia(*, salario_base, adicionales_salariales=Decimal("0"), auxilio_transporte=Decimal("0")):
    """Calcula deducciones del trabajador y aportes/provisiones del empleador según porcentajes estándar."""
    base = Decimal(str(salario_base))
    adicionales = Decimal(str(adicionales_salariales))
    auxilio = Decimal(str(auxilio_transporte))
    if base <= 0:
        raise ValueError("El salario base debe ser mayor que cero.")
    if adicionales < 0 or auxilio < 0:
        raise ValueError("Los valores adicionales o de auxilio no pueden ser negativos.")

    ibc = (base + adicionales).quantize(CENTAVOS)
    base_prestaciones = (ibc + auxilio).quantize(CENTAVOS)

    salud_empleado = calcular_iva(ibc, Decimal("4.00"))
    pension_empleado = calcular_iva(ibc, Decimal("4.00"))
    total_deducciones_empleado = (salud_empleado + pension_empleado).quantize(CENTAVOS)
    neto_estimado = (base_prestaciones - total_deducciones_empleado).quantize(CENTAVOS)

    salud_empleador = calcular_iva(ibc, Decimal("8.50"))
    pension_empleador = calcular_iva(ibc, Decimal("12.00"))
    arl_riesgo_i = calcular_iva(ibc, Decimal("0.52"))
    caja_compensacion = calcular_iva(ibc, Decimal("4.00"))
    icbf_empleador = calcular_iva(ibc, Decimal("3.00"))
    sena_empleador = calcular_iva(ibc, Decimal("2.00"))
    cesantias = calcular_iva(base_prestaciones, Decimal("8.33"))
    prima = calcular_iva(base_prestaciones, Decimal("8.33"))
    vacaciones = calcular_iva(ibc, Decimal("4.17"))

    total_seguridad_social_empleador = (salud_empleador + pension_empleador + arl_riesgo_i).quantize(CENTAVOS)
    total_parafiscales = (caja_compensacion + icbf_empleador + sena_empleador).quantize(CENTAVOS)
    total_prestaciones = (cesantias + prima + vacaciones).quantize(CENTAVOS)
    costo_total_empleador = (
        base_prestaciones + total_seguridad_social_empleador + total_parafiscales + total_prestaciones
    ).quantize(CENTAVOS)

    return {
        "ibc": ibc,
        "salud_empleado": salud_empleado,
        "pension_empleado": pension_empleado,
        "deducciones_empleado": total_deducciones_empleado,
        "neto_estimado": neto_estimado,
        "salud_empleador": salud_empleador,
        "pension_empleador": pension_empleador,
        "arl_empleador": arl_riesgo_i,
        "caja_compensacion": caja_compensacion,
        "icbf_empleador": icbf_empleador,
        "sena_empleador": sena_empleador,
        "cesantias": cesantias,
        "prima": prima,
        "vacaciones": vacaciones,
        "total_seguridad_social_empleador": total_seguridad_social_empleador,
        "total_parafiscales": total_parafiscales,
        "total_prestaciones": total_prestaciones,
        "costo_total_empleador": costo_total_empleador,
    }
