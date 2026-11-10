"""Transiciones del ERP: validación, bloqueo y efectos atómicos."""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .impuestos import calcular_iva
from .models import (
    Empresa, Factura, Compra, CuentaCartera, MovimientoTesoreria, CuentaTesoreria,
    AsientoContable, LiquidacionNomina, Empleado, OrdenProduccion, Producto, Cita,
)
from .services import registrar_movimiento


def guardar(objeto):
    objeto.full_clean()
    objeto.save()
    return objeto


def bloquear(modelo, empresa, pk):
    # La empresa serializa las transiciones que afectan varios documentos.
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    return modelo.objects.select_for_update().get(empresa=empresa, pk=pk)


@transaction.atomic
def recibir_compra(*, empresa, pk, usuario):
    compra = bloquear(Compra, empresa, pk)
    if compra.recibida:
        return compra
    lineas = list(compra.lineas.select_related("producto"))
    if not lineas:
        raise ValidationError("Agrega al menos un producto antes de recibir la compra.")
    subtotal = iva = Decimal("0")
    for linea in lineas:
        linea.full_clean()
        subtotal += linea.costo * linea.cantidad
        iva += calcular_iva(linea.costo * linea.cantidad, linea.iva_porcentaje)
        registrar_movimiento(empresa=empresa, usuario=usuario, producto=linea.producto,
                             tipo="entrada", cantidad=linea.cantidad,
                             referencia=f"Compra {compra.referencia}"[:60])
    compra.subtotal, compra.iva = subtotal, iva
    compra.total = subtotal + iva
    compra.recibida = True
    guardar(compra)
    if compra.total > 0:
        guardar(CuentaCartera(empresa=empresa, tipo="pagar", tercero=compra.proveedor.nombre,
                             concepto=f"Compra {compra.referencia}", total=compra.total,
                             fecha=compra.fecha, vencimiento=compra.vencimiento, compra=compra))
    return compra


@transaction.atomic
def registrar_tesoreria(*, empresa, usuario, cuenta, monto, tipo, concepto, fecha,
                       operacion, referencia="", cartera=None):
    cuenta = bloquear(CuentaTesoreria, empresa, cuenta.pk)
    anterior = MovimientoTesoreria.objects.filter(operacion=operacion).first()
    if anterior:
        if (anterior.empresa_id != empresa.pk or anterior.cuenta_id != cuenta.pk
                or anterior.monto != monto or anterior.tipo != tipo
                or anterior.cartera_id != (cartera.pk if cartera else None)
                or anterior.concepto != concepto or anterior.fecha != fecha
                or anterior.referencia != referencia):
            raise ValidationError("Esta operación ya se utilizó con otros datos.")
        return anterior
    if not cuenta.activa:
        raise ValidationError("La cuenta de tesorería está inactiva.")
    if monto <= 0:
        raise ValidationError("El monto debe ser mayor que cero.")
    if cartera:
        cartera = bloquear(CuentaCartera, empresa, cartera.pk)
        if monto > cartera.saldo:
            raise ValidationError("El abono supera el saldo pendiente.")
        if tipo != ("ingreso" if cartera.tipo == "cobrar" else "egreso"):
            raise ValidationError("El tipo de movimiento no corresponde a la cuenta por cobrar/pagar.")
        cartera.abonado += monto
        guardar(cartera)
    return guardar(MovimientoTesoreria(empresa=empresa, cuenta=cuenta, monto=monto, tipo=tipo,
                   concepto=concepto, fecha=fecha, operacion=operacion, referencia=referencia,
                   cartera=cartera, usuario=usuario))


@transaction.atomic
def llevar_factura_a_cartera(*, empresa, pk, vencimiento):
    factura = bloquear(Factura, empresa, pk)
    existente = CuentaCartera.objects.filter(factura=factura).first()
    if existente:
        return existente
    if factura.estado == "anulada" or factura.esta_pagada or factura.total <= 0:
        raise ValidationError("Solo puedes llevar a cartera facturas vigentes, con saldo y sin pagos aprobados.")
    if factura.pagos.filter(estado="pendiente").exists():
        raise ValidationError("La factura tiene un intento de pago pendiente. Resuélvelo antes de llevarla a cartera.")
    return guardar(CuentaCartera(empresa=empresa, tipo="cobrar", tercero=factura.cliente.nombre,
                   concepto=f"Factura {factura.numero}", total=factura.total,
                   vencimiento=vencimiento, factura=factura))


