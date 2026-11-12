"""
Servicios de Intersoft: aquí vive la LÓGICA DE NEGOCIO.

Las vistas reciben la petición y llaman a un servicio; el servicio hace el trabajo
y garantiza la integridad. Así la misma lógica sirve para la web, una API o un comando.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import Cliente, DetalleFactura, Empresa, Factura, MovimientoInventario, Producto

from .impuestos import CENTAVOS, calcular_iva


class StockInsuficiente(Exception):
    """Se intenta vender más unidades de las que hay."""


def siguiente_consecutivo(modelo, empresa):
    """Consecutivo sin duplicados: la fila de la empresa queda bloqueada hasta el final de la transacción."""
    Empresa.objects.select_for_update().get(pk=empresa.pk)
    ultimo = modelo.objects.filter(empresa=empresa).aggregate(m=Max("numero"))["m"] or 0
    return ultimo + 1


@transaction.atomic
def crear_factura(*, empresa, usuario, cliente, items):
    """
    Crea una factura completa: encabezado, líneas, descuento de stock y kardex.

    items = [{"producto": <Producto>, "cantidad": 2}, ...]

    @transaction.atomic = TODO O NADA. Si algo falla a mitad de camino,
    PostgreSQL deshace todo lo hecho dentro de la función.
    """
    if cliente.empresa_id != empresa.id:
        raise ValueError("El cliente no pertenece a esta empresa.")
    if not items:
        raise ValueError("La factura necesita al menos un producto.")

    # 1. Bloquear los productos que se van a vender.
    #    select_for_update = "nadie más toca estas filas hasta que yo termine".
    #    order_by("id") evita bloqueos cruzados (deadlocks) entre dos ventas simultáneas.
    ids = [item["producto"].id for item in items]
    productos = {
        p.id: p
        for p in Producto.objects.select_for_update()
        .filter(empresa=empresa, id__in=ids, activo=True)
        .order_by("id")
    }

    # 2. Validar TODO antes de escribir nada (acumulando líneas repetidas del mismo producto).
    acumulado = {}
    for item in items:
        producto = productos.get(item["producto"].id)
        raw_cantidad = item["cantidad"]
        if isinstance(raw_cantidad, bool):
            raise ValueError("La cantidad debe ser un número entero.")
        cantidad = int(raw_cantidad)
        if producto is None:
            raise ValueError("Producto inexistente, inactivo o de otra empresa.")
        if cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        total_producto = acumulado.get(producto.id, 0) + cantidad
        if producto.stock < total_producto:
            raise StockInsuficiente(
                f"Stock insuficiente de {producto.nombre}: hay {producto.stock}, se piden {total_producto}."
            )
        acumulado[producto.id] = total_producto

    # 3. Consecutivo sin duplicados e instantánea descriptiva.
    factura = Factura.objects.create(
        empresa=empresa,
        numero=siguiente_consecutivo(Factura, empresa),
        cliente=cliente,
        cliente_nombre=cliente.nombre,
        cliente_documento=f"{cliente.tipo_documento} {cliente.numero_documento}",
        empresa_nombre=empresa.nombre,
        empresa_nit=empresa.nit,
        empresa_direccion=empresa.direccion,
        empresa_telefono=empresa.telefono,
        creada_por=usuario,
    )

    # 4. Líneas, descuento de stock y kardex.
    subtotal = Decimal("0")
    iva = Decimal("0")
    for producto_id, cantidad in acumulado.items():
        producto = productos[producto_id]
        valor_linea = producto.precio * cantidad
        subtotal += valor_linea
        iva += calcular_iva(valor_linea, producto.iva_porcentaje)

        DetalleFactura.objects.create(
            empresa=empresa,
            factura=factura,
            producto=producto,
            nombre_producto=producto.nombre,
            cantidad=cantidad,
            precio_unitario=producto.precio,          # precio CONGELADO al vender
            iva_porcentaje=producto.iva_porcentaje,
        )
        # F() resta DENTRO de PostgreSQL, no en Python
        Producto.objects.filter(pk=producto.pk).update(stock=F("stock") - cantidad)
        MovimientoInventario.objects.create(
            empresa=empresa,
            producto=producto,
            tipo=MovimientoInventario.Tipo.SALIDA,
            cantidad=cantidad,
            referencia=f"Factura {factura.numero}",
            usuario=usuario,
        )

    # 5. Totales
    factura.subtotal = subtotal.quantize(CENTAVOS)
    factura.iva = iva
    factura.total = (subtotal + iva).quantize(CENTAVOS)
    factura.save(update_fields=["subtotal", "iva", "total"])
    return factura


@transaction.atomic
def crear_factura_desde_pedido(pedido):
    """Factura de un pedido pagado. No toca el stock: ya se descontó al reservar."""
    # Sin filtrar por activo: un cliente inactivo con el mismo documento se reutiliza, no se duplica
    cliente, _ = Cliente.objects.get_or_create(
        empresa_id=pedido.empresa_id,
        tipo_documento=pedido.tipo_documento,
        numero_documento=pedido.numero_documento,
        defaults={
            "nombre": pedido.nombre,
            "email": pedido.email,
            "telefono": pedido.telefono,
            "direccion": pedido.direccion,
        },
    )
    empresa = pedido.empresa
    factura = Factura.objects.create(
        empresa_id=pedido.empresa_id,
        numero=siguiente_consecutivo(Factura, empresa),
        cliente=cliente,
        cliente_nombre=cliente.nombre,
        cliente_documento=f"{cliente.tipo_documento} {cliente.numero_documento}",
        empresa_nombre=empresa.nombre,
        empresa_nit=empresa.nit,
        empresa_direccion=empresa.direccion,
        empresa_telefono=empresa.telefono,
        creada_por=pedido.comprador,
        subtotal=pedido.subtotal,
        iva=pedido.iva,
        total=pedido.total,
    )
    for linea in pedido.lineas.select_related("producto"):
        DetalleFactura.objects.create(
            empresa_id=pedido.empresa_id,
            factura=factura,
            producto_id=linea.producto_id,
            nombre_producto=linea.producto.nombre,
            cantidad=linea.cantidad,
            precio_unitario=linea.precio_unitario,
            iva_porcentaje=linea.iva_porcentaje,
        )
    return factura


@transaction.atomic
def anular_factura(*, factura, usuario):
    """Una factura NUNCA se borra: se anula y la mercancía vuelve al inventario."""
    factura = Factura.objects.select_for_update().get(pk=factura.pk)
    if factura.estado == Factura.Estado.ANULADA:
        raise ValueError("La factura ya está anulada.")

    if factura.esta_pagada:
        raise ValueError("No se puede anular una factura pagada; primero debe reembolsarse.")

    cartera = getattr(factura, "cuentacartera", None)
    if cartera is not None:
        if cartera.abonado > 0:
            raise ValueError("No se puede anular una factura con abonos registrados en cartera.")
        cartera.delete()

    for detalle in factura.detalles.all():
        Producto.objects.filter(pk=detalle.producto_id).update(stock=F("stock") + detalle.cantidad)
        MovimientoInventario.objects.create(
            empresa_id=factura.empresa_id,
            producto_id=detalle.producto_id,
            tipo=MovimientoInventario.Tipo.ENTRADA,
            cantidad=detalle.cantidad,
            referencia=f"Anulación factura {factura.numero}",
            usuario=usuario,
        )

    factura.estado = Factura.Estado.ANULADA
    factura.anulada_en = timezone.now()
    factura.save(update_fields=["estado", "anulada_en"])

    from .contabilidad_automatica import reversar_asiento_factura
    from .facturacion_electronica import emitir_nota_credito_electronica

    reversar_asiento_factura(factura=factura, usuario=usuario)
    if factura.estado_dian == Factura.EstadoDian.ACEPTADA and factura.cufe:
        factura = emitir_nota_credito_electronica(
            factura=factura, motivo=f"Anulación factura #{factura.numero}"
        )
    return factura

@transaction.atomic
def registrar_movimiento(*, empresa, producto, tipo, cantidad, usuario, referencia=""):
    """
    Único punto por el que cambia el stock (fuera de la facturación).

    - ENTRADA y SALIDA reciben cantidad positiva.
    - AJUSTE puede ser positivo (sobrante) o negativo (faltante, daño, pérdida).
    """
    cantidad = int(cantidad)
    Tipo = MovimientoInventario.Tipo

    if tipo in (Tipo.ENTRADA, Tipo.SALIDA) and cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor que cero.")
    if tipo == Tipo.AJUSTE and cantidad == 0:
        raise ValueError("Un ajuste no puede ser cero.")

    variacion = -cantidad if tipo == Tipo.SALIDA else cantidad

    # Bloqueamos el producto: si alguien factura al mismo tiempo, espera su turno
    producto = Producto.objects.select_for_update().get(pk=producto.pk, empresa=empresa)
    if producto.stock + variacion < 0:
        raise StockInsuficiente(
            f"El movimiento dejaría el stock de {producto.nombre} en negativo (disponible: {producto.stock})."
        )

    Producto.objects.filter(pk=producto.pk).update(stock=F("stock") + variacion)
    return MovimientoInventario.objects.create(
        empresa=empresa,
        producto=producto,
        tipo=tipo,
        cantidad=cantidad,
        referencia=referencia,
        usuario=usuario,
    )