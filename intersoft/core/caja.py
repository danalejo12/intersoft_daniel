"""Punto de venta: abrir caja, vender en el mostrador y cerrar con arqueo.

La venta reutiliza services.crear_factura: mismos precios, IVA, consecutivo y kardex
que el resto del sistema. Lo único nuevo es cómo se registra el pago.
"""
from decimal import Decimal, InvalidOperation
import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from .impuestos import CENTAVOS
from .models import Cliente, Factura, PagoCaja, TurnoCaja
from .services import StockInsuficiente, crear_factura

Metodo = PagoCaja.Metodo
# Documento que la DIAN usa para las ventas a quien no se identifica
DOCUMENTO_CONSUMIDOR_FINAL = "222222222222"
# Límite de los campos DecimalField(max_digits=14, decimal_places=2)
MAXIMO_DINERO = Decimal("999999999999.99")


class OperacionCaja(Exception):
    """El mensaje se le muestra al cajero."""


def dinero(valor, campo="valor"):
    """Convierte lo que llega del navegador en pesos con dos decimales, o falla con un mensaje claro."""
    if isinstance(valor, bool) or valor is None:
        raise OperacionCaja(f"El {campo} no es un número válido.")
    try:
        cantidad = Decimal(str(valor).replace(",", ".").strip() or "0")
    except (InvalidOperation, ValueError, TypeError):
        raise OperacionCaja(f"El {campo} no es un número válido.") from None
    if not cantidad.is_finite():
        raise OperacionCaja(f"El {campo} no es un número válido.")
    if cantidad < 0:
        raise OperacionCaja(f"El {campo} no puede ser negativo.")
    if cantidad > MAXIMO_DINERO:
        raise OperacionCaja(f"El {campo} supera el monto máximo permitido.")
    try:
        redondeado = cantidad.quantize(CENTAVOS)
    except InvalidOperation:
        raise OperacionCaja(f"El {campo} no es un número válido.") from None
    if cantidad != redondeado:
        raise OperacionCaja(f"El {campo} tiene más de dos decimales.")
    return redondeado


def pesos(valor):
    """$1.234.567,50 al estilo colombiano; sin decimales si son cero."""
    entero, decimales = f"{valor:.2f}".split(".")
    texto = f"{int(entero):,}".replace(",", ".")
    return f"${texto}" if decimales == "00" else f"${texto},{decimales}"


def turno_abierto(empresa, usuario):
    return TurnoCaja.objects.filter(empresa=empresa, cajero=usuario, cerrado_en__isnull=True).first()


def abrir_turno(*, empresa, usuario, base):
    if turno_abierto(empresa, usuario):
        raise OperacionCaja("Ya tienes una caja abierta.")
    try:
        with transaction.atomic():
            return TurnoCaja.objects.create(empresa=empresa, cajero=usuario, base_inicial=dinero(base, "valor de la base"))
    except IntegrityError:
        # Dos aperturas al mismo tiempo: la base de datos solo deja una
        raise OperacionCaja("Ya tienes una caja abierta.") from None


def consumidor_final(empresa):
    cliente, _ = Cliente.objects.get_or_create(
        empresa=empresa,
        tipo_documento=Cliente.TipoDocumento.CC,
        numero_documento=DOCUMENTO_CONSUMIDOR_FINAL,
        defaults={"nombre": "Consumidor final"},
    )
    return cliente


def _validar_pagos(pagos, total):
    """Calcula cómo se reparte el total. El efectivo cubre lo que falte y puede dar cambio."""
    if not isinstance(pagos, list) or not pagos:
        raise OperacionCaja("Indica cómo pagó el cliente.")

    efectivo = None
    otros = []
    for pago in pagos:
        if not isinstance(pago, dict):
            raise OperacionCaja("El pago no tiene un formato válido.")
        metodo = pago.get("metodo")
        if metodo == Metodo.EFECTIVO:
            if efectivo is not None:
                raise OperacionCaja("Registra el efectivo en una sola línea.")
            efectivo = dinero(pago.get("recibido"), "efectivo recibido")
        elif metodo in (Metodo.TARJETA, Metodo.TRANSFERENCIA):
            monto = dinero(pago.get("monto"), "monto")
            if monto > 0:
                otros.append((metodo, monto, str(pago.get("referencia") or "").strip()[:60]))
        else:
            raise OperacionCaja("Medio de pago no reconocido.")

    sin_efectivo = sum((monto for _, monto, _ in otros), Decimal("0"))
    if sin_efectivo > total:
        raise OperacionCaja("Los pagos con tarjeta o transferencia superan el total: el cambio solo se da en efectivo.")
    falta = total - sin_efectivo
    if falta > 0 and not efectivo:
        raise OperacionCaja(f"Falta por pagar {pesos(falta)}.")
    if efectivo and efectivo < falta:
        raise OperacionCaja("El efectivo recibido no alcanza para completar el pago.")
    if falta == 0 and efectivo:
        raise OperacionCaja("El total ya está cubierto: quita el efectivo.")
    return otros, (falta, efectivo) if falta > 0 else None