@transaction.atomic
def confirmar_asiento(*, empresa, pk):
    asiento = bloquear(AsientoContable, empresa, pk)
    if asiento.confirmado:
        return asiento
    lineas = list(asiento.lineas.select_related("cuenta"))
    if len(lineas) < 2:
        raise ValidationError("Un asiento necesita al menos dos líneas.")
    for linea in lineas:
        linea.full_clean()
    debito = sum((l.debito for l in lineas), Decimal("0"))
    credito = sum((l.credito for l in lineas), Decimal("0"))
    if debito <= 0 or debito != credito:
        raise ValidationError("El asiento debe tener débitos y créditos iguales y mayores que cero.")
    asiento.confirmado = True
    return guardar(asiento)


@transaction.atomic
def aprobar_nomina(*, empresa, pk):
    nomina = bloquear(LiquidacionNomina, empresa, pk)
    if nomina.aprobada:
        return nomina
    if not nomina.empleado.activo:
        raise ValidationError("El empleado está inactivo.")
    if LiquidacionNomina.objects.filter(empresa=empresa, empleado=nomina.empleado, aprobada=True,
                                       desde__lte=nomina.hasta, hasta__gte=nomina.desde).exclude(pk=pk).exists():
        raise ValidationError("El empleado ya tiene una liquidación aprobada que cruza este período.")
    nomina.neto = nomina.base + nomina.adicionales - nomina.deducciones
    if nomina.neto <= 0:
        raise ValidationError("El neto a pagar debe ser mayor que cero.")
    nomina.cartera = guardar(CuentaCartera(empresa=empresa, tipo="pagar", tercero=nomina.empleado.nombre,
        concepto=f"Nómina {nomina.desde} / {nomina.hasta}", total=nomina.neto, vencimiento=nomina.hasta))
    nomina.aprobada = True
    return guardar(nomina)


@transaction.atomic
def completar_produccion(*, empresa, pk, usuario):
    orden = bloquear(OrdenProduccion, empresa, pk)
    if orden.completada:
        return orden
    insumos = list(orden.insumos.select_related("producto"))
    if not insumos:
        raise ValidationError("Agrega los insumos antes de completar la producción.")
    if not orden.producto.activo:
        raise ValidationError("El producto terminado está inactivo.")
    for insumo in insumos:
        insumo.full_clean()
        if insumo.producto_id == orden.producto_id:
            raise ValidationError("El producto terminado no puede ser su propio insumo.")
        if not insumo.producto.activo:
            raise ValidationError("Uno de los insumos está inactivo.")
        registrar_movimiento(empresa=empresa, usuario=usuario, producto=insumo.producto,
                             tipo="salida", cantidad=insumo.cantidad, referencia=f"Producción {str(pk)[:8]}")
    registrar_movimiento(empresa=empresa, usuario=usuario, producto=orden.producto,
                         tipo="entrada", cantidad=orden.cantidad, referencia=f"Producción {str(pk)[:8]}")
    orden.completada = True
    return guardar(orden)


@transaction.atomic
def reservar_cita(cita):
    bloquear(Empleado, cita.empresa, cita.empleado_id)
    if not cita.empleado.activo or not cita.servicio.activo or not cita.cliente.activo:
        raise ValidationError("El cliente, profesional y servicio deben estar activos.")
    cita.fin = cita.inicio + timedelta(minutes=cita.servicio.duracion_minutos)
    if Cita.objects.filter(empresa=cita.empresa, empleado=cita.empleado, estado="pendiente",
                           inicio__lt=cita.fin, fin__gt=cita.inicio).exclude(pk=cita.pk).exists():
        raise ValidationError("El profesional ya tiene una cita en ese horario.")
    cita.total = cita.servicio.precio + calcular_iva(cita.servicio.precio, cita.servicio.iva_porcentaje)
    return guardar(cita)


@transaction.atomic
def cambiar_cita(*, empresa, pk, estado):
    cita = bloquear(Cita, empresa, pk)
    if cita.estado != "pendiente":
        if cita.estado == estado:
            return cita
        raise ValidationError("La cita ya fue atendida o cancelada.")
    if estado not in ("atendida", "cancelada"):
        raise ValidationError("Estado de cita no válido.")
    if estado == "atendida" and cita.total > 0:
        cita.cartera = guardar(CuentaCartera(empresa=empresa, tipo="cobrar", tercero=cita.cliente.nombre,
                 concepto=f"Servicio: {cita.servicio.nombre}"[:200], total=cita.total, vencimiento=timezone.localdate()))
    cita.estado = estado
    return guardar(cita)