@transaction.atomic
def registrar_venta(*, turno, usuario, items, pagos, cliente=None, operacion=None):
    """Crea la factura, descuenta el stock y registra los pagos: todo o nada."""
    operacion_uuid = None
    if operacion is not None:
        if isinstance(operacion, bool):
            raise OperacionCaja("La clave de operación no es válida.")
        try:
            operacion_uuid = operacion if isinstance(operacion, uuid.UUID) else uuid.UUID(str(operacion))
        except (ValueError, TypeError, AttributeError):
            raise OperacionCaja("La clave de operación no es válida.") from None

    turno = TurnoCaja.objects.select_for_update().get(pk=turno.pk)
    if turno.cajero_id != usuario.pk:
        raise OperacionCaja("Solo el cajero que abrió la caja puede vender en ella.")
    if not items:
        raise OperacionCaja("Agrega al menos un producto.")
    if cliente is not None and cliente.empresa_id != turno.empresa_id:
        raise OperacionCaja("El cliente no pertenece a este negocio.")

    if operacion_uuid is not None:
        existente = Factura.objects.filter(empresa=turno.empresa, operacion_pos=operacion_uuid).first()
        if existente is not None:
            if existente.turno_id != turno.pk:
                raise OperacionCaja("Esta clave de operación ya fue usada en otra caja.")
            cantidades_pedidas = {}
            for item in items:
                prod = item["producto"]
                cantidades_pedidas[prod.pk] = cantidades_pedidas.get(prod.pk, 0) + int(item["cantidad"])
            cantidades_existentes = {d.producto_id: d.cantidad for d in existente.detalles.all()}
            cliente_esperado = cliente.pk if cliente is not None else consumidor_final(turno.empresa).pk
            if cantidades_pedidas != cantidades_existentes or existente.cliente_id != cliente_esperado:
                raise OperacionCaja("Esta clave de operación ya fue usada con otros datos.")
            return existente

    if not turno.abierto:
        raise OperacionCaja("Esta caja ya está cerrada. Abre una nueva para seguir vendiendo.")

    try:
        factura = crear_factura(
            empresa=turno.empresa, usuario=usuario, cliente=cliente or consumidor_final(turno.empresa), items=items
        )
    except StockInsuficiente as error:
        raise OperacionCaja(str(error)) from None  # en el panel sí se muestra el stock exacto
    except ValueError as error:
        raise OperacionCaja(str(error)) from None
    if factura.total > MAXIMO_DINERO:
        raise OperacionCaja("El total de la venta supera el monto máximo permitido.")
    factura.turno = turno
    factura.operacion_pos = operacion_uuid
    factura.save(update_fields=["turno", "operacion_pos"])

    # Se valida con el total que calculó el servidor, nunca con el del navegador
    otros, efectivo = _validar_pagos(pagos, factura.total)
    for metodo, monto, referencia in otros:
        PagoCaja.objects.create(
            empresa=turno.empresa, turno=turno, factura=factura, metodo=metodo, monto=monto, referencia=referencia
        )
    if efectivo:
        falta, recibido = efectivo
        PagoCaja.objects.create(
            empresa=turno.empresa, turno=turno, factura=factura, metodo=Metodo.EFECTIVO,
            monto=falta, recibido=recibido, cambio=recibido - falta,
        )
    return factura


def resumen_turno(turno):
    """Ventas y dinero del turno, separado por medio de pago."""
    por_metodo = {fila["metodo"]: fila["total"] for fila in turno.pagos.values("metodo").annotate(total=Sum("monto"))}
    ventas = turno.facturas.aggregate(cantidad=Count("id"), total=Sum("total"))
    efectivo = por_metodo.get(Metodo.EFECTIVO, Decimal("0"))
    return {
        "ventas": ventas["cantidad"],
        "total_vendido": ventas["total"] or Decimal("0"),
        "por_metodo": [(etiqueta, por_metodo.get(valor, Decimal("0"))) for valor, etiqueta in Metodo.choices],
        "efectivo_ventas": efectivo,
        "efectivo_esperado": turno.base_inicial + efectivo,
    }


@transaction.atomic
def cerrar_turno(*, turno, usuario, contado, observaciones=""):
    """Arqueo a ciegas: el cajero cuenta sin ver lo esperado y el sistema calcula la diferencia."""
    turno = TurnoCaja.objects.select_for_update().get(pk=turno.pk)
    if not turno.abierto:
        raise OperacionCaja("Esta caja ya estaba cerrada.")
    if turno.cajero_id != usuario.pk:
        raise OperacionCaja("Solo el cajero que abrió la caja puede cerrarla.")
    contado = dinero(contado, "efectivo contado")
    esperado = resumen_turno(turno)["efectivo_esperado"]
    turno.cerrado_en = timezone.now()
    turno.efectivo_esperado = esperado
    turno.efectivo_contado = contado
    turno.diferencia = contado - esperado
    turno.observaciones = observaciones.strip()[:1000]
    turno.save()
    return turno
